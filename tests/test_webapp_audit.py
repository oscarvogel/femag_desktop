"""La webapp deja rastro de quien entra y de quien carga cada parte (#778).

En la planta se pasa el mismo celular entre varias personas y a veces la
misma clave. Sin registro, un parte cargado por error no tiene dueño y no
hay forma de saber que paso en el turno ni desde que equipo se entro.

Estos tests fijan dos cosas: que la fila de auditoria exista con el dato que
sirve (la IP del celular), y que un problema al registrar **no** impida
cargar el parte: el parte cargado vale mas que la fila de auditoria.
"""

from decimal import Decimal

from app.models.audit import AuditLog
from app.models.masters import (
    PRODUCT_KIND_PRODUCT,
    STOCK_ROLE_FINISHED,
    STOCK_ROLE_RAW,
    Product,
)
from app.models.stock import StockMovement
from app.services.auth_service import AuthService
from app.services.stock_service import StockService
from webapp import create_app


PASSWORD = "clave-de-prueba-123"


def _app():
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    return app


def _crear_usuario(username="operador", profile_name="Secretaría", password=PASSWORD):
    return AuthService().create_user(
        username,
        password,
        profile_name,
        display_name=username,
        actor="test",
    )


def _crear_productos():
    producto = Product.create(
        name="BOLSAS DE FECULA NATIVA",
        unit="kg",
        peso_unitario_kg=Decimal("25.000"),
        product_kind=PRODUCT_KIND_PRODUCT,
        stock_role=STOCK_ROLE_FINISHED,
    )
    materia = Product.create(
        name="ALMIDON DE MAIZ A GRANEL",
        unit="kg",
        peso_unitario_kg=Decimal("1000.000"),
        product_kind=PRODUCT_KIND_PRODUCT,
        stock_role=STOCK_ROLE_RAW,
    )
    return producto, materia


def _ingresar_materia(materia, kilos="20000"):
    StockService.register(
        product=materia,
        movement_type=StockMovement.TYPE_PURCHASE,
        quantity_kg=Decimal(kilos),
        source_ref="test:compra-materia",
        description="Compra de prueba",
    )


def _login(client, username="operador", password=PASSWORD):
    return client.post("/login", data={"username": username, "password": password})


def _payload_part(
    producto, materia, *, kilos="1000", bolsas="40", fecha="2026-10-21", turno="Mañana"
):
    return {
        "fecha": fecha,
        "turno": turno,
        "product_0": str(producto.id),
        "bags_0": bolsas,
        "materia_0": str(materia.id),
        "kg_0": kilos,
        "observaciones": "",
    }


def _filas_de_auditoria():
    return list(AuditLog.select().order_by(AuditLog.id))


def test_el_ingreso_queda_registrado_con_la_ip_del_celular(db):
    """La IP es lo que dice desde que equipo entro cada vez."""
    _crear_usuario()
    app = _app()
    client = app.test_client()

    _login(client)

    filas = [row for row in _filas_de_auditoria() if row.action == "login exitoso"]
    assert len(filas) == 1
    assert filas[0].user == "operador"
    assert filas[0].module == "Sistema"
    # El cliente de pruebas viene de 127.0.0.1: eso es la IP del celular.
    assert filas[0].workstation == "127.0.0.1"


def test_un_ingreso_fallido_también_queda_registrado(db):
    _crear_usuario()
    app = _app()
    client = app.test_client()

    _login(client, password="clave-incorrecta")

    fallidos = [row for row in _filas_de_auditoria() if row.action == "login fallido"]
    assert len(fallidos) == 1
    assert fallidos[0].workstation == "127.0.0.1"


def test_la_salida_queda_registrada(db):
    _crear_usuario()
    app = _app()
    client = app.test_client()
    _login(client)

    response = client.get("/logout")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    salidas = [row for row in _filas_de_auditoria() if row.action == "salida"]
    assert len(salidas) == 1
    assert salidas[0].user == "operador"


def test_cargar_un_parte_deja_registrado_quien_lo_cargo(db):
    _crear_usuario()
    producto, materia = _crear_productos()
    _ingresar_materia(materia)
    app = _app()
    client = app.test_client()
    _login(client)

    client.post("/produccion", data=_payload_part(producto, materia))

    cargas = [row for row in _filas_de_auditoria() if row.action == "carga de parte"]
    assert len(cargas) == 1
    row = cargas[0]
    assert row.user == "operador"
    assert row.module == "Produccion"
    assert row.workstation == "127.0.0.1"
    assert row.new_value["usuario"] == "operador"
    assert row.new_value["bolsas"] == 40
    assert row.new_value["kg"] == 1000.0
    assert row.new_value["turno"] == "Mañana"
    assert row.record_ref.startswith("ProductionPart:")


def test_confirmar_un_parte_queda_registrado(db):
    _crear_usuario()
    producto, materia = _crear_productos()
    _ingresar_materia(materia)
    app = _app()
    client = app.test_client()
    _login(client)
    client.post("/produccion", data=_payload_part(producto, materia))
    parte_id = [
        row.new_value["parte"]
        for row in _filas_de_auditoria()
        if row.action == "carga de parte"
    ][0]

    client.post(f"/produccion/{parte_id}/confirmar")

    confirmaciones = [
        row for row in _filas_de_auditoria() if row.action == "confirmacion de parte"
    ]
    assert len(confirmaciones) == 1
    assert confirmaciones[0].new_value["parte"] == parte_id


def test_anular_un_parte_queda_registrado_con_el_motivo(db):
    _crear_usuario()
    producto, materia = _crear_productos()
    _ingresar_materia(materia)
    app = _app()
    client = app.test_client()
    _login(client)
    client.post("/produccion", data=_payload_part(producto, materia))
    parte_id = [
        row.new_value["parte"]
        for row in _filas_de_auditoria()
        if row.action == "carga de parte"
    ][0]

    client.post(f"/produccion/{parte_id}/anular", data={"motivo": "Se cargo dos veces"})

    anulaciones = [
        row for row in _filas_de_auditoria() if row.action == "anulacion de parte"
    ]
    assert len(anulaciones) == 1
    assert anulaciones[0].observation == "Se cargo dos veces"


def test_si_falla_la_auditoria_el_operario_igual_puede_entrar_y_cargar(db, monkeypatch):
    """El parte vale mas que la fila de auditoria.

    Si la auditoria falla (por ejemplo, porque la tabla todavia no esta
    migrada), el operario tiene que poder entrar y cargar el parte igual: el
    problema se ve en el log del servidor, no en el celular.
    """
    _crear_usuario()
    producto, materia = _crear_productos()
    _ingresar_materia(materia)
    app = _app()
    client = app.test_client()

    def _explota(*args, **kwargs):
        raise RuntimeError("la tabla de auditoria no existe")

    monkeypatch.setattr(AuditLog, "create", staticmethod(_explota))

    ingreso = _login(client)

    assert ingreso.status_code == 302
    with client.session_transaction() as session:
        assert session["femag_username"] == "operador"

    respuesta = client.post("/produccion", data=_payload_part(producto, materia))

    assert respuesta.status_code == 302
    from app.models.production import ProductionPart

    assert ProductionPart.select().count() == 1
