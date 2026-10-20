"""#688: ``clientaddress.locality`` no se backfillea al reimportar.

La referencia DGR importada y los maestros reimportados llenan todos los
enlaces DGR, menos ``clientaddress.locality``: el servicio que reutiliza la
dirección que ya existe no toca ese campo, y las direcciones importadas cuando
``dgrlocality`` estaba vacía quedan con ``locality_id = NULL``. Sin localidad el
F150 no puede emitir: el destino sale sin provincia ni pais.
"""

from app.importers.dgr_reference import DgrReferenceImporter
from app.importers.legacy_dbf import LegacyDbfMasterImporter
from app.models.dgr import DgrLocality
from app.models.masters import Client, ClientAddress


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
}


def _import_clients(rows, *, mode: str = "patch"):
    return LegacyDbfMasterImporter(mode=mode).import_rows({"clients": rows})


def test_reimport_backfillea_la_localidad_de_la_direccion_existente(db):
    """Criterio 1: con DGR cargado, la direccion que ya existia queda con localidad."""
    DgrReferenceImporter().import_rows(DGR_ROWS)

    # Primera pasada: el legacy todavia no tiene localidad cargada en la base.
    _import_clients([dict(CLIENT_ROW, LOCALIDAD="")])
    address = ClientAddress.get()
    assert address.locality_id is None

    # Segunda pasada: el legacy ya trae la localidad y la base ya tiene la direccion.
    summary = _import_clients([CLIENT_ROW])

    address = ClientAddress.get()
    assert address.locality_id is not None
    assert address.locality.name == "CAPITAL FEDERAL"
    assert summary["clients"]["localidad_backfill"] == 1


def test_el_resumen_cuantos_backfilleo_y_cuantos_actualizo(db):
    """Criterio 1: el resumen dice cuantos se backfillearon."""
    DgrReferenceImporter().import_rows(DGR_ROWS)
    _import_clients([dict(CLIENT_ROW, LOCALIDAD="")])

    summary = _import_clients([CLIENT_ROW])
    assert summary["clients"]["localidad_backfill"] == 1
    assert summary["clients"]["localidad_actualizada"] == 0


def test_correrlo_dos_veces_no_cambia_el_resultado(db):
    """Criterio 2: la importacion es idempotente."""
    DgrReferenceImporter().import_rows(DGR_ROWS)
    _import_clients([dict(CLIENT_ROW, LOCALIDAD="")])

    first = _import_clients([CLIENT_ROW])
    second = _import_clients([CLIENT_ROW])

    assert first["clients"]["localidad_backfill"] == 1
    assert second["clients"]["localidad_backfill"] == 0
    assert second["clients"]["localidad_actualizada"] == 0
    assert ClientAddress.select().count() == 1
    assert ClientAddress.get().locality.name == "CAPITAL FEDERAL"


def test_en_modo_patch_una_direccion_con_otra_localidad_se_respeta(db):
    """#746: en una base viva la direccion conserva la localidad que tiene.

    Puede ser que el operador la haya corregido a mano, asi que la
    importacion no la pisa: solo la cuenta.
    """
    DgrReferenceImporter().import_rows(DGR_ROWS)
    _import_clients([CLIENT_ROW])
    assert ClientAddress.get().locality.name == "CAPITAL FEDERAL"

    summary = _import_clients([dict(CLIENT_ROW, LOCALIDAD="2430")])

    assert ClientAddress.get().locality.name == "CAPITAL FEDERAL"
    assert summary["clients"]["localidad_respetada"] == 1
    assert summary["clients"]["localidad_actualizada"] == 0
    assert summary["clients"]["localidad_backfill"] == 0


def test_en_modo_overwrite_la_direccion_sigue_la_localidad_del_legacy(db):
    """Criterio 3 de #688, disponible a proposito con el modo overwrite."""
    DgrReferenceImporter().import_rows(DGR_ROWS)
    _import_clients([CLIENT_ROW], mode="overwrite")
    assert ClientAddress.get().locality.name == "CAPITAL FEDERAL"

    summary = _import_clients([dict(CLIENT_ROW, LOCALIDAD="2430")], mode="overwrite")

    assert ClientAddress.get().locality.name == "PUERTO RICO"
    assert summary["clients"]["localidad_actualizada"] == 1
    assert summary["clients"]["localidad_backfill"] == 0


def test_una_direccion_sin_localidad_en_el_legacy_no_pisa_la_que_tenia(db):
    """Criterio 4: sin localidad en el legacy, la direccion conserva la suya."""
    DgrReferenceImporter().import_rows(DGR_ROWS)
    _import_clients([CLIENT_ROW])
    assert ClientAddress.get().locality.name == "CAPITAL FEDERAL"

    summary = _import_clients([dict(CLIENT_ROW, LOCALIDAD="")])

    assert ClientAddress.get().locality.name == "CAPITAL FEDERAL"
    assert summary["clients"]["localidad_backfill"] == 0
    assert summary["clients"]["localidad_actualizada"] == 0


def test_el_backfill_no_toca_direcciones_de_otros_tipos(db):
    """Solo se completa la direccion fiscal/entrega, no cualquier direccion."""
    DgrReferenceImporter().import_rows(DGR_ROWS)
    client = Client.create(name="Cliente Norte", cuit="30722222226", iva_condition="RI")
    otra = ClientAddress.create(
        client=client,
        address_type="otro",
        province="Misiones",
        city="Posadas",
        address="Sucursal",
    )

    _import_clients([CLIENT_ROW])

    otra = ClientAddress.get(ClientAddress.id == otra.id)
    assert otra.locality_id is None


def test_el_backfill_deja_la_localidad_que_ya_venia_de_otra_importacion(db):
    """Una direccion creada a mano con su localidad no se pisa con la del legacy."""
    DgrReferenceImporter().import_rows(DGR_ROWS)
    client = Client.create(name="Cliente Norte", cuit="30722222226", iva_condition="RI")
    preexisting = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Sucursal",
        locality=DgrLocality.get(DgrLocality.code == "2430"),
    )

    _import_clients([CLIENT_ROW])

    preexisting = ClientAddress.get(ClientAddress.id == preexisting.id)
    assert preexisting.locality.name == "PUERTO RICO"
