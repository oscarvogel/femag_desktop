"""#683: el precio del renglón queda congelado al emitir el remito.

El legacy guardaba el precio unitario en ``detalleremito.unitario`` y la
reescritura lo perdió. Sin eso el F150 leía ``Product.precio_neto_base``, que
además es siempre el precio de la lista 1: a un cliente de otra lista le
ponía el precio de otra.

La regla del precio ya existía en ``LoadOrderService`` para las órdenes de
carga. Acá se comparte y se congela en el renglón del remito.
"""

import json
from datetime import date
from decimal import Decimal

import pytest

from app.importers.dgr_reference import DgrReferenceImporter
from app.models.dgr import DgrLocality
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.system import AppParameter
from app.services.f150_batch_service import F150BatchService
from app.services.f150_encoder import F150ValidationError
from app.services.pricing import price_for_client_list
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

# Replica el caso real: el maestro tiene una sola lista y los clientes operan
# en listas distintas.
PRECIO_LISTA_1 = Decimal("20000")
PRECIO_LISTA_2 = Decimal("32200")
PRECIO_LISTA_3 = Decimal("42000")


def _maestros(db):
    DgrReferenceImporter().import_rows(DGR_ROWS)
    AppParameter.create(key="f150.origin", value=json.dumps({"locality_code": "2457"}))
    locality = DgrLocality.get(DgrLocality.code == "2457")
    product = Product.create(
        codigo="0001", name="BOLSAS DE FECULA NATIVA", unit="U",
        rh1="2", rh2="2", rh3="19", rh4="0", unidad_dgr="U",
        precio_neto_base=float(PRECIO_LISTA_1),
        precio_lista_1=float(PRECIO_LISTA_1),
        precio_lista_2=float(PRECIO_LISTA_2),
        precio_lista_3=float(PRECIO_LISTA_3),
    )
    carrier = Carrier.create(
        name="Transporte 683", cuit="20-23737702-9", codigo="0004",
        tipo="DIR", locality=locality, address="Ruta 12 km 8",
    )
    truck = Truck.create(
        domain="GET683", trailer_domain="KKV479", carrier=carrier,
        chassis_type="1", trailer_type="1",
    )
    driver = Driver.create(
        name="Chofer 683", carrier=carrier, usual_truck=truck,
        cuit="20-30717891-6", document="30717891", locality=locality,
        address="Posadas",
    )
    return product, carrier, truck, driver, locality


def _cliente(nombre, cuit, lista_precios, locality):
    client = Client.create(
        name=nombre, cuit=cuit, iva_condition="RI", lista_precios=lista_precios
    )
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones",
        city="Puerto Rico", address="Ruta 12 km 8", locality=locality,
    )
    return client, address


def _remito(db, *, lista_precios, unit_price=None):
    product, carrier, truck, driver, locality = _maestros(db)
    client, address = _cliente("Cliente 683", "30-63634545-4", lista_precios, locality)
    item = {"product": product, "quantity": Decimal("1140")}
    if unit_price is not None:
        item["unit_price"] = unit_price
    service = RemittanceService("admin")
    remittance = service.create_manual(
        client=client, delivery_address=address, carrier=carrier, truck=truck,
        driver=driver, physical_point_of_sale="0001", physical_number="683",
        remittance_date=date(2026, 10, 16), items=[item],
    )
    return service, remittance


def test_precio_toma_la_lista_del_cliente_y_no_la_lista_1(db):
    """El defecto: precio_neto_base es siempre la lista 1."""
    _, remittance = _remito(db, lista_precios=2)
    assert remittance.items.get().unit_price == PRECIO_LISTA_2


def test_clientes_de_distintas_listas_generan_precios_distintos(db):
    """Dos remitos del mismo producto, para clientes de listas distintas."""
    product, carrier, truck, driver, locality = _maestros(db)
    service = RemittanceService("admin")
    precios = {}
    for nombre, cuit, lista in (("Lista 2", "30-63634545-4", 2), ("Lista 3", "30-63634545-5", 3)):
        client, address = _cliente(nombre, cuit, lista, locality)
        remittance = service.create_manual(
            client=client, delivery_address=address, carrier=carrier, truck=truck,
            driver=driver, physical_point_of_sale="0001", physical_number=str(lista),
            remittance_date=date(2026, 10, 16),
            items=[{"product": product, "quantity": Decimal("1140")}],
        )
        precios[nombre] = remittance.items.get().unit_price
    assert precios["Lista 2"] == PRECIO_LISTA_2
    assert precios["Lista 3"] == PRECIO_LISTA_3


def test_precio_explicito_del_renglon_gana(db):
    """El operador negocia y corrige: ese valor es el que se congela."""
    _, remittance = _remito(db, lista_precios=2, unit_price=Decimal("35000.0000"))
    assert remittance.items.get().unit_price == Decimal("35000.0000")


def test_tocar_el_maestro_no_altera_un_remito_ya_emitido(db):
    service, remittance = _remito(db, lista_precios=2)
    issued = service.issue(remittance)
    product = issued.items.get().product
    product.precio_lista_2 = 1.0
    product.precio_neto_base = 1.0
    product.save()
    reloaded = type(issued).get_by_id(issued.id)
    assert reloaded.items.get().unit_price == PRECIO_LISTA_2


def test_f150_usa_el_precio_congelado_y_no_el_del_maestro(db, tmp_path):
    service, remittance = _remito(db, lista_precios=2)
    issued = service.issue(remittance)
    product = issued.items.get().product
    product.precio_lista_2 = 99999.0
    product.save()
    output = tmp_path / "f150-683.TXT"
    F150BatchService("admin").generate([type(issued).get_by_id(issued.id)], output)
    detail = output.read_bytes().decode("cp1252").splitlines()[1]
    assert "@1,140@32,200.00@36,708,000.00@" in detail


def test_f150_bloquea_si_el_renglon_no_tiene_precio(db, tmp_path):
    """Sin precio congelado no se estima ningun importe."""
    service, remittance = _remito(db, lista_precios=2)
    issued = service.issue(remittance)
    item = issued.items.get()
    item.unit_price = Decimal("0")
    item.save()
    with pytest.raises(F150ValidationError) as error:
        F150BatchService("admin").generate(
            [type(issued).get_by_id(issued.id)], tmp_path / "f150-683.TXT"
        )
    assert "sin precio de operacion" in str(error.value)


def test_emitir_congelan_un_renglon_sin_precio(db):
    """Los renglones anteriores a la columna llegan vacios y se resuelven al emitir."""
    service, remittance = _remito(db, lista_precios=3)
    item = remittance.items.get()
    item.unit_price = None
    item.save()
    issued = service.issue(type(remittance).get_by_id(remittance.id))
    assert issued.items.get().unit_price == PRECIO_LISTA_3


def test_precio_cae_a_precio_neto_base_si_la_lista_no_tiene_valor(db):
    product, *_ = _maestros(db)
    product.precio_lista_2 = 0.0
    product.save()

    class _Cliente:
        lista_precios = 2

    assert price_for_client_list(product, _Cliente()) == PRECIO_LISTA_1