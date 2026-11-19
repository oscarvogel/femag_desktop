"""Reproducciones de #792; xfail identifica defectos confirmados sin reparar."""

import pytest
from PyQt5.QtWidgets import QApplication, QDialog

from app.models.dgr import DgrLocality
from app.models.f150 import F150Batch
from app.models.masters import ClientAddress
from app.models.remittances import Remittance
from app.services.client_service import ClientService
from app.services.f150_batch_service import F150BatchService
from app.ui.master_abm import ClientAddressEntryDialog
from tests.test_issue_790_f150_dgr import _dgr, _remittance


@pytest.fixture
def scenario(db):
    cordoba = _dgr(db)
    posadas = DgrLocality.create(
        code="2000", name="POSADAS", dgr_id=2000, dgr_code=44,
        department_code=1, province_code=14, country=cordoba.country,
    )
    return _remittance(), cordoba, posadas


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def _edit(row, *, locality=None, city=None, province=None, street=None):
    return ClientService("audit792").update_address(
        row, client=row.client, address_type=row.address_type,
        province=province or row.province, city=city or row.city,
        address=street or row.address, active=True,
        locality=locality or row.locality,
    )


def _destination_fields(path):
    # Cabecera C del layout DGR: domicilio, localidad, nombre y provincia.
    fields = path.read_bytes().decode("cp1252").splitlines()[0].split("@")
    return fields[-9], fields[-5], fields[-4], fields[-3]


def test_domicilio_correcto_genera_txt_sin_reabrir_cliente(scenario, tmp_path):
    remittance, _, _ = scenario
    output = tmp_path / "correcto.txt"
    F150BatchService("audit792").generate([remittance], output)
    assert _destination_fields(output) == (
        "ESPINOSA NEGRETE 701", "0035", "CORDOBA", "04",
    )
    assert F150Batch.select().count() == 1


def test_aceptar_domicilio_correcto_conserva_datos_y_permite_generar(
    scenario, qt_app, tmp_path,
):
    remittance, cordoba, _ = scenario
    dialog = ClientAddressEntryDialog(
        current_user="audit792", record_id=remittance.delivery_address_id,
    )
    dialog._save()
    assert dialog.result() == QDialog.Accepted
    saved = ClientAddress.get_by_id(remittance.delivery_address_id)
    assert (saved.address, saved.city, saved.province, saved.locality_id) == (
        "ESPINOSA NEGRETE 701", "CORDOBA", "CORDOBA", cordoba.id,
    )
    output = tmp_path / "aceptado.txt"
    F150BatchService("audit792").generate([remittance], output)
    assert _destination_fields(output) == (
        "ESPINOSA NEGRETE 701", "0035", "CORDOBA", "04",
    )
    dialog.close()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="#792: asigna primera localidad sin elegirla")
def test_aceptar_sin_localidad_no_inventa_codigo(scenario, qt_app):
    remittance, _, _ = scenario
    address = remittance.delivery_address
    address.locality = None
    address.save()
    dialog = ClientAddressEntryDialog(current_user="audit792", record_id=address.id)
    dialog._save()
    assert ClientAddress.get_by_id(address.id).locality_id is None


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="#792: cambio explicito de localidad conserva textos viejos")
def test_elegir_otra_localidad_actualiza_ciudad_y_provincia(scenario, qt_app):
    remittance, _, posadas = scenario
    dialog = ClientAddressEntryDialog(
        current_user="audit792", record_id=remittance.delivery_address_id,
    )
    dialog.locality_combo.setCurrentIndex(dialog.locality_combo.findData(posadas.id))
    dialog._save()
    saved = ClientAddress.get_by_id(remittance.delivery_address_id)
    assert (saved.city, saved.province, saved.locality_id) == (
        "POSADAS", "MISIONES", posadas.id,
    )


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="#792: texto libre reutiliza el ID anterior del combo")
def test_texto_sin_seleccionar_no_guarda_localidad_anterior(scenario, qt_app):
    remittance, _, _ = scenario
    dialog = ClientAddressEntryDialog(
        current_user="audit792", record_id=remittance.delivery_address_id,
    )
    dialog.locality_combo.setEditText("LOCALIDAD INEXISTENTE")
    dialog._save()
    assert dialog.result() != QDialog.Accepted
    assert dialog.saved_record is None


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="#792: editar promueve domicilio a principal")
def test_editar_sin_cambios_no_reasigna_principal(scenario):
    remittance, cordoba, _ = scenario
    other = ClientService("audit792").add_address(
        remittance.client, "entrega", "CORDOBA", "CORDOBA", "OTRO DEPOSITO",
        is_primary=True, locality=cordoba,
    )
    address = ClientAddress.get_by_id(remittance.delivery_address_id)
    _edit(address)
    assert ClientAddress.get_by_id(other.id).is_primary is True
    assert ClientAddress.get_by_id(address.id).is_primary is False


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="#792: TXT mezcla snapshot viejo y codigos actuales")
def test_generar_despues_de_editar_no_mezcla_domicilios(scenario, tmp_path):
    remittance, _, posadas = scenario
    _edit(
        remittance.delivery_address, locality=posadas, city="POSADAS",
        province="MISIONES", street="CALLE NUEVA 123",
    )
    fresh = Remittance.get_by_id(remittance.id)
    output = tmp_path / "despues_de_editar.txt"
    F150BatchService("audit792").generate([fresh], output)
    # Esta prueba no decide fiscal/entrega ni actual/historico. Exige coherencia
    # y generacion con datos completos: ninguna version admite un hibrido.
    assert _destination_fields(output) in {
        ("ESPINOSA NEGRETE 701", "0035", "CORDOBA", "04"),
        ("CALLE NUEVA 123", "0044", "POSADAS", "14"),
    }


def test_editar_domicilio_no_altera_txt_historico(scenario, tmp_path):
    remittance, _, posadas = scenario
    service = F150BatchService("audit792", archive_dir=tmp_path / "archive")
    original = tmp_path / "original.txt"
    batch = service.generate([remittance], original)
    expected = original.read_bytes()
    _edit(
        remittance.delivery_address, locality=posadas, city="POSADAS",
        province="MISIONES", street="CALLE NUEVA 123",
    )
    original.unlink()
    recovered = service.recover_txt(batch, tmp_path / "recuperado.txt")
    assert recovered.read_bytes() == expected
    assert F150Batch.select().count() == 1
    assert Remittance.get_by_id(remittance.id).delivery_address_text == "ESPINOSA NEGRETE 701"
