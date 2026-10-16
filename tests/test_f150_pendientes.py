"""Al emitir, el F150 sale solo; si falta un dato, el remito queda pendiente.

La pantalla de F150 es donde el operador termina esos remitos, asi que tiene
que mostrar de entrada cuantos son listos y cuantos quedaron parados, sin que
tenga que revisar fila por fila.
"""

import json
from datetime import date
from decimal import Decimal

from app.importers.dgr_reference import DgrReferenceImporter
from app.models.dgr import DgrLocality
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.system import AppParameter
from app.services.remittance_service import RemittanceService

DGR_ROWS = {
    "paises": [{"IDPAIS": 200, "NOMBRE": "ARGENTINA", "ABR": "ARG"}],
    "provincias": [{"CODIGO": 14, "DESCRIPCIO": "MISIONES"}],
    "locdgr": [
        {"IDLOCALIDA": 61, "CODIGODGR": 61, "PROVINCIA": 14, "DPTO": 10,
         "DESCRIPCIO": "PUERTO RICO"}
    ],
    "localidades": [
        {"CODIGO": "2457", "LOCALIDAD": "PUERTO RICO", "CODIGODGR": 61,
         "PAISDGR": 200, "PROVDGR": 14, "DEPA": 10, "PROVINCIA": "MISIONES"}
    ],
}


def _emitir(db, nombre, numero, *, cuit="30-63634545-4",
            carrier_address="Ruta 12 km 8", driver_address="Posadas"):
    DgrReferenceImporter().import_rows(DGR_ROWS)
    if AppParameter.get_or_none(AppParameter.key == "f150.origin") is None:
        AppParameter.create(key="f150.origin", value=json.dumps({"locality_code": "2457"}))
    locality = DgrLocality.get(DgrLocality.code == "2457")
    client = Client.create(name=nombre, cuit=cuit, iva_condition="RI")
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones",
        city="Puerto Rico", address="Ruta 12 km 8", locality=locality,
    )
    carrier = Carrier.create(
        name=f"Transporte {numero}", cuit="20-23737702-9", codigo="0004",
        tipo="DIR", locality=locality, address=carrier_address,
    )
    truck = Truck.create(
        domain=f"GET{numero}", trailer_domain=f"KKV{numero}", carrier=carrier,
        chassis_type="1", trailer_type="1",
    )
    driver = Driver.create(
        name=f"Chofer {numero}", carrier=carrier, usual_truck=truck,
        cuit="20-30717891-6", document="30717891", locality=locality,
        address=driver_address,
    )
    product = Product.create(
        codigo=f"00{numero}", name=f"BOLSAS DE FECULA NATIVA {numero}", unit="U",
        rh1="2", rh2="2", rh3="19", rh4="0", unidad_dgr="U",
        precio_neto_base=32200.0, precio_lista_1=32200.0,
    )
    service = RemittanceService("admin")
    draft = service.create_manual(
        client=client, delivery_address=address, carrier=carrier, truck=truck,
        driver=driver, physical_point_of_sale="0001", physical_number=numero,
        remittance_date=date.today(),
        items=[{"product": product, "quantity": Decimal("1140")}],
    )
    return service.issue(draft)


def _page(db, tmp_path):
    from PyQt5.QtWidgets import QApplication

    from app.ui.f150 import F150Page

    app = QApplication.instance() or QApplication([])
    page = F150Page(current_user="admin", output_dir=tmp_path)
    app.processEvents()
    page.refresh()
    # Se guarda en una lista del modulo porque PyQt destruye el widget si queda
    # solo referenciado por una variable local de este scope.
    _PAGES.append(page)
    return page


_PAGES: list = []


def test_resumen_avisa_cuantos_pendientes(db, tmp_path):
    _emitir(db, "Cliente Listo", "9001", cuit="30-63634545-4")
    _emitir(db, "Cliente Pendiente", "9002", carrier_address=None, cuit="30-63634545-5")
    page = _page(db, tmp_path)
    text = page.pending_summary
    assert "1 listo" in text
    assert "1 pendiente" in text
    assert "Validación" in text


def test_resumen_no_avoriza_cuando_no_hay_pendientes(db, tmp_path):
    _emitir(db, "Cliente Listo", "9003", cuit="30-63634545-6")
    page = _page(db, tmp_path)
    text = page.pending_summary
    assert "pendiente" not in text
    assert "listo" in text


def test_resumen_avisa_cuando_no_hay_remitos(db, tmp_path):
    page = _page(db, tmp_path)
    assert "No hay remitos" in page.pending_summary


def test_texto_del_resumen_por_caso():
    """La logica del resumen, sin depender del widget."""
    from app.ui.f150 import F150Page

    assert "No hay remitos" in F150Page._pending_summary_text(0, 0)
    sin_pendientes = F150Page._pending_summary_text(3, 0)
    assert "3 remitos listos" in sin_pendientes
    assert "pendiente" not in sin_pendientes
    con_pendientes = F150Page._pending_summary_text(5, 2)
    assert "3 listos" in con_pendientes
    assert "2 pendientes" in con_pendientes
    singular = F150Page._pending_summary_text(1, 1)
    assert "1 pendiente " in singular