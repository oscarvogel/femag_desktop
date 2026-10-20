"""#746: la importacion de maestros no pisa lo que el operador ya edito.

La base del cliente es una base **viva**: el operador ya corrigio nombres,
telefonos, domicilios y rubros. Una reimportacion no puede deshacer eso.

El modo por defecto es ``patch``: la importacion solo **completa los campos
vacios**. De los campos que el operador no edita en el ABM (la localidad DGR,
los rubros DGR, el tipo de chasis) la importacion es duena y los corrige
siempre, porque son los que el F150 exige.
"""

from app.importers.dgr_reference import DgrReferenceImporter
from app.importers.legacy_dbf import LegacyDbfMasterImporter
from app.models.dgr import DgrLocality
from app.models.masters import Carrier, Client, ClientAddress, Product


DGR_ROWS = {
    "paises": [{"IDPAIS": 200, "NOMBRE": "ARGENTINA", "ABR": "ARG"}],
    "provincias": [{"CODIGO": 1, "DESCRIPCIO": "CAPITAL FEDERAL"}],
    "locdgr": [
        {"IDLOCALIDA": 1, "CODIGODGR": 1, "PROVINCIA": 1, "DPTO": 0, "DESCRIPCIO": "CAPITAL FEDERAL"},
        {"IDLOCALIDA": 61, "CODIGODGR": 61, "PROVINCIA": 14, "DPTO": 10, "DESCRIPCIO": "PUERTO RICO"},
    ],
    "localidades": [
        {"CODIGO": "0001", "LOCALIDAD": "CAPITAL FEDERAL", "CODIGODGR": 1,
         "PAISDGR": 200, "PROVDGR": 1, "DEPA": 0, "PROVINCIA": "CAPITAL FEDERAL"},
        {"CODIGO": "2430", "LOCALIDAD": "PUERTO RICO", "CODIGODGR": 61,
         "PAISDGR": 200, "PROVDGR": 14, "DEPA": 10, "PROVINCIA": "MISIONES"},
    ],
}

CLIENT_ROW = {
    "CODIGO": "0319",
    "NOMBRE": "BIOFEGMA S.A.",
    "CUIT": "30711111118",
    "DOMICILIO": "VIAMONTE 927",
    "CODPOS": "1053",
    "IMPOSITIVO": "CUIDAD AUTONOMA",
    "LOCALIDAD": "0001",
    "TELEFONO": "111",
}

CARRIER_ROW = {
    "CODIGO": "T001",
    "NOMBRE": "TRANSPORTE UNO",
    "CUIT": "30-87654321-9",
    "DOMICILIO": "LAVALLE 2809",
    "LOCALIDAD": "0001",
    "CODPOS": "1002",
    "TIPO": "DIR",
}

PRODUCT_ROW = {
    "CODIGO": "P001",
    "NOMBRE": "FECULA",
    "UNIDADDGR": "U",
    "RH1": "2",
    "RH2": "2",
    "RH3": "19",
    "RH4": "0",
}


def _importar(entities, *, mode: str = "patch"):
    return LegacyDbfMasterImporter(mode=mode).import_rows(entities)


def test_reimportar_no_pisa_el_nombre_ni_el_telefono_del_cliente(db):
    _importar({"clients": [CLIENT_ROW]})

    client = Client.get()
    client.name = "BIOFEGMA S.A. (CORREGIDO)"
    client.phone = "343-555-0000"
    client.save()

    summary = _importar({"clients": [dict(CLIENT_ROW, NOMBRE="BIOFEGMA OTRO NOMBRE", TELEFONO="999")]})

    client = Client.get()
    assert client.name == "BIOFEGMA S.A. (CORREGIDO)"
    assert client.phone == "343-555-0000"
    assert summary["clients"]["campos_pisados"] == 0


def test_reimportar_no_pisa_el_domicilio_que_edited_el_operador(db):
    _importar({"clients": [CLIENT_ROW]})

    address = ClientAddress.get()
    address.address = "AV. CORREGIDA 1234"
    address.city = "CIUDAD CORREGIDA"
    address.save()

    _importar({"clients": [CLIENT_ROW]})

    address = ClientAddress.get()
    assert address.address == "AV. CORREGIDA 1234"
    assert address.city == "CIUDAD CORREGIDA"


def test_reimportar_completa_lo_que_esta_vacio(db):
    """El caso del cliente: los maestros entraron sin DGR, el reimport los completa."""
    # Primero los maestros, cuando todavia no hay ninguna localidad DGR.
    _importar({"carriers": [CARRIER_ROW]})
    assert Carrier.get().locality is None

    # Despues llega la referencia DGR.
    DgrReferenceImporter().import_rows(DGR_ROWS)

    # Y el reimport completa lo que faltaba.
    _importar({"carriers": [CARRIER_ROW]})

    assert Carrier.get().locality is not None
    assert Carrier.get().locality.name == "CAPITAL FEDERAL"


def test_la_importacion_es_duena_de_la_localidad_y_los_rubros(db):
    """Esos campos el operador no los edita: la importacion los corrige."""
    DgrReferenceImporter().import_rows(DGR_ROWS)
    _importar({"carriers": [CARRIER_ROW], "products": [PRODUCT_ROW]})

    carrier = Carrier.get()
    carrier.locality = DgrLocality.get(DgrLocality.code == "2430")
    carrier.save()
    product = Product.get()
    product.rh1 = "9"
    product.save()

    _importar({"carriers": [CARRIER_ROW], "products": [PRODUCT_ROW]})

    assert Carrier.get().locality.name == "CAPITAL FEDERAL"
    assert Product.get().rh1 == "2"


def test_el_resumen_dice_cuanto_completo_y_cuanto_respeto(db):
    _importar({"clients": [CLIENT_ROW], "carriers": [CARRIER_ROW]})
    assert ClientAddress.get().locality is None

    DgrReferenceImporter().import_rows(DGR_ROWS)

    client = Client.get()
    client.phone = "343-555-0000"
    client.save()

    summary = _importar({"clients": [CLIENT_ROW], "carriers": [CARRIER_ROW]})

    # El telefono del operador se respeta: no se cuenta como campo pisado.
    assert summary["clients"]["campos_pisados"] == 0
    # Y la direccion del cliente quedo con la localidad que le faltaba.
    assert summary["clients"]["localidad_backfill"] == 1
    assert summary["clients"]["localidad_actualizada"] == 0
    assert summary["carriers"]["campos_completados"] >= 1
