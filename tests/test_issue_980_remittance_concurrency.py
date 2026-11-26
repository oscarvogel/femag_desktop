"""#980: una sola emision por remito aunque dos puestos lo intenten a la vez.

La prueba de fondo corre contra MySQL/MariaDB de pruebas con conexiones
independientes. SQLite se usa solo para el mensaje secuencial y la UI, porque no
tiene bloqueos de fila ``FOR UPDATE``.

Configuracion del MySQL de pruebas (variables de entorno):

    FEMAG_TEST_MYSQL_HOST=127.0.0.1
    FEMAG_TEST_MYSQL_PORT=3307
    FEMAG_TEST_MYSQL_USER=root
    FEMAG_TEST_MYSQL_PASSWORD=...

Cada test crea una base descartable ``femag_test_980_*`` y la elimina al final.
Si las variables no estan, los tests MySQL se saltan y queda claro el motivo.
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

from app.config.database import bind_database, database_proxy
from app.models import ALL_MODELS, SYNC_MODELS
from app.models.audit import AuditLog
from app.models.remittances import Remittance, RemittanceSeries
from app.services.remittance_service import (
    RemittanceAlreadyIssued,
    RemittanceIssueBlocked,
    RemittanceSeriesService,
    RemittanceService,
)
from tests.conftest import _f150_ready_master_data


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
    database_name = f"femag_test_980_{os.getpid()}_{uuid.uuid4().hex[:8]}"
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


def _make_series(*, next_number: int) -> RemittanceSeries:
    return RemittanceSeriesService("admin").save(
        name=f"Talonario 980 {next_number}",
        point_of_sale="0001",
        next_number=next_number,
        is_default=True,
    )


def _make_draft(data, series: RemittanceSeries) -> Remittance:
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


def _connection_id() -> int:
    row = database_proxy.obj.execute_sql("SELECT CONNECTION_ID()").fetchone()
    return int(row[0])


def _issue_worker(remittance_id: int, user: str, barrier, results: list) -> None:
    try:
        barrier.wait(timeout=15)
        issued = RemittanceService(user).issue(
            Remittance.get_by_id(remittance_id)
        )
        results.append(
            {
                "ok": True,
                "physical_number": issued.physical_number,
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


def _run_two_workers(remittance_ids: tuple[int, int]):
    barrier = threading.Barrier(2)
    results: list[dict] = []
    threads = [
        threading.Thread(
            target=_issue_worker,
            args=(remittance_id, f"operador_{index}", barrier, results),
        )
        for index, remittance_id in enumerate(remittance_ids)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert all(not thread.is_alive() for thread in threads), "hilo de emision colgado"
    assert len(results) == 2, results
    return results


def _slow_freeze(monkeypatch, delay: float = 0.8) -> None:
    original = RemittanceService._freeze_item_prices

    def slow(remittance):
        time.sleep(delay)
        return original(remittance)

    monkeypatch.setattr(
        RemittanceService, "_freeze_item_prices", staticmethod(slow)
    )


def test_issue_already_issued_raises_clear_message_without_extra_effect(db):
    data = _f150_ready_master_data()
    series = _make_series(next_number=10)
    service = RemittanceService("admin")
    issued = service.issue(_make_draft(data, series))

    with pytest.raises(RemittanceAlreadyIssued) as error:
        service.issue(Remittance.get_by_id(issued.id))

    assert "ya fue emitido por otro puesto" in str(error.value)
    assert RemittanceSeries.get_by_id(series.id).next_number == 11
    assert (
        AuditLog.select()
        .where(
            (AuditLog.record_ref == f"Remittance:{issued.id}")
            & (AuditLog.action == "emitir")
        )
        .count()
        == 1
    )


def test_ui_informs_already_issued_remittance(db, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.models.f150 import F150Batch
    from app.ui.remittances import RemittancesPage

    data = _f150_ready_master_data()
    series = _make_series(next_number=20)
    service = RemittanceService("admin")
    issued = service.issue(_make_draft(data, series))
    app = QApplication.instance() or QApplication([])
    page = RemittancesPage(
        current_user="admin", output_dir=tmp_path, f150_output_dir=tmp_path
    )
    monkeypatch.setattr(page, "_selected", lambda: Remittance.get_by_id(issued.id))
    infos: list[tuple] = []
    warnings: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, text: infos.append((title, text)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )

    page._issue()
    app.processEvents()

    assert warnings == []
    assert len(infos) == 1
    assert infos[0][0] == "Remito ya emitido"
    assert "ya fue emitido por otro puesto" in infos[0][1]
    assert RemittanceSeries.get_by_id(series.id).next_number == 21
    assert F150Batch.select().count() == 0
    assert list(tmp_path.iterdir()) == []


def test_mysql_two_connections_issue_same_draft_only_once(
    mysql_models, monkeypatch
):
    data = _f150_ready_master_data()
    series = _make_series(next_number=100)
    draft = _make_draft(data, series)
    _slow_freeze(monkeypatch)

    results = _run_two_workers((draft.id, draft.id))

    successes = [row for row in results if row["ok"]]
    failures = [row for row in results if not row["ok"]]
    assert len(successes) == 1, results
    assert len(failures) == 1, results
    assert failures[0]["type"] == "RemittanceAlreadyIssued", failures[0]
    assert "ya fue emitido por otro puesto" in failures[0]["message"]
    assert len({row["connection"] for row in results}) == 2

    current = Remittance.get_by_id(draft.id)
    assert current.status == Remittance.STATUS_ISSUED
    assert current.physical_number == "00000100"
    assert RemittanceSeries.get_by_id(series.id).next_number == 101
    assert (
        AuditLog.select()
        .where(
            (AuditLog.record_ref == f"Remittance:{draft.id}")
            & (AuditLog.action == "emitir")
        )
        .count()
        == 1
    )


def test_mysql_two_connections_issue_different_drafts_same_series(mysql_models):
    data = _f150_ready_master_data()
    series = _make_series(next_number=200)
    first = _make_draft(data, series)
    second = _make_draft(data, series)

    results = _run_two_workers((first.id, second.id))

    assert all(row["ok"] for row in results), results
    assert sorted(row["physical_number"] for row in results) == [
        "00000200",
        "00000201",
    ]
    assert len({row["connection"] for row in results}) == 2
    assert RemittanceSeries.get_by_id(series.id).next_number == 202
    for remittance_id in (first.id, second.id):
        assert Remittance.get_by_id(remittance_id).status == Remittance.STATUS_ISSUED
        assert (
            AuditLog.select()
            .where(
                (AuditLog.record_ref == f"Remittance:{remittance_id}")
                & (AuditLog.action == "emitir")
            )
            .count()
            == 1
        )


def test_mysql_lock_releases_after_validation_rejection(
    mysql_models, monkeypatch
):
    data = _f150_ready_master_data()
    data["carrier"].address = None
    data["carrier"].save()
    series = _make_series(next_number=300)
    draft = _make_draft(data, series)
    _slow_freeze(monkeypatch)

    results = _run_two_workers((draft.id, draft.id))

    assert all(not row["ok"] for row in results), results
    assert {row["type"] for row in results} == {"RemittanceIssueBlocked"}
    assert Remittance.get_by_id(draft.id).status == Remittance.STATUS_DRAFT
    assert RemittanceSeries.get_by_id(series.id).next_number == 300
    assert (
        AuditLog.select()
        .where(
            (AuditLog.record_ref == f"Remittance:{draft.id}")
            & (AuditLog.action == "emitir")
        )
        .count()
        == 0
    )
