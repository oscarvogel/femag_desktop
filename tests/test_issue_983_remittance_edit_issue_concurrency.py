"""#983: edicion y emision concurrentes del mismo remito.

La evidencia fuerte corre contra MySQL/MariaDB con tablas InnoDB y conexiones
independientes. SQLite se usa para los flujos secuenciales y la UI.

Variables para el MySQL de pruebas:

    FEMAG_TEST_MYSQL_HOST=127.0.0.1
    FEMAG_TEST_MYSQL_PORT=3307
    FEMAG_TEST_MYSQL_USER=root
    FEMAG_TEST_MYSQL_PASSWORD=...

Cada test crea una base descartable ``femag_test_983_*`` y la elimina.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import date
from decimal import Decimal

import pymysql
import pytest
from peewee import MySQLDatabase
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

from app.config.database import bind_database, database_proxy
from app.models import ALL_MODELS, SYNC_MODELS
from app.models.audit import AuditLog
from app.models.remittances import Remittance, RemittanceSeries
from app.services.remittance_service import (
    RemittanceChangedElsewhere,
    RemittanceEditConflict,
    RemittanceIssueBlocked,
    RemittanceSeriesService,
    RemittanceService,
)
from app.ui.remittances import RemittanceDialog, RemittancesPage
from tests.conftest import _f150_ready_master_data

ISSUED_FROM_OTHER_STATION = (
    "Este remito fue emitido desde otro puesto mientras usted lo estaba "
    "editando. No es posible guardar las modificaciones. Actualice la "
    "información para consultar el remito emitido."
)


def _series(next_number: int = 700) -> RemittanceSeries:
    return RemittanceSeriesService("admin").save(
        name=f"Talonario 983 {next_number}",
        point_of_sale="0001",
        next_number=next_number,
        is_default=True,
    )


def _draft(data, series: RemittanceSeries) -> Remittance:
    return RemittanceService("admin").create_manual(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        truck=data["truck"],
        driver=data["driver"],
        series=series,
        remittance_date=date(2026, 11, 26),
        items=[{"product": data["product"], "quantity": Decimal("10")}],
    )


def _audit_count(remittance_id: int, action: str) -> int:
    return (
        AuditLog.select()
        .where(
            (AuditLog.record_ref == f"Remittance:{remittance_id}")
            & (AuditLog.action == action)
        )
        .count()
    )


def test_update_after_issue_has_exact_message_and_no_overwrite(db):
    data = _f150_ready_master_data()
    series = _series()
    service = RemittanceService("admin")
    draft = _draft(data, series)
    stale = Remittance.get_by_id(draft.id)
    stale_version = RemittanceService.edit_version(stale)

    issued = service.issue(Remittance.get_by_id(draft.id))
    original_observations = issued.observations

    with pytest.raises(RemittanceEditConflict) as error:
        service.update_draft(
            stale,
            expected_version=stale_version,
            observations="intento de A",
        )

    assert str(error.value) == ISSUED_FROM_OTHER_STATION
    current = Remittance.get_by_id(issued.id)
    assert current.status == Remittance.STATUS_ISSUED
    assert current.observations == original_observations
    assert RemittanceSeries.get_by_id(series.id).next_number == 701
    assert _audit_count(issued.id, "emitir") == 1
    assert _audit_count(issued.id, "modificar") == 0


def test_stale_draft_update_after_other_edit_rejects(db):
    data = _f150_ready_master_data()
    series = _series()
    service = RemittanceService("admin")
    draft = _draft(data, series)
    stale = Remittance.get_by_id(draft.id)
    stale_version = RemittanceService.edit_version(stale)

    service.update_draft(
        Remittance.get_by_id(draft.id), observations="editado por B"
    )

    with pytest.raises(RemittanceEditConflict) as error:
        service.update_draft(
            stale,
            expected_version=stale_version,
            observations="intento de A",
        )

    assert "fue modificado desde otro puesto" in str(error.value)
    current = Remittance.get_by_id(draft.id)
    assert current.observations == "editado por B"
    assert _audit_count(draft.id, "modificar") == 1


def test_issue_with_stale_screen_version_rejects(db):
    data = _f150_ready_master_data()
    series = _series()
    service = RemittanceService("admin")
    draft = _draft(data, series)
    stale_version = RemittanceService.edit_version(
        Remittance.get_by_id(draft.id)
    )

    service.update_draft(
        Remittance.get_by_id(draft.id), observations="editado por B"
    )

    with pytest.raises(RemittanceChangedElsewhere) as error:
        service.issue(
            Remittance.get_by_id(draft.id), expected_version=stale_version
        )

    assert "fue modificado desde otro puesto" in str(error.value)
    current = Remittance.get_by_id(draft.id)
    assert current.status == Remittance.STATUS_DRAFT
    assert current.observations == "editado por B"
    assert RemittanceSeries.get_by_id(series.id).next_number == 700
    assert _audit_count(draft.id, "emitir") == 0


def test_draft_can_save_invalid_f150_data_and_issue_blocks(db):
    data = _f150_ready_master_data()
    series = _series()
    service = RemittanceService("admin")
    draft = _draft(data, series)

    updated = service.update_draft(
        Remittance.get_by_id(draft.id),
        items=[{"product": data["other_product"], "quantity": Decimal("5")}],
    )
    assert updated.items[0].product_id == data["other_product"].id

    with pytest.raises(RemittanceIssueBlocked) as error:
        service.issue(Remittance.get_by_id(draft.id))

    assert any("sin rubros DGR" in issue for issue in error.value.issues)
    assert Remittance.get_by_id(draft.id).status == Remittance.STATUS_DRAFT
    assert RemittanceSeries.get_by_id(series.id).next_number == 700
    assert _audit_count(draft.id, "emitir") == 0


def test_update_draft_rolls_back_on_audit_error(db):
    data = _f150_ready_master_data()
    series = _series()
    service = RemittanceService("admin")
    draft = _draft(data, series)
    current = Remittance.get_by_id(draft.id)
    original_observations = current.observations
    original_address = (
        current.delivery_address_text,
        current.delivery_city,
        current.delivery_province,
    )
    original_items = [
        (item.product_id, str(item.quantity)) for item in current.items
    ]
    original_carrier = (current.carrier_id, current.carrier_name)

    def boom(**_kwargs):
        raise RuntimeError("fallo de auditoria")

    service.audit_service.record = boom
    with pytest.raises(RuntimeError, match="fallo de auditoria"):
        service.update_draft(
            current,
            observations="no debe quedar",
            items=[
                {
                    "product": data["other_product"],
                    "quantity": Decimal("7"),
                }
            ],
        )

    after = Remittance.get_by_id(draft.id)
    assert after.observations == original_observations
    assert (
        after.delivery_address_text,
        after.delivery_city,
        after.delivery_province,
    ) == original_address
    assert [
        (item.product_id, str(item.quantity)) for item in after.items
    ] == original_items
    assert (after.carrier_id, after.carrier_name) == original_carrier
    assert _audit_count(draft.id, "modificar") == 0


def test_dialog_save_after_issue_shows_exact_message(db, monkeypatch):
    data = _f150_ready_master_data()
    series = _series()
    draft = _draft(data, series)
    app = QApplication.instance() or QApplication([])
    dialog = RemittanceDialog(
        current_user="admin", remittance=Remittance.get_by_id(draft.id)
    )
    app.processEvents()
    RemittanceService("admin").issue(Remittance.get_by_id(draft.id))

    warnings = []
    accepted = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )
    monkeypatch.setattr(dialog, "accept", lambda: accepted.append(True))

    dialog._save()

    assert accepted == []
    assert len(warnings) == 1
    assert warnings[0][0] == "Remito no guardado"
    assert warnings[0][1] == ISSUED_FROM_OTHER_STATION


def test_page_issue_with_stale_version_shows_message(db, tmp_path, monkeypatch):
    data = _f150_ready_master_data()
    series = _series()
    service = RemittanceService("admin")
    draft = _draft(data, series)
    app = QApplication.instance() or QApplication([])
    page = RemittancesPage(
        current_user="admin", output_dir=tmp_path, f150_output_dir=tmp_path
    )
    row = next(
        index
        for index in range(page.table.rowCount())
        if page.table.item(index, 0).data(Qt.UserRole) == draft.id
    )
    page.table.setCurrentCell(row, 0)
    stale_version = page._selected_version()
    service.update_draft(
        Remittance.get_by_id(draft.id), observations="editado por B"
    )

    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )

    page._issue()
    app.processEvents()

    assert warnings
    assert warnings[0][0] == "Remito desactualizado"
    assert "fue modificado desde otro puesto" in warnings[0][1]
    assert Remittance.get_by_id(draft.id).status == Remittance.STATUS_DRAFT
    assert stale_version is not None


def test_edit_version_changes_when_items_change(db):
    data = _f150_ready_master_data()
    series = _series()
    service = RemittanceService("admin")
    draft = _draft(data, series)
    before = RemittanceService.edit_version(Remittance.get_by_id(draft.id))

    service.update_draft(
        Remittance.get_by_id(draft.id),
        items=[{"product": data["other_product"], "quantity": Decimal("3")}],
    )

    after = RemittanceService.edit_version(Remittance.get_by_id(draft.id))
    assert before != after


def _mysql_config() -> dict | None:
    host = os.getenv("FEMAG_TEST_MYSQL_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.getenv("FEMAG_TEST_MYSQL_PORT", "3306")),
        "user": os.getenv("FEMAG_TEST_MYSQL_USER", "root"),
        "password": os.getenv("FEMAG_TEST_MYSQL_PASSWORD", ""),
    }


@pytest.fixture()
def mysql_models():
    config = _mysql_config()
    if config is None:
        pytest.skip("MySQL de pruebas no configurado (FEMAG_TEST_MYSQL_*)")

    admin = pymysql.connect(**config, autocommit=True)
    database_name = f"femag_test_983_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    with admin.cursor() as cursor:
        cursor.execute(
            f"CREATE DATABASE `{database_name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )

    database = MySQLDatabase(
        database_name,
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        charset="utf8mb4",
    )
    previous = database_proxy.obj
    bind_database(database)
    database.connect()
    try:
        database.create_tables([*ALL_MODELS, *SYNC_MODELS])
        engines = database.execute_sql(
            "SELECT table_name, engine FROM information_schema.tables "
            "WHERE table_schema = %s",
            (database_name,),
        ).fetchall()
        assert engines
        assert all((engine or "").upper() == "INNODB" for _, engine in engines)
        yield database
    finally:
        database.close()
        bind_database(previous)
        try:
            with admin.cursor() as cursor:
                cursor.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
        finally:
            admin.close()


def _connection_id() -> int:
    row = database_proxy.obj.execute_sql("SELECT CONNECTION_ID()").fetchone()
    return int(row[0])


def _run_two_workers(functions) -> list[dict]:
    barrier = threading.Barrier(2)
    results: list[dict] = []

    def runner(function):
        try:
            barrier.wait(timeout=15)
            value = function()
            results.append(
                {
                    "ok": True,
                    "value": value,
                    "connection": _connection_id(),
                }
            )
        except Exception as exc:  # noqa: BLE001 - el test compara el tipo exacto
            results.append(
                {
                    "ok": False,
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "connection": _connection_id(),
                }
            )
        finally:
            database_proxy.obj.close()

    threads = [threading.Thread(target=runner, args=(fn,)) for fn in functions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert all(not thread.is_alive() for thread in threads), "hilo colgado"
    assert len(results) == 2, results
    return results


def _run_ordered(first, first_ready: threading.Event, second) -> list[dict]:
    """Ejecuta ``first``, espera que tome el lock y recien ahi lanza ``second``."""
    results: list[dict] = []

    def runner(function):
        try:
            value = function()
            results.append(
                {
                    "ok": True,
                    "value": value,
                    "connection": _connection_id(),
                }
            )
        except Exception as exc:  # noqa: BLE001 - el test compara el tipo exacto
            results.append(
                {
                    "ok": False,
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "connection": _connection_id(),
                }
            )
        finally:
            database_proxy.obj.close()

    first_thread = threading.Thread(target=runner, args=(first,))
    first_thread.start()
    assert first_ready.wait(timeout=15), "la primera operacion no tomo el lock"
    second_thread = threading.Thread(target=runner, args=(second,))
    second_thread.start()
    for thread in (first_thread, second_thread):
        thread.join(timeout=30)
    assert all(
        not thread.is_alive() for thread in (first_thread, second_thread)
    ), "hilo colgado"
    assert len(results) == 2, results
    return results


def _slow_replace_items(
    monkeypatch, delay: float = 0.8, ready: threading.Event | None = None
) -> None:
    original = RemittanceService._replace_items

    def slow(remittance, items):
        if ready is not None:
            ready.set()
        time.sleep(delay)
        return original(remittance, items)

    monkeypatch.setattr(
        RemittanceService, "_replace_items", staticmethod(slow)
    )


def _slow_freeze_prices(
    monkeypatch, delay: float = 0.8, ready: threading.Event | None = None
) -> None:
    original = RemittanceService._freeze_item_prices

    def slow(remittance):
        if ready is not None:
            ready.set()
        time.sleep(delay)
        return original(remittance)

    monkeypatch.setattr(
        RemittanceService, "_freeze_item_prices", staticmethod(slow)
    )


def test_mysql_update_first_then_issue_waits_and_uses_new_data(
    mysql_models, monkeypatch
):
    data = _f150_ready_master_data()
    series = _series()
    draft = _draft(data, series)
    ready = threading.Event()
    _slow_replace_items(monkeypatch, ready=ready)

    def update():
        return RemittanceService("A").update_draft(
            Remittance.get_by_id(draft.id),
            observations="EDITADO-A",
            items=[
                {
                    "product": data["product"],
                    "quantity": Decimal("12"),
                }
            ],
        )

    def issue():
        return RemittanceService("B").issue(Remittance.get_by_id(draft.id))

    results = _run_ordered(update, ready, issue)
    assert all(row["ok"] for row in results), results
    assert len({row["connection"] for row in results}) == 2

    current = Remittance.get_by_id(draft.id)
    assert current.status == Remittance.STATUS_ISSUED
    assert current.observations == "EDITADO-A"
    assert current.items[0].quantity == Decimal("12.000")
    assert RemittanceSeries.get_by_id(series.id).next_number == 701
    assert _audit_count(draft.id, "modificar") == 1
    assert _audit_count(draft.id, "emitir") == 1


def test_mysql_update_first_invalid_f150_then_issue_blocks(
    mysql_models, monkeypatch
):
    data = _f150_ready_master_data()
    series = _series()
    draft = _draft(data, series)
    ready = threading.Event()
    _slow_replace_items(monkeypatch, ready=ready)

    def update():
        return RemittanceService("A").update_draft(
            Remittance.get_by_id(draft.id),
            items=[
                {
                    "product": data["other_product"],
                    "quantity": Decimal("5"),
                }
            ],
        )

    def issue():
        return RemittanceService("B").issue(Remittance.get_by_id(draft.id))

    results = _run_ordered(update, ready, issue)
    update_result = next(row for row in results if row["ok"])
    issue_result = next(row for row in results if not row["ok"])
    assert update_result["ok"]
    assert issue_result["type"] == "RemittanceIssueBlocked"
    assert "sin rubros DGR" in issue_result["message"]

    current = Remittance.get_by_id(draft.id)
    assert current.status == Remittance.STATUS_DRAFT
    assert current.items[0].product_id == data["other_product"].id
    assert RemittanceSeries.get_by_id(series.id).next_number == 700
    assert _audit_count(draft.id, "emitir") == 0


def test_mysql_issue_first_then_stale_update_rejects(
    mysql_models, monkeypatch
):
    data = _f150_ready_master_data()
    series = _series()
    draft = _draft(data, series)
    stale = Remittance.get_by_id(draft.id)
    stale_version = RemittanceService.edit_version(stale)
    ready = threading.Event()
    _slow_freeze_prices(monkeypatch, ready=ready)

    def issue():
        return RemittanceService("A").issue(Remittance.get_by_id(draft.id))

    def update():
        return RemittanceService("B").update_draft(
            stale,
            expected_version=stale_version,
            observations="INTENTO-B",
        )

    results = _run_ordered(issue, ready, update)
    issue_result = next(row for row in results if row["ok"])
    update_result = next(row for row in results if not row["ok"])
    assert issue_result["ok"]
    assert update_result["type"] == "RemittanceEditConflict"
    assert update_result["message"] == ISSUED_FROM_OTHER_STATION

    current = Remittance.get_by_id(draft.id)
    assert current.status == Remittance.STATUS_ISSUED
    assert current.observations is None
    assert RemittanceSeries.get_by_id(series.id).next_number == 701
    assert _audit_count(draft.id, "emitir") == 1
    assert _audit_count(draft.id, "modificar") == 0


def test_mysql_two_concurrent_edits_one_wins(mysql_models, monkeypatch):
    data = _f150_ready_master_data()
    series = _series()
    draft = _draft(data, series)
    first = Remittance.get_by_id(draft.id)
    second = Remittance.get_by_id(draft.id)
    first_version = RemittanceService.edit_version(first)
    second_version = RemittanceService.edit_version(second)
    _slow_replace_items(monkeypatch, delay=0.5)

    def update_first():
        return RemittanceService("A").update_draft(
            first,
            expected_version=first_version,
            observations="A",
            items=[
                {"product": data["product"], "quantity": Decimal("11")}
            ],
        )

    def update_second():
        return RemittanceService("B").update_draft(
            second,
            expected_version=second_version,
            observations="B",
            items=[
                {"product": data["product"], "quantity": Decimal("22")}
            ],
        )

    results = _run_two_workers([update_first, update_second])
    winner = next(row for row in results if row["ok"])
    loser = next(row for row in results if not row["ok"])
    assert winner["ok"]
    assert loser["type"] == "RemittanceEditConflict"
    assert "fue modificado desde otro puesto" in loser["message"]

    current = Remittance.get_by_id(draft.id)
    final_pair = (current.observations, current.items[0].quantity)
    assert final_pair in {
        ("A", Decimal("11.000")),
        ("B", Decimal("22.000")),
    }
    assert _audit_count(draft.id, "modificar") == 1


def test_mysql_stale_issue_screen_rejects(mysql_models):
    data = _f150_ready_master_data()
    series = _series()
    service = RemittanceService("A")
    draft = _draft(data, series)
    stale_version = RemittanceService.edit_version(
        Remittance.get_by_id(draft.id)
    )

    service.update_draft(
        Remittance.get_by_id(draft.id), observations="EDITADO-B"
    )

    with pytest.raises(RemittanceChangedElsewhere):
        service.issue(
            Remittance.get_by_id(draft.id), expected_version=stale_version
        )

    current = Remittance.get_by_id(draft.id)
    assert current.status == Remittance.STATUS_DRAFT
    assert current.observations == "EDITADO-B"
    assert RemittanceSeries.get_by_id(series.id).next_number == 700
    assert _audit_count(draft.id, "emitir") == 0


def test_mysql_update_rolls_back_on_audit_error(mysql_models):
    data = _f150_ready_master_data()
    series = _series()
    service = RemittanceService("A")
    draft = _draft(data, series)
    current = Remittance.get_by_id(draft.id)
    original_address = (
        current.delivery_address_text,
        current.delivery_city,
        current.delivery_province,
    )
    original_items = [
        (item.product_id, str(item.quantity)) for item in current.items
    ]

    def boom(**_kwargs):
        raise RuntimeError("fallo de auditoria MySQL")

    service.audit_service.record = boom
    with pytest.raises(RuntimeError, match="fallo de auditoria MySQL"):
        service.update_draft(
            current,
            observations="no debe quedar",
            items=[
                {"product": data["other_product"], "quantity": Decimal("8")}
            ],
        )

    after = Remittance.get_by_id(draft.id)
    assert after.observations is None
    assert (
        after.delivery_address_text,
        after.delivery_city,
        after.delivery_province,
    ) == original_address
    assert [
        (item.product_id, str(item.quantity)) for item in after.items
    ] == original_items
    assert _audit_count(draft.id, "modificar") == 0
