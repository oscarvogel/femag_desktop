"""#790: destino DGR, correccion desde F150 y recuperacion de TXT historicos."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.importers.legacy_dbf import LegacyDbfMasterImporter
from app.models.audit import AuditLog
from app.models.dgr import DgrCountry, DgrLocality, DgrProvince
from app.models.f150 import F150Batch, F150BatchRemittance
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.remittances import Remittance
from app.models.security import User, UserProfile
from app.models.system import AppParameter
from app.services.f150_batch_service import F150BatchService
from app.services.f150_dgr_service import (
    F150DgrCorrectionService,
    ProductDgrUpdate,
)
from app.services.f150_encoder import F150Encoder, F150ValidationError
from app.services.remittance_service import RemittanceService


COUNTRY = None
CORDOBA = None


def _dgr(db):
    global COUNTRY, CORDOBA
    COUNTRY = DgrCountry.create(legacy_id=59, name="ARGENTINA", abbr="ARG")
    DgrProvince.create(code=4, name="CORDOBA")
    DgrProvince.create(code=14, name="MISIONES")
    CORDOBA = DgrLocality.create(
        code="1030",
        name="CORDOBA",
        dgr_id=1030,
        dgr_code=35,
        department_code=0,
        province_code=4,
        country=COUNTRY,
    )
    return CORDOBA


def _admin(username="admin790"):
    profile = UserProfile.get_or_create(name="Administrador")[0]
    return User.get_or_create(
        username=username,
        defaults={"password_hash": "x", "profile": profile, "active": True},
    )[0]


def _non_admin(username="secretaria790"):
    profile = UserProfile.get_or_create(name="Secretaría")[0]
    return User.get_or_create(
        username=username,
        defaults={"password_hash": "x", "profile": profile, "active": True},
    )[0]


def _transport_and_product(*, product_codes=True, product_name="BOLSAS ALM. DE MAIZ X 10 KG."):
    carrier = Carrier.create(
        name="MENDIETA GABRIEL",
        cuit="20248343843",
        codigo="0010",
        tipo="DIR",
        locality=CORDOBA,
        address="LOTE 105 OTTO BAHR",
    )
    truck = Truck.create(
        domain="IVW157",
        trailer_domain="AF923VQ",
        carrier=carrier,
        chassis_type="1",
        trailer_type="1",
    )
    driver = Driver.create(
        name="BUSTAMANTE FABIAN ROMUALDO",
        carrier=carrier,
        usual_truck=truck,
        cuit="23266557779",
        document="26655777",
        locality=CORDOBA,
        address="SAN FRANCISCO 907",
    )
    product = Product.create(
        codigo="2003",
        name=product_name,
        unit="UNIDADES",
        precio_neto_base=11780.0,
        precio_lista_1=11780.0,
        rh1="2" if product_codes else None,
        rh2="2" if product_codes else None,
        rh3="19" if product_codes else None,
        rh4="0" if product_codes else None,
        unidad_dgr="U" if product_codes else None,
    )
    return carrier, truck, driver, product


def _address(client, *, city="CORDOBA", province="CORDOBA", address="ESPINOSA NEGRETE 701", locality=None):
    return ClientAddress.create(
        client=client,
        address_type="entrega",
        province=province,
        city=city,
        address=address,
        locality=locality if locality is not None else CORDOBA,
        is_primary=True,
    )


def _remittance(
    *,
    city="CORDOBA",
    province="CORDOBA",
    address="ESPINOSA NEGRETE 701",
    locality=None,
    product_codes=True,
    issued=True,
    number="10942",
):
    AppParameter.get_or_create(
        key="f150.origin", defaults={"value": json.dumps({"locality_code": "0015"})}
    )
    client = Client.create(name="ASTICOMAR S.A.", cuit="30718034384", iva_condition="RI")
    delivery = _address(
        client, city=city, province=province, address=address, locality=locality
    )
    carrier, truck, driver, product = _transport_and_product(product_codes=product_codes)
    service = RemittanceService("admin")
    remittance = service.create_manual(
        client=client,
        delivery_address=delivery,
        carrier=carrier,
        truck=truck,
        driver=driver,
        physical_point_of_sale="0001",
        physical_number=number,
        remittance_date=date(2026, 10, 26),
        items=[{"product": product, "quantity": Decimal("10")}],
    )
    if issued:
        remittance.status = Remittance.STATUS_ISSUED
        remittance.issued_by = "gabriela"
        remittance.save()
    return remittance


def _asticomar_row(**overrides):
    row = {
        "CODIGO": "0830",
        "NOMBRE": "ASTICOMAR S.A.",
        "CUIT": "30-71803438-4",
        "DOMICILIO": "ESPINOSA NEGRETE 701",
        "CODPOS": "5000",
        "LOCALIDAD": "1030",
        "C_DOMI": "TOMAS DE IROBI 83",
        "C_CODPOS": "5000",
        "C_LOCAL": "1030",
        "IMPOSITIVO": "",
    }
    row.update(overrides)
    return row


def test_asticomar_import_separa_fiscal_y_entrega_y_completa_ciudad_provincia(db):
    _dgr(db)
    importer = LegacyDbfMasterImporter()
    first = importer.import_rows({"clients": [_asticomar_row()]})
    second = importer.import_rows({"clients": [_asticomar_row()]})

    client = Client.get(Client.source_id == "0830")
    addresses = {
        row.address_type: row
        for row in ClientAddress.select().where(ClientAddress.client == client)
    }
    assert set(addresses) == {"fiscal", "entrega"}
    assert addresses["fiscal"].address == "ESPINOSA NEGRETE 701"
    assert addresses["entrega"].address == "TOMAS DE IROBI 83"
    assert addresses["fiscal"].city == "CORDOBA"
    assert addresses["fiscal"].province == "CORDOBA"
    assert addresses["entrega"].city == "CORDOBA"
    assert addresses["entrega"].province == "CORDOBA"
    assert addresses["fiscal"].locality.code == "1030"
    assert addresses["entrega"].locality.code == "1030"
    assert first["clients"]["direcciones_creadas"] == 2
    assert second["clients"]["direcciones_creadas"] == 0
    assert ClientAddress.select().where(ClientAddress.client == client).count() == 2


def test_import_completa_ciudad_provincia_de_la_direccion_existente_sin_cambiar_calle(db):
    _dgr(db)
    client = Client.create(name="ASTICOMAR S.A.", cuit="30718034384", iva_condition="RI")
    shared = ClientAddress.create(
        client=client,
        address_type="fiscal_entrega",
        province="Sin especificar",
        city="Sin especificar",
        address="ESPINOSA NEGRETE 701",
        locality=CORDOBA,
        is_primary=True,
    )

    LegacyDbfMasterImporter().import_rows({"clients": [_asticomar_row()]})

    shared = ClientAddress.get_by_id(shared.id)
    assert shared.address == "ESPINOSA NEGRETE 701"
    assert shared.city == "CORDOBA"
    assert shared.province == "CORDOBA"
    assert shared.locality.code == "1030"


def test_import_no_pisa_ciudad_provincia_editadas_por_el_operador(db):
    _dgr(db)
    client = Client.create(name="ASTICOMAR S.A.", cuit="30718034384", iva_condition="RI")
    shared = ClientAddress.create(
        client=client,
        address_type="fiscal_entrega",
        province="CORDOBA CAPITAL",
        city="CORDOBA CAPITAL",
        address="ESPINOSA NEGRETE 701",
        locality=CORDOBA,
        is_primary=True,
    )

    LegacyDbfMasterImporter().import_rows({"clients": [_asticomar_row()]})

    shared = ClientAddress.get_by_id(shared.id)
    assert shared.city == "CORDOBA CAPITAL"
    assert shared.province == "CORDOBA CAPITAL"


def test_emision_bloquea_ciudad_o_provincia_sin_especificar(db):
    _dgr(db)
    remittance = _remittance(city="Sin especificar", province="Sin especificar", issued=False)
    with pytest.raises(ValueError, match="ciudad de entrega|provincia de entrega"):
        RemittanceService("admin").issue(remittance)


def test_emision_bloquea_localidad_dgr_de_otra_provincia(db):
    _dgr(db)
    remittance = _remittance(city="CORDOBA", province="MISIONES", issued=False)
    with pytest.raises(ValueError, match="no coincide con la localidad DGR"):
        RemittanceService("admin").issue(remittance)


def test_emision_valida_refresca_snapshot_desde_el_maestro(db):
    _dgr(db)
    remittance = _remittance(issued=False)
    remittance.delivery_city = "Sin especificar"
    remittance.delivery_province = "Sin especificar"
    remittance.save()
    issued = RemittanceService("admin").issue(remittance)
    assert issued.delivery_city == "CORDOBA"
    assert issued.delivery_province == "CORDOBA"
    assert issued.delivery_address_text == "ESPINOSA NEGRETE 701"


def test_f150_10942_bloquea_hasta_corregir_el_snapshot(db, tmp_path):
    _dgr(db)
    remittance = _remittance(
        city="Sin especificar", province="Sin especificar", product_codes=False
    )
    issues = F150BatchService.validation_issues(remittance)
    assert any("ciudad de entrega" in issue for issue in issues)
    assert any("provincia de entrega" in issue for issue in issues)
    assert any("sin rubros DGR" in issue for issue in issues)

    _admin()
    service = F150DgrCorrectionService("admin790")
    result = service.correct(
        remittance,
        address="ESPINOSA NEGRETE 701",
        city="CORDOBA",
        province="CORDOBA",
        locality_id=CORDOBA.id,
        product_updates=[
            ProductDgrUpdate(
                product_id=Product.get().id,
                rh1="2",
                rh2="2",
                rh3="19",
                rh4="0",
                unidad_dgr="U",
            )
        ],
        update_snapshot=True,
    )
    assert result["remaining_issues"] == []
    assert result["snapshot_updated"] is True
    remittance = Remittance.get_by_id(remittance.id)
    assert remittance.delivery_city == "CORDOBA"
    assert remittance.delivery_province == "CORDOBA"
    assert remittance.delivery_address_text == "ESPINOSA NEGRETE 701"
    output = tmp_path / "10942.TXT"
    F150BatchService("admin").generate([remittance], output)
    assert output.exists()


def test_correccion_dgr_audita_antes_y_despues_y_no_toca_importes_ni_items(db):
    _dgr(db)
    remittance = _remittance(
        city="Sin especificar", province="Sin especificar", product_codes=False
    )
    product = Product.get()
    original_price = remittance.items[0].unit_price
    original_number = remittance.physical_number
    _admin()

    F150DgrCorrectionService("admin790").correct(
        remittance,
        address="ESPINOSA NEGRETE 701",
        city="CORDOBA",
        province="CORDOBA",
        locality_id=CORDOBA.id,
        product_updates=[
            ProductDgrUpdate(product.id, "2", "2", "19", "0", "U")
        ],
    )

    remittance = Remittance.get_by_id(remittance.id)
    assert remittance.physical_number == original_number
    assert remittance.items[0].unit_price == original_price
    audit = AuditLog.get(AuditLog.action == "corregir datos DGR")
    assert audit.old_value["address"]["city"] == "Sin especificar"
    assert audit.new_value["address"]["city"] == "CORDOBA"
    assert audit.old_value["products"][str(product.id)]["rh1"] is None
    assert audit.new_value["products"][str(product.id)]["rh1"] == "2"


def test_correccion_dgr_no_modifica_snapshot_de_un_remito_ya_incluido(db, tmp_path):
    _dgr(db)
    remittance = _remittance()
    batch = F150BatchService("admin").generate([remittance], tmp_path / "lote.TXT")
    original_text = remittance.delivery_address_text
    _admin()

    result = F150DgrCorrectionService("admin790").correct(
        remittance,
        address="OTRA CALLE 123",
        city="CORDOBA",
        province="CORDOBA",
        locality_id=CORDOBA.id,
        product_updates=[
            ProductDgrUpdate(Product.get().id, "2", "2", "19", "0", "U")
        ],
        update_snapshot=True,
    )

    remittance = Remittance.get_by_id(remittance.id)
    assert remittance.delivery_address_text == original_text
    assert remittance.delivery_address.address == "OTRA CALLE 123"
    assert result["snapshot_updated"] is False
    assert "ya pertenece a un lote F150" in result["snapshot_skipped_reason"]
    assert F150Batch.select().count() == 1
    assert F150Batch.get_by_id(batch.id).sha256 == batch.sha256


def test_correccion_dgr_requiere_permiso_administrativo(db):
    _dgr(db)
    remittance = _remittance()
    _non_admin()
    with pytest.raises(PermissionError, match="permiso administrativo"):
        F150DgrCorrectionService("secretaria790").require_permission()


def test_dialogo_de_domicilio_guarda_localidad_dgr_y_deriva_ciudad_provincia(db):
    from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton

    from app.ui.master_abm import ClientAddressEntryDialog

    _dgr(db)
    client = Client.create(name="Cliente Domicilio UI", cuit="30718034385", iva_condition="RI")
    app = QApplication.instance() or QApplication([])
    dialog = ClientAddressEntryDialog(current_user="admin", client_id=client.id)
    app.processEvents()
    dialog.findChild(QLineEdit, "addressStreetInput").setText("ESPINOSA NEGRETE 701")
    index = dialog.locality_combo.findData(CORDOBA.id)
    assert index >= 0
    dialog.locality_combo.setCurrentIndex(index)
    app.processEvents()
    assert dialog.findChild(QLineEdit, "addressCityInput").text() == "CORDOBA"
    assert dialog.findChild(QLineEdit, "addressProvinceInput").text() == "CORDOBA"
    dialog.findChild(QPushButton, "saveAddressButton").click()
    app.processEvents()

    assert dialog.saved_record is not None
    saved = ClientAddress.get_by_id(dialog.saved_record.id)
    assert saved.locality_id == CORDOBA.id
    assert saved.city == "CORDOBA"
    assert saved.province == "CORDOBA"


def test_pantalla_f150_expone_correccion_y_recuperacion(db, tmp_path):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.ui.f150 import F150Page

    _dgr(db)
    _admin()
    app = QApplication.instance() or QApplication([])
    page = F150Page(current_user="admin790", output_dir=tmp_path)
    app.processEvents()
    assert page.findChild(QPushButton, "correctF150DgrButton") is not None
    assert page.findChild(QPushButton, "recoverF150Button") is not None
    page.deleteLater()


def test_dialogo_f150_corrige_y_revalida(db):
    from PyQt5.QtWidgets import QApplication, QDialog

    from app.ui.f150 import F150DgrCorrectionDialog

    _dgr(db)
    remittance = _remittance(
        city="Sin especificar", province="Sin especificar", product_codes=False
    )
    _admin()
    app = QApplication.instance() or QApplication([])
    dialog = F150DgrCorrectionDialog(current_user="admin790", remittance=remittance)
    app.processEvents()

    index = dialog.locality_combo.findData(CORDOBA.id)
    assert index >= 0
    dialog.locality_combo.setCurrentIndex(index)
    dialog.address_input.setText("ESPINOSA NEGRETE 701")
    dialog.city_input.setText("CORDOBA")
    dialog.province_input.setText("CORDOBA")
    for column, value in enumerate(("2", "2", "19", "0", "U"), start=1):
        dialog.products_table.item(0, column).setText(value)
    dialog._save()
    app.processEvents()

    assert dialog.result() == QDialog.Accepted
    assert dialog.result_info is not None
    assert dialog.result_info["remaining_issues"] == []


def _recover_service(archive_dir: Path) -> F150BatchService:
    return F150BatchService("admin", archive_dir=archive_dir)


def test_recuperar_txt_dos_veces_entrega_bytes_identicos_sin_duplicar_lote(db, tmp_path):
    _dgr(db)
    remittance = _remittance()
    service = _recover_service(tmp_path / "archive")
    original = tmp_path / "original.TXT"
    batch = service.generate([remittance], original)
    expected = original.read_bytes()
    original.unlink()

    first = service.recover_txt(batch, tmp_path / "copia1.TXT")
    second = service.recover_txt(batch, tmp_path / "copia2.TXT")

    assert first.read_bytes() == expected
    assert second.read_bytes() == expected
    assert hashlib.sha256(first.read_bytes()).hexdigest() == batch.sha256
    assert F150Batch.select().count() == 1
    assert F150BatchRemittance.select().count() == 1
    refreshed = F150Batch.get_by_id(batch.id)
    assert refreshed.file_path == batch.file_path
    assert refreshed.sha256 == batch.sha256
    assert AuditLog.select().where(AuditLog.action == "recuperar_txt").count() == 2


def test_recuperar_txt_conserva_el_historico_aunque_cambien_los_datos(db, tmp_path):
    _dgr(db)
    remittance = _remittance()
    service = _recover_service(tmp_path / "archive")
    original = tmp_path / "original.TXT"
    batch = service.generate([remittance], original)
    expected = original.read_bytes()
    original.unlink()

    remittance.observations = "CAMBIO POSTERIOR"
    remittance.save()

    recovered = service.recover_txt(batch, tmp_path / "recuperado.TXT")
    assert recovered.read_bytes() == expected


def test_recuperar_txt_sin_archivo_ni_bytes_historicos_falla_explicito(db, tmp_path):
    _dgr(db)
    remittance = _remittance()
    generator = _recover_service(tmp_path / "archive_generado")
    original = tmp_path / "original.TXT"
    batch = generator.generate([remittance], original)
    original.unlink()
    remittance.observations = "CAMBIO POSTERIOR"
    remittance.save()

    historical = _recover_service(tmp_path / "archive_vacio")
    target = tmp_path / "no_debe_crearse.TXT"
    with pytest.raises(F150ValidationError, match="no coincide con el SHA-256"):
        historical.recover_txt(batch, target)
    assert not target.exists()
    assert F150Batch.select().count() == 1


def test_recuperar_txt_rechaza_archivo_de_recuperacion_alterado(db, tmp_path):
    _dgr(db)
    remittance = _remittance()
    service = _recover_service(tmp_path / "archive")
    original = tmp_path / "original.TXT"
    batch = service.generate([remittance], original)
    original.unlink()
    archive = service._archive_path(batch.batch_number, batch.sha256)
    archive.write_bytes(b"alterado")

    with pytest.raises(F150ValidationError, match="SHA-256"):
        service.recover_txt(batch, tmp_path / "copia.TXT")


def test_recuperar_txt_no_sobrescribe_archivo_existente(db, tmp_path):
    _dgr(db)
    remittance = _remittance()
    service = _recover_service(tmp_path / "archive")
    batch = service.generate([remittance], tmp_path / "original.TXT")
    existing = tmp_path / "existente.TXT"
    existing.write_text("no tocar")

    with pytest.raises(FileExistsError):
        service.recover_txt(batch, existing)
    assert existing.read_text() == "no tocar"
    assert F150Batch.select().count() == 1


def test_recuperar_txt_error_de_ruta_no_modifica_el_lote(db, tmp_path):
    _dgr(db)
    remittance = _remittance()
    service = _recover_service(tmp_path / "archive")
    batch = service.generate([remittance], tmp_path / "original.TXT")
    blocker = tmp_path / "blocker"
    blocker.write_text("archivo")

    with pytest.raises(OSError):
        service.recover_txt(batch, blocker / "salida.TXT")
    assert F150Batch.select().count() == 1
    assert F150Batch.get_by_id(batch.id).sha256 == batch.sha256


def test_golden_master_f150_se_reproduce_byte_a_byte():
    from scripts.verify_f150_corpus import parse

    path = Path("docs/F.150-05-10-2026B.TXT")
    raw = path.read_bytes()
    generated = F150Encoder().encode(parse(path)).encode(F150Encoder.encoding)
    assert generated == raw
