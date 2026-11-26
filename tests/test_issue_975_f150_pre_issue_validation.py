"""#975: la emision se bloquea si falta un dato obligatorio del F150.

La regla separa guardar de emitir:

- un borrador con datos F150 incompletos se crea, guarda, reabre y edita;
- Emitir valida los datos efectivos (maestros actuales, snapshots y precios)
  antes de consumir el talonario;
- un rechazo conserva el borrador, sus datos y la numeracion, y no deja lote,
  archivo, precio congelado ni auditoria de emision;
- corregidos los maestros, el mismo borrador se emite;
- cancelar el guardado o fallar la escritura despues de emitir conserva el
  comportamiento #931: remito emitido y F150 pendiente recuperable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.audit import AuditLog
from app.models.f150 import F150Batch
from app.models.remittances import Remittance, RemittanceItem, RemittanceSeries
from app.services.f150_batch_service import F150BatchService
from app.services.load_order_service import LoadOrderService
from app.services.pricing import price_for_client_list
from app.services.remittance_service import (
    RemittanceIssueBlocked,
    RemittanceSeriesService,
    RemittanceService,
)
from tests.conftest import _f150_ready_master_data


def _draft(service, data, *, number="00000975", point="0001", **changes):
    items = changes.pop(
        "items",
        [{"product": data["product"], "quantity": Decimal("10")}],
    )
    return service.create_manual(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        truck=data["truck"],
        driver=data["driver"],
        physical_point_of_sale=point,
        physical_number=number,
        remittance_date=date(2026, 11, 26),
        items=items,
        **changes,
    )


def test_draft_with_missing_f150_data_saves_reopens_and_edits(db):
    data = _f150_ready_master_data()
    service = RemittanceService("admin")
    draft = _draft(service, data)

    # El maestro se completa despues: guardar no exige los datos del F150.
    data["carrier"].address = None
    data["carrier"].save()
    data["driver"].locality = None
    data["driver"].save()

    reopened = Remittance.get_by_id(draft.id)
    assert reopened.status == Remittance.STATUS_DRAFT
    assert reopened.carrier_id == data["carrier"].id
    assert reopened.driver_id == data["driver"].id

    updated = service.update_draft(reopened, observations="Sigue en borrador")
    assert updated.observations == "Sigue en borrador"
    assert updated.carrier.address is None
    assert updated.driver.locality is None
    assert len(list(updated.items)) == 1


def test_direct_service_issue_blocks_and_reports_all_missing(db):
    data = _f150_ready_master_data()
    service = RemittanceService("admin")
    draft = _draft(service, data)

    data["carrier"].codigo = None
    data["carrier"].address = None
    data["carrier"].save()
    data["driver"].locality = None
    data["driver"].save()
    data["product"].rh1 = None
    data["product"].unidad_dgr = None
    data["product"].save()

    with pytest.raises(RemittanceIssueBlocked) as error:
        service.issue(draft)

    issues = error.value.issues
    assert "transportista: falta código" in issues
    assert any(issue.startswith("transportista: falta domicilio") for issue in issues)
    assert any(issue.startswith("chofer: falta localidad DGR") for issue in issues)
    assert any("sin rubros DGR" in issue for issue in issues)
    assert any("sin unidad DGR" in issue for issue in issues)
    assert len(issues) >= 5
    message = str(error.value)
    for issue in issues:
        assert issue in message
    assert "No se ha consumido ningún número del talonario" in message


def test_blocked_issue_leaves_number_data_and_effects_intact(db):
    data = _f150_ready_master_data()
    series = RemittanceSeriesService("admin").save(
        name="Talonario 975",
        point_of_sale="0001",
        next_number=5,
        is_default=True,
    )
    service = RemittanceService("admin")
    draft = _draft(service, data, number=None, point=None, series=series)
    item_id = draft.items[0].id
    # Simula un borrador legacy sin precio congelado: la emision lo resolveria
    # y el rollback tiene que devolverlo a NULL.
    RemittanceItem.update(unit_price=None).where(RemittanceItem.id == item_id).execute()

    old_client_name = draft.client_name
    old_carrier_name = draft.carrier_name
    data["client"].name = "Cliente corregido"
    data["client"].save()
    data["carrier"].address = None
    data["carrier"].save()

    with pytest.raises(RemittanceIssueBlocked):
        service.issue(draft)

    current = Remittance.get_by_id(draft.id)
    assert current.status == Remittance.STATUS_DRAFT
    assert current.physical_point_of_sale is None
    assert current.physical_number is None
    assert current.series_id == series.id
    assert current.issued_by is None
    # El refresh de snapshots tambien se revierte.
    assert current.client_name == old_client_name
    assert current.carrier_name == old_carrier_name
    assert RemittanceItem.get_by_id(item_id).unit_price is None
    refreshed_series = RemittanceSeries.get_by_id(series.id)
    assert refreshed_series.next_number == 5
    assert (
        AuditLog.select()
        .where(
            (AuditLog.record_ref == f"Remittance:{draft.id}")
            & (AuditLog.action == "emitir")
        )
        .count()
        == 0
    )
    assert F150Batch.select().count() == 0


def test_ui_blocks_and_shows_all_missing_with_guidance(db, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.ui.remittances import RemittancesPage

    data = _f150_ready_master_data()
    service = RemittanceService("admin")
    draft = _draft(service, data, number="00000976")
    data["carrier"].address = None
    data["carrier"].save()
    data["driver"].locality = None
    data["driver"].save()

    app = QApplication.instance() or QApplication([])
    page = RemittancesPage(
        current_user="admin", output_dir=tmp_path, f150_output_dir=tmp_path
    )
    monkeypatch.setattr(page, "_selected", lambda: Remittance.get_by_id(draft.id))
    warnings = []
    infos = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *_args, **_kwargs: infos.append(True)
    )

    page._issue()
    app.processEvents()

    assert infos == []
    assert len(warnings) == 1
    title, text = warnings[0]
    assert title == "No se puede emitir el remito"
    assert "transportista: falta domicilio" in text
    assert "chofer: falta localidad DGR" in text
    assert "Dónde corregir" in text
    assert "No se ha consumido ningún número del talonario" in text
    assert Remittance.get_by_id(draft.id).status == Remittance.STATUS_DRAFT


def test_corrected_masters_allow_retry_and_refresh_snapshots(db):
    data = _f150_ready_master_data()
    client = data["client"]
    carrier = data["carrier"]
    driver = data["driver"]
    carrier_cuit = carrier.cuit
    client.cuit = ""
    client.save()
    carrier.cuit = None
    carrier.codigo = None
    carrier.save()
    driver.locality = None
    driver.save()

    service = RemittanceService("admin")
    draft = _draft(service, data, number="00000977")
    assert draft.client_cuit == ""
    assert draft.carrier_cuit is None

    with pytest.raises(RemittanceIssueBlocked) as error:
        service.issue(draft)
    assert "falta CUIT del cliente" in error.value.issues
    assert "falta transportista con CUIT" in error.value.issues
    assert "transportista: falta código" in error.value.issues
    assert any(
        issue.startswith("chofer: falta localidad DGR")
        for issue in error.value.issues
    )

    client.cuit = "30712345678"
    client.save()
    carrier.cuit = carrier_cuit
    carrier.codigo = "0001"
    carrier.save()
    driver.locality = data["address"].locality
    driver.save()

    issued = service.issue(draft)
    assert issued.status == Remittance.STATUS_ISSUED
    # El snapshot se refresca desde el maestro corregido, no queda el viejo.
    assert issued.client_cuit == "30712345678"
    assert issued.carrier_cuit == carrier_cuit
    assert F150BatchService.validation_issues(issued) == []
    assert issued.items[0].unit_price == price_for_client_list(data["product"], client)


def test_issue_refreshes_address_truck_and_driver_snapshots(db):
    data = _f150_ready_master_data()
    service = RemittanceService("admin")
    draft = _draft(service, data, number="00000986")

    address = data["address"]
    address.address = "Ruta 12 km 1540"
    address.save()
    truck = data["truck"]
    truck.domain = "NUEVA456"
    truck.save()
    driver = data["driver"]
    driver.document = "22222222"
    driver.save()

    issued = service.issue(draft)
    assert issued.delivery_address_text == "Ruta 12 km 1540"
    assert issued.truck_domain == "NUEVA456"
    assert issued.driver_document == "22222222"
    assert F150BatchService.validation_issues(issued) == []


def test_explicit_price_is_kept_at_issue(db):
    data = _f150_ready_master_data()
    service = RemittanceService("admin")
    draft = _draft(
        service,
        data,
        number="00000978",
        items=[
            {
                "product": data["product"],
                "quantity": Decimal("1"),
                "unit_price": Decimal("250"),
            }
        ],
    )
    issued = service.issue(draft)
    assert issued.items[0].unit_price == Decimal("250.0000")


def test_zero_price_blocks_emission(db):
    data = _f150_ready_master_data()
    data["product"].precio_neto_base = 0
    data["product"].save()
    service = RemittanceService("admin")
    draft = _draft(service, data, number="00000979")

    with pytest.raises(RemittanceIssueBlocked) as error:
        service.issue(draft)
    assert any(
        "sin precio de operacion" in issue for issue in error.value.issues
    )


def test_malformed_driver_document_blocks_emission(db):
    data = _f150_ready_master_data()
    driver = data["driver"]
    driver.cuit = "ABC"
    driver.document = ""
    driver.save()
    service = RemittanceService("admin")
    draft = _draft(service, data, number="00000980")

    with pytest.raises(RemittanceIssueBlocked) as error:
        service.issue(draft)
    assert "falta CUIT o documento del chofer" in error.value.issues


def test_order_based_remittance_blocks_then_emits_after_correction(db):
    from app.models.load_orders import LoadOrderDestination

    data = _f150_ready_master_data()
    order = LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [{"product": data["product"], "quantity": 10}],
            }
        ],
        pallets=[],
    )
    destination = order.destinations.order_by(LoadOrderDestination.sequence).first()
    service = RemittanceService("admin")
    draft = service.create_from_order(
        order=order,
        destination=destination,
        physical_point_of_sale="0001",
        physical_number="00000981",
    )
    assert draft.source_order_id == order.id

    data["carrier"].address = None
    data["carrier"].save()
    with pytest.raises(RemittanceIssueBlocked):
        service.issue(draft)

    data["carrier"].address = "Ruta 12"
    data["carrier"].save()
    issued = service.issue(draft)
    assert issued.status == Remittance.STATUS_ISSUED
    assert F150BatchService.validation_issues(issued) == []


def test_preflight_for_draft_does_not_require_post_issue_state(db):
    data = _f150_ready_master_data()
    service = RemittanceService("admin")
    draft = _draft(service, data, number=None, point=None)

    issues = F150BatchService.validation_issues(draft, require_issued=False)

    assert "debe estar emitido" not in issues
    assert "falta numeracion fisica" not in issues
    assert issues == []
    # La validacion final del F150 sigue exigiendo el estado emitido.
    assert "debe estar emitido" in F150BatchService.validation_issues(draft)


def test_historical_issued_without_frozen_price_still_blocks_generation(db):
    data = _f150_ready_master_data()
    service = RemittanceService("admin")
    issued = service.issue(_draft(service, data, number="00000987"))
    RemittanceItem.update(unit_price=None).where(
        RemittanceItem.remittance == issued
    ).execute()

    issues = F150BatchService.validation_issues(Remittance.get_by_id(issued.id))

    assert any("sin precio de operacion" in issue for issue in issues)


def test_issued_remittance_stays_non_editable(db):
    data = _f150_ready_master_data()
    service = RemittanceService("admin")
    issued = service.issue(_draft(service, data, number="00000982"))

    with pytest.raises(ValueError, match="borrador"):
        service.update_draft(issued, observations="no deberia poder")


def test_generated_f150_keeps_golden_layout_contract(db, tmp_path):
    data = _f150_ready_master_data()
    service = RemittanceService("admin")
    issued = service.issue(_draft(service, data, number="00000983"))

    output = tmp_path / "f150-975.txt"
    F150BatchService("admin").generate([issued], output)

    raw = output.read_bytes()
    assert not raw.endswith(b"\r\n")
    text = raw.decode("cp1252")
    records = text.split("\r\n")
    assert len(records) == 2
    header, detail = records
    assert header.startswith("C1F150")
    assert detail.startswith("D1F150")
    assert header.count("@") == 49  # prefijo + 49 campos
    assert detail.endswith("@")
    header_fields = header.split("@")
    detail_fields = detail.split("@")
    assert header_fields[3] == "0001"
    assert detail_fields[4] == "0001"
    assert detail_fields[5] == "00000983"
    assert "@30-71234567-8@" in text
    assert detail_fields[11] == "kg"


def test_cancelled_save_after_issue_keeps_emitted_and_pending(db, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

    from app.ui.remittances import RemittancesPage

    data = _f150_ready_master_data()
    service = RemittanceService("admin")
    remittance = service.issue(_draft(service, data, number="00000984"))
    app = QApplication.instance() or QApplication([])
    page = RemittancesPage(
        current_user="admin", output_dir=tmp_path, f150_output_dir=tmp_path
    )
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: ("", ""))
    infos = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _p, title, text: infos.append((title, text))
    )

    page._generate_f150_after_emit(remittance)
    app.processEvents()

    assert not list(tmp_path.iterdir())
    assert F150Batch.select().count() == 0
    assert F150BatchService.is_included(remittance) is False
    assert Remittance.get_by_id(remittance.id).status == Remittance.STATUS_ISSUED
    assert "pendiente" in infos[-1][1].lower()


def test_write_failure_after_issue_keeps_emitted_and_pending(
    db, tmp_path, monkeypatch
):
    from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

    from app.ui.remittances import RemittancesPage

    data = _f150_ready_master_data()
    service = RemittanceService("admin")
    remittance = service.issue(_draft(service, data, number="00000985"))
    app = QApplication.instance() or QApplication([])
    page = RemittancesPage(
        current_user="admin", output_dir=tmp_path, f150_output_dir=tmp_path
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_a, **_k: (str(tmp_path / "no-se-escribe.txt"), ""),
    )

    def _boom(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(F150BatchService, "generate", _boom)
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )

    page._generate_f150_after_emit(remittance)
    app.processEvents()

    assert len(warnings) == 1
    assert warnings[0][0] == "F150 pendiente"
    assert "quedo emitido" in warnings[0][1]
    assert F150BatchService.is_included(remittance) is False
    assert Remittance.get_by_id(remittance.id).status == Remittance.STATUS_ISSUED
