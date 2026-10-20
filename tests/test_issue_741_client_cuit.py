"""#741: el importador no le saca el CUIT a otro cliente ni aborta la importacion.

``client.cuit`` es unico. El legacy tiene filas que comparten CUIT (el mismo
cliente con dos codigos) y filas a las que les corrigieron el CUIT con el de
otra. Cuando eso pasaba, el importador le pisaba el CUIT al cliente que ya
existia por su ``source_id`` y el guardado reventaba con
``Duplicate entry ... for key 'client.client_cuit'``: la importacion entera se
caia y con ella los camiones, los choferes, los productos y las direcciones.
"""

from app.importers.legacy_dbf import LegacyDbfMasterImporter
from app.models.masters import Client


CLIENT_A = {
    "CODIGO": "0635",
    "NOMBRE": "DISTRIB.DE INSUMOS Y MAT.PRIMAS EG SRL",
    "CUIT": "30-71655178-0",
    "DOMICILIO": "AV. RIVADAVIA 1234",
    "CODPOS": "1002",
    "IMPOSITIVO": "CUIDAD AUTONOMA",
    "LOCALIDAD": "0001",
}

CLIENT_B = {
    "CODIGO": "0664",
    "NOMBRE": "DISTRIBUIDORA DE MAT. PRIMAS S.A",
    "CUIT": "30-71415724-4",
    "DOMICILIO": "AV. CORRIENTES 2222",
    "CODPOS": "1002",
    "IMPOSITIVO": "CUIDAD AUTONOMA",
    "LOCALIDAD": "0001",
}


def _import_clients(rows):
    return LegacyDbfMasterImporter().import_rows({"clients": rows})


def test_una_fila_no_le_saca_el_cuit_a_otro_cliente(db):
    """El CUIT que ya tiene otro cliente no se le pone encima."""
    _import_clients([CLIENT_A, CLIENT_B])
    cliente_b = Client.get(Client.source_id == "0664")
    cuit_original = cliente_b.cuit

    # La fila 0664 ahora trae en el legacy el CUIT que tiene la 0635.
    _import_clients([dict(CLIENT_B, CUIT="30-71655178-0")])

    cliente_b = Client.get(Client.source_id == "0664")
    assert cliente_b.cuit == cuit_original
    assert Client.select().count() == 2


def test_el_resumen_avisa_cuando_no_se_puede_tomar_el_cuit(db):
    """El operador tiene que ver en el resumen que el CUIT no se pudo tomar."""
    _import_clients([CLIENT_A, CLIENT_B])

    summary = _import_clients([dict(CLIENT_B, CUIT="30-71655178-0")])

    codigos = {warning["code"] for warning in summary["clients"]["warnings"]}
    assert "client_cuit_taken_by_another_row" in codigos
    assert summary["clients"]["errors"] == []


def test_una_fila_que_choca_con_un_indice_unico_no_frena_la_importacion(db):
    """Un choque puntual se anota y el resto de las filas se importa igual."""
    summary = _import_clients([CLIENT_A, {"CODIGO": "0665", "NOMBRE": "", "CUIT": ""}])

    assert summary["clients"]["created"] == 1
    assert len(summary["clients"]["errors"]) == 1
    assert summary["clients"]["errors"][0]["source_id"] == "0665"
    assert Client.select().count() == 1


def test_la_importacion_completa_no_aborta_y_avanza_a_las_siguientes_entidades(db):
    """Si un cliente falla, los camiones y los productos se importan igual."""
    summary = LegacyDbfMasterImporter().import_rows(
        {
            "clients": [CLIENT_A, {"CODIGO": "0665", "NOMBRE": "", "CUIT": ""}],
            "products": [
                {
                    "CODIGO": "0001",
                    "NOMBRE": "BOLSAS DE FECULA NATIVA",
                    "UNIDADDGR": "U",
                    "RH1": "2",
                    "RH2": "2",
                    "RH3": "19",
                    "RH4": "0",
                    "TIPOIVA": "01",
                    "KG": "",
                }
            ],
        }
    )

    assert summary["clients"]["created"] == 1
    assert len(summary["clients"]["errors"]) == 1
    assert summary["products"]["created"] == 1
