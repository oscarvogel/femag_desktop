"""#981: el preflight F150 rechaza campos obligatorios invalidos o ficticios.

La regla se aplica al emitir (``require_issued=False``). El borrador se sigue
creando, guardando y editando con las validaciones normales de borrador. Los
remitos ya emitidos conservan su validacion historica: no se reescriben ni se
les agregan restricciones nuevas al generar su F150.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from app.models.audit import AuditLog
from app.models.remittances import Remittance, RemittanceSeries
from app.models.system import AppParameter
from app.services.f150_batch_service import F150BatchService
from app.services.remittance_service import (
    RemittanceIssueBlocked,
    RemittanceSeriesService,
    RemittanceService,
)
from tests.conftest import _f150_ready_master_data


def _series(next_number: int = 500) -> RemittanceSeries:
    return RemittanceSeriesService("admin").save(
        name=f"Talonario 981 {next_number}",
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


def _blocked_issues(draft, series, *expected: str) -> list[str]:
    initial_number = RemittanceSeries.get_by_id(series.id).next_number
    with pytest.raises(RemittanceIssueBlocked) as error:
        RemittanceService("admin").issue(draft)
    issues = error.value.issues
    for text in expected:
        assert any(text in issue for issue in issues), issues
    current = Remittance.get_by_id(draft.id)
    assert current.status == Remittance.STATUS_DRAFT
    assert RemittanceSeries.get_by_id(series.id).next_number == initial_number
    assert (
        AuditLog.select()
        .where(
            (AuditLog.record_ref == f"Remittance:{draft.id}")
            & (AuditLog.action == "emitir")
        )
        .count()
        == 0
    )
    return issues


def test_whitespace_client_cuit_blocks(db):
    data = _f150_ready_master_data()
    data["client"].cuit = " \t\n "
    data["client"].save()
    series = _series()

    issues = _blocked_issues(_draft(data, series), series, "falta CUIT del cliente")

    assert not any("inválido" in issue for issue in issues)


def test_letter_client_cuit_blocks(db):
    data = _f150_ready_master_data()
    data["client"].cuit = "20-ABC-12345678-9"
    data["client"].save()
    series = _series()

    _blocked_issues(
        _draft(data, series),
        series,
        "CUIT del cliente inválido (se esperan 11 dígitos)",
    )


def test_whitespace_carrier_cuit_blocks(db):
    data = _f150_ready_master_data()
    data["carrier"].cuit = "\t \n"
    data["carrier"].save()
    series = _series()

    _blocked_issues(
        _draft(data, series), series, "falta transportista con CUIT"
    )


def test_invalid_carrier_cuit_blocks(db):
    data = _f150_ready_master_data()
    data["carrier"].cuit = "ABC"
    data["carrier"].save()
    series = _series()

    _blocked_issues(
        _draft(data, series),
        series,
        "CUIT del transportista inválido (se esperan 11 dígitos)",
    )


@pytest.mark.parametrize("domain", [" \t\n", "Sin especificar", "---"])
def test_missing_or_fictitious_truck_domain_blocks(db, domain):
    data = _f150_ready_master_data()
    data["truck"].domain = domain
    data["truck"].save()
    series = _series()

    _blocked_issues(_draft(data, series), series, "falta camion")


def test_whitespace_carrier_codes_block(db):
    data = _f150_ready_master_data()
    data["carrier"].tipo = " \t"
    data["carrier"].codigo = "Sin especificar"
    data["carrier"].save()
    series = _series()

    _blocked_issues(
        _draft(data, series),
        series,
        "transportista: falta tipo",
        "transportista: falta código",
    )


def test_placeholder_carrier_and_driver_fiscal_address_block(db):
    data = _f150_ready_master_data()
    data["carrier"].fiscal_address = None
    data["carrier"].address = "Sin especificar"
    data["carrier"].save()
    data["driver"].fiscal_address = None
    data["driver"].address = " \t\n"
    data["driver"].save()
    series = _series()

    _blocked_issues(
        _draft(data, series),
        series,
        "transportista: falta domicilio fiscal",
        "chofer: falta domicilio fiscal",
    )


def test_whitespace_truck_types_block(db):
    data = _f150_ready_master_data()
    data["truck"].trailer_domain = "AC456EF"
    data["truck"].chassis_type = " \t"
    data["truck"].trailer_type = "Sin especificar"
    data["truck"].save()
    series = _series()

    _blocked_issues(
        _draft(data, series),
        series,
        "camión: falta tipo de chasis",
        "camión: falta tipo de acoplado",
    )


def test_whitespace_product_rubros_and_unit_block(db):
    data = _f150_ready_master_data()
    data["product"].rh1 = " \t"
    data["product"].rh2 = "Sin especificar"
    data["product"].unidad_dgr = "\n"
    data["product"].save()
    series = _series()

    _blocked_issues(
        _draft(data, series),
        series,
        "sin rubros DGR",
        "sin unidad DGR",
    )


def test_whitespace_names_block(db):
    data = _f150_ready_master_data()
    data["client"].name = " \t\n"
    data["client"].save()
    data["carrier"].name = "Sin especificar"
    data["carrier"].save()
    data["driver"].name = "\n"
    data["driver"].save()
    series = _series()

    _blocked_issues(
        _draft(data, series),
        series,
        "falta nombre del cliente",
        "transportista: falta nombre",
        "chofer: falta nombre",
    )


def test_whitespace_origin_parameter_blocks(db):
    data = _f150_ready_master_data()
    AppParameter.update(
        value=json.dumps({"locality_code": " \t\n "})
    ).where(AppParameter.key == "f150.origin").execute()
    series = _series()

    _blocked_issues(
        _draft(data, series),
        series,
        "falta origen DGR (parámetro f150.origin)",
    )


def test_valid_legacy_values_still_emit(db):
    data = _f150_ready_master_data()
    data["client"].cuit = "30-71234567-8"
    data["client"].save()
    data["carrier"].cuit = "30 777 777 770"
    data["carrier"].save()
    data["truck"].domain = "AB 123 CD"
    data["truck"].save()
    data["product"].rh4 = "0"
    data["product"].save()
    series = _series()

    issued = RemittanceService("admin").issue(_draft(data, series))

    assert issued.status == Remittance.STATUS_ISSUED
    assert RemittanceSeries.get_by_id(series.id).next_number == 501
    assert F150BatchService.validation_issues(issued) == []


def test_draft_with_invalid_fields_saves_and_edits(db):
    data = _f150_ready_master_data()
    data["client"].cuit = " \t"
    data["client"].save()
    data["carrier"].codigo = "Sin especificar"
    data["carrier"].save()
    data["product"].rh1 = " \t"
    data["product"].save()
    series = _series()

    service = RemittanceService("admin")
    draft = _draft(data, series)
    reopened = Remittance.get_by_id(draft.id)
    updated = service.update_draft(reopened, observations="Sigue en borrador")

    assert updated.observations == "Sigue en borrador"
    assert updated.client_cuit == " \t"
    assert updated.carrier.codigo == "Sin especificar"
    _blocked_issues(updated, series, "falta CUIT del cliente")


def test_all_missing_reported_together(db):
    data = _f150_ready_master_data()
    data["client"].cuit = " \t"
    data["client"].save()
    data["carrier"].cuit = "Sin especificar"
    data["carrier"].codigo = " \t"
    data["carrier"].save()
    data["truck"].domain = " \t"
    data["truck"].chassis_type = "Sin especificar"
    data["truck"].save()
    data["product"].rh2 = " \t"
    data["product"].unidad_dgr = "Sin especificar"
    data["product"].save()
    series = _series()

    issues = _blocked_issues(
        _draft(data, series),
        series,
        "falta CUIT del cliente",
        "falta transportista con CUIT",
        "falta camion",
        "transportista: falta código",
        "camión: falta tipo de chasis",
        "sin rubros DGR",
        "sin unidad DGR",
    )

    assert len(issues) >= 7


def test_ui_reports_whitespace_fields(db, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.ui.remittances import RemittancesPage

    data = _f150_ready_master_data()
    data["client"].cuit = " \t"
    data["client"].save()
    data["carrier"].codigo = "Sin especificar"
    data["carrier"].save()
    series = _series()
    draft = _draft(data, series)

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
    assert warnings[0][0] == "No se puede emitir el remito"
    assert "falta CUIT del cliente" in warnings[0][1]
    assert "transportista: falta código" in warnings[0][1]
    assert Remittance.get_by_id(draft.id).status == Remittance.STATUS_DRAFT
