"""#744: un comando deja la base lista para generar el F150.

El setup son tres pasos y el orden importa: la referencia DGR, los maestros y
el origen. Si los maestros se importan sin la referencia DGR cargada, todos los
enlaces DGR quedan en ``NULL`` **sin ningun error**, y el F150 no sale sin que
nadie sepa por que.
"""

from datetime import date, datetime
from pathlib import Path

from app.models.dgr import DgrLocality
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product
from app.models.remittances import Remittance
from app.services.f150_batch_service import F150BatchService
from app.services.f150_setup_service import F150SetupService


# ----------------------------------------------------------------------
# DBF minimos (dbfread no escribe, asi que se arman a mano)
# ----------------------------------------------------------------------
def write_dbf(path: Path, fields, rows) -> Path:
    """Escribe un DBF dBase III con campos de texto.

    ``dbfread`` solo lee, asi que el formato se arma a mano: cabecera de 32
    bytes, un descriptor de 32 bytes por campo, el terminador ``0x0D`` y los
    registros. La cabecera tiene que decir cuanto mide (bytes 8-9) y cuanto
    mide cada registro (bytes 10-11), porque de ahi el lector decide donde
    empiezan los datos.
    """
    record_len = 1 + sum(length for _name, length in fields)
    header = bytearray(32)
    header[0] = 0x03  # dBase III, sin memo
    ahora = datetime.now()
    header[1] = ahora.year - 1900
    header[2] = ahora.month
    header[3] = ahora.day
    header[4:8] = len(rows).to_bytes(4, "little")
    header[8:10] = (32 + 32 * len(fields) + 1).to_bytes(2, "little")
    header[10:12] = record_len.to_bytes(2, "little")

    for name, length in fields:
        header += name.encode("ascii")[:10].ljust(11, b"\x00")
        header += b"C"
        header += b"\x00" * 4  # direccion del campo (reservado)
        header += bytes([length, 0])  # longitud y decimales
        header += b"\x00" * 14  # reservado
    header += b"\x0D"

    body = bytearray()
    for row in rows:
        body += b" "
        for name, length in fields:
            value = str(row.get(name, "") or "").replace("\r", " ").replace("\n", " ")
            body += value.encode("cp1252", errors="replace")[:length].ljust(length, b" ")
    body += b"\x1A"
    path.write_bytes(bytes(header) + bytes(body))
    return path


def escribir_dbf_de_la_fabrica(carpeta: Path) -> Path:
    """Arma una carpeta con los DBF que el setup necesita."""
    carpeta.mkdir(parents=True, exist_ok=True)
    write_dbf(carpeta / "paises.dbf", [("IDPAIS", 4), ("NOMBRE", 40), ("ABR", 4)],
              [{"IDPAIS": "200", "NOMBRE": "ARGENTINA", "ABR": "ARG"}])
    write_dbf(carpeta / "provincias.dbf", [("CODIGO", 4), ("DESCRIPCIO", 40)],
              [{"CODIGO": "1", "DESCRIPCIO": "CAPITAL FEDERAL"}])
    write_dbf(carpeta / "localidades.dbf",
              [("CODIGO", 6), ("LOCALIDAD", 40), ("CODIGODGR", 6), ("PAISDGR", 6),
               ("PROVDGR", 6), ("DEPA", 6), ("PROVINCIA", 40)],
              [{"CODIGO": "0001", "LOCALIDAD": "CAPITAL FEDERAL", "CODIGODGR": "1",
                "PAISDGR": "200", "PROVDGR": "1", "DEPA": "0", "PROVINCIA": "CAPITAL FEDERAL"},
               {"CODIGO": "2426", "LOCALIDAD": "CAPIOVI", "CODIGODGR": "15",
                "PAISDGR": "200", "PROVDGR": "14", "DEPA": "10", "PROVINCIA": "MISIONES"}])
    write_dbf(carpeta / "locdgr.dbf",
              [("IDLOCALIDA", 6), ("CODIGODGR", 6), ("PROVINCIA", 6), ("DPTO", 6),
               ("DESCRIPCIO", 40)],
              [{"IDLOCALIDA": "1", "CODIGODGR": "1", "PROVINCIA": "1", "DPTO": "0",
                "DESCRIPCIO": "CAPITAL FEDERAL"},
               {"IDLOCALIDA": "15", "CODIGODGR": "15", "PROVINCIA": "14", "DPTO": "10",
                "DESCRIPCIO": "CAPIOVI"}])
    write_dbf(carpeta / "clientes.dbf",
              [("CODIGO", 6), ("NOMBRE", 40), ("CUIT", 14), ("DOMICILIO", 40),
               ("CODPOS", 10), ("IMPOSITIVO", 30), ("LOCALIDAD", 6)],
              [{"CODIGO": "0001", "NOMBRE": "CLIENTE UNO", "CUIT": "30-12345678-9",
                "DOMICILIO": "AV. SIEMPRE 123", "CODPOS": "1002", "IMPOSITIVO": "CUIDAD",
                "LOCALIDAD": "0001"}])
    write_dbf(carpeta / "transporte.dbf",
              [("CODIGO", 6), ("NOMBRE", 40), ("CUIT", 14), ("DOMICILIO", 40),
               ("LOCALIDAD", 6), ("CODPOS", 10), ("TIPO", 6)],
              [{"CODIGO": "0001", "NOMBRE": "TRANSPORTE UNO", "CUIT": "30-87654321-9",
                "DOMICILIO": "LAVALLE 2809", "LOCALIDAD": "0001", "CODPOS": "1002",
                "TIPO": "DIR"}])
    write_dbf(carpeta / "chofer.dbf",
              [("CODIGO", 6), ("NOMBRE", 40), ("CUIT", 14), ("DOMICILIO", 40),
               ("LOCALIDAD", 6), ("CODPOS", 10), ("TIPOPATE", 4), ("CHASIS", 10),
               ("TIPOPATEAC", 4), ("ACOPLADO", 10)],
              [{"CODIGO": "0001", "NOMBRE": "CHOFER UNO", "CUIT": "20-11111111-1",
                "DOMICILIO": "JARDIN AMERICA", "LOCALIDAD": "0001", "CODPOS": "3328",
                "TIPOPATE": "1", "CHASIS": "ENS886", "TIPOPATEAC": "2",
                "ACOPLADO": "AC476IH"}])
    write_dbf(carpeta / "productos.dbf",
              [("CODIGO", 6), ("NOMBRE", 40), ("UNIDADDGR", 4), ("RH1", 4), ("RH2", 4),
               ("RH3", 4), ("RH4", 4), ("TIPOIVA", 4), ("KG", 12)],
              [{"CODIGO": "0001", "NOMBRE": "FECULA", "UNIDADDGR": "U", "RH1": "2",
                "RH2": "2", "RH3": "19", "RH4": "0", "TIPOIVA": "01", "KG": ""}])
    write_dbf(carpeta / "param.dbf", [("LOCORIGEN", 6), ("EMPRESA", 40)],
              [{"LOCORIGEN": "2426", "EMPRESA": "FEMAG"}])
    return carpeta


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------
def test_el_setup_importa_todo_y_deja_el_origen_configurado(db, tmp_path):
    carpeta = escribir_dbf_de_la_fabrica(tmp_path / "fabrica")

    report = F150SetupService().run(dbf_dir=carpeta)

    assert report.warnings == ()
    assert report.blockers == ()
    assert report.origin is not None
    assert report.origin.locality_name == "CAPIOVI"
    assert F150BatchService.origin_configured() is True
    assert DgrLocality.select().count() == 2
    assert Carrier.select().count() == 1
    assert Driver.select().count() == 1
    assert Product.select().count() == 1
    assert ClientAddress.select().count() == 1
    assert Carrier.get().locality is not None
    assert Driver.get().locality is not None
    assert ClientAddress.get().locality is not None
    assert Product.get().unidad_dgr == "U"


def test_el_setup_es_idempotente(db, tmp_path):
    carpeta = escribir_dbf_de_la_fabrica(tmp_path / "fabrica")

    F150SetupService().run(dbf_dir=carpeta)
    segunda = F150SetupService().run(dbf_dir=carpeta)

    assert segunda.warnings == ()
    assert segunda.blockers == ()
    assert DgrLocality.select().count() == 2
    assert Carrier.select().count() == 1
    assert ClientAddress.select().count() == 1
    assert ClientAddress.get().locality is not None


def test_sin_referencia_dgr_no_importa_los_maestros_y_avisa(db, tmp_path):
    """El modo de falla silencioso: sin DGR los maestros quedan en NULL."""
    carpeta = escribir_dbf_de_la_fabrica(tmp_path / "fabrica")

    report = F150SetupService().run(
        dbf_dir=carpeta, import_dgr=False, configure_origin=False
    )

    assert any("referencia DGR" in blocker for blocker in report.blockers)
    assert report.ok is False
    assert Carrier.select().count() == 0
    assert Driver.select().count() == 0


def test_avisa_cuando_no_hay_que_importar_por_faltar_dbf(db, tmp_path):
    carpeta = tmp_path / "vacia"
    carpeta.mkdir()

    report = F150SetupService().run(dbf_dir=carpeta)

    assert report.warnings
    assert report.blockers
    assert report.origin is None
    assert report.ok is False


def test_el_origen_sale_del_param_dbf_del_legacy(tmp_path):
    carpeta = escribir_dbf_de_la_fabrica(tmp_path / "fabrica")

    assert F150SetupService.origin_code_from_param(carpeta / "param.dbf") == "2426"
    assert F150SetupService.origin_code_from_param(carpeta / "no-existe.dbf") is None


def test_el_origen_se_puede_forzar_con_el_codigo_de_localidad(db, tmp_path):
    carpeta = escribir_dbf_de_la_fabrica(tmp_path / "fabrica")

    report = F150SetupService().run(dbf_dir=carpeta, locality_code="0001")

    assert report.warnings == ()
    assert report.origin is not None
    assert report.origin.locality_code == "0001"
    assert report.origin.locality_name == "CAPITAL FEDERAL"


def test_avisa_si_la_localidad_de_origen_no_existe_en_la_referencia(db, tmp_path):
    """En la maquina del cliente el param.dbf puede traer un codigo que no esta."""
    carpeta = escribir_dbf_de_la_fabrica(tmp_path / "fabrica")

    report = F150SetupService().run(dbf_dir=carpeta, locality_code="9999")

    assert report.origin is None
    assert any("9999" in blocker for blocker in report.blockers)
    assert report.ok is False


def test_avisa_si_la_importacion_dejo_filas_sin_entrar(db, tmp_path):
    """Una fila que no entra tiene que quedar a la vista, no en el resumen.

    Pero no voltea el resultado: una fila del legacy que no se pudo importar no
    deja al resto de la base sin poder emitir. El legacy real tiene una asi
    (el chofer 0090, sin nombre ni CUIT) y con ella el setup tiene que salir
    con exito igual.
    """
    carpeta = escribir_dbf_de_la_fabrica(tmp_path / "fabrica")
    write_dbf(
        carpeta / "clientes.dbf",
        [("CODIGO", 6), ("NOMBRE", 40), ("CUIT", 14), ("DOMICILIO", 40),
         ("CODPOS", 10), ("IMPOSITIVO", 30), ("LOCALIDAD", 6)],
        [{"CODIGO": "", "NOMBRE": "SIN CODIGO", "CUIT": "30-99999999-7",
          "DOMICILIO": "AV. X 100", "CODPOS": "1002", "IMPOSITIVO": "CUIDAD",
          "LOCALIDAD": "0001"}],
    )

    report = F150SetupService().run(dbf_dir=carpeta)

    assert any("sin entrar" in warning for warning in report.warnings)
    assert report.masters["clients"]["errors"]
    assert report.ok is True


def test_el_setup_avisa_que_hay_remitos_bloqueados(db, tmp_path):
    carpeta = escribir_dbf_de_la_fabrica(tmp_path / "fabrica")
    F150SetupService().run(dbf_dir=carpeta)

    cliente = Client.get()
    direccion = ClientAddress.get()
    remittance = Remittance.create(
        remittance_number="REM-00000001",
        physical_point_of_sale="0001",
        physical_number="00000001",
        date=date(2026, 10, 20),
        status=Remittance.STATUS_ISSUED,
        client=cliente,
        delivery_address=direccion,
        client_name=cliente.name,
        client_cuit=cliente.cuit,
        delivery_address_text=direccion.address,
    )
    assert remittance.id

    report = F150SetupService().run(dbf_dir=carpeta)

    assert report.remittances_ready == 0
    assert report.remittances_blocked
    numero, problemas = report.remittances_blocked[0]
    assert numero == "REM-00000001"
    # El origen si quedo configurado: no es lo que bloquea este remito.
    assert not any("origen" in problema for problema in problemas)
    assert report.ok is False
