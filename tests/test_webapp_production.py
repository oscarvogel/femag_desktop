"""Tests de la captura de partes de produccion desde la webapp (#754)."""

from datetime import date
from decimal import Decimal

from app.models.masters import (
    PRODUCT_KIND_PRODUCT,
    STOCK_ROLE_FINISHED,
    STOCK_ROLE_RAW,
    Product,
)
from app.models.production import ProductionPart
from app.models.stock import StockMovement
from app.services.auth_service import AuthService
from app.services.stock_service import StockService
from webapp import create_app
from webapp import production_service

PASSWORD = "clave-de-prueba-123"


def _app():
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    return app


def _crear_usuario(username="operador", profile_name="Secretaría", password=PASSWORD, active=True):
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


def _payload_part(producto, materia, *, kilos="1000", bolsas="40", fecha="2026-10-21", turno="Mañana"):
    return {
        "fecha": fecha,
        "turno": turno,
        "product_0": str(producto.id),
        "bags_0": bolsas,
        "materia_0": str(materia.id),
        "kg_0": kilos,
        "observaciones": "",
    }


def test_produccion_exige_sesion(db):
    app = _app()

    response = app.test_client().get("/produccion")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_valido_entra_y_uno_invalido_no(db):
    _crear_usuario()
    app = _app()
    client = app.test_client()

    response = _login(client, password="clave-incorrecta")

    assert response.status_code == 200
    assert b"Usuario o" in response.data
    with client.session_transaction() as session:
        assert "femag_username" not in session

    response = _login(client)

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["femag_username"] == "operador"


def test_usuario_deshabilitado_no_entra(db):
    usuario = _crear_usuario()
    usuario.active = False
    usuario.save()
    app = _app()
    client = app.test_client()

    response = _login(client)

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert "femag_username" not in session


def test_el_parte_guarda_quien_lo_cargo(db):
    _crear_usuario()
    producto, materia = _crear_productos()
    app = _app()
    client = app.test_client()
    _login(client)

    response = client.post("/produccion", data=_payload_part(producto, materia))

    assert response.status_code == 302
    part = ProductionPart.get()
    assert part.recorded_by == "operador"
    assert part.shift == "Mañana"
    assert part.production_date == date(2026, 10, 21)
    assert part.is_confirmed is False


def test_la_pantalla_muestra_el_autor_del_parte(db):
    _crear_usuario()
    producto, materia = _crear_productos()
    app = _app()
    client = app.test_client()
    _login(client)
    client.post("/produccion", data=_payload_part(producto, materia))

    response = client.get("/produccion?fecha=2026-10-21")

    assert response.status_code == 200
    assert b"operador" in response.data
    assert b"BOLSAS DE FECULA NATIVA" in response.data
    assert b"40 bolsas" in response.data


def test_confirmar_escribe_los_movimientos_de_stock(db):
    _crear_usuario()
    producto, materia = _crear_productos()
    _ingresar_materia(materia)
    app = _app()
    client = app.test_client()
    _login(client)
    client.post("/produccion", data=_payload_part(producto, materia))
    part = ProductionPart.get()

    client.post(f"/produccion/{part.id}/confirmar")

    # La confirmacion se escribe en la base: hay que releer el parte.
    part = ProductionPart.get_by_id(part.id)
    assert part.is_confirmed is True
    movimientos = list(StockMovement.select().where(StockMovement.source_ref == f"production_part:{part.id}"))
    assert len(movimientos) == 2
    tipos = sorted(movimiento.movement_type for movimiento in movimientos)
    assert tipos == [StockMovement.TYPE_PRODUCTION, StockMovement.TYPE_PRODUCTION_CONSUMPTION]
    # 40 bolsas de 25 kg entran; 1000 kg de almidon salen.
    assert StockService.balance_for(producto).balance_kg == Decimal("1000.000")
    assert StockService.balance_for(materia).balance_kg == Decimal("19000.000")


def test_confirmar_dos_veces_no_duplica_movimientos(db):
    _crear_usuario()
    producto, materia = _crear_productos()
    _ingresar_materia(materia)
    app = _app()
    client = app.test_client()
    _login(client)
    client.post("/produccion", data=_payload_part(producto, materia))
    part = ProductionPart.get()

    client.post(f"/produccion/{part.id}/confirmar")
    client.post(f"/produccion/{part.id}/confirmar")

    movimientos = list(StockMovement.select().where(StockMovement.source_ref == f"production_part:{part.id}"))
    assert len(movimientos) == 2


def test_no_se_confirma_sin_materia_prima_suficiente(db):
    _crear_usuario()
    producto, materia = _crear_productos()
    _ingresar_materia(materia, kilos="100")
    app = _app()
    client = app.test_client()
    _login(client)
    client.post("/produccion", data=_payload_part(producto, materia, kilos="1000"))
    part = ProductionPart.get()

    client.post(f"/produccion/{part.id}/confirmar")

    assert part.is_confirmed is False
    assert StockMovement.select().where(StockMovement.source_ref == f"production_part:{part.id}").count() == 0


def test_anular_un_parte_de_otro_operador_no_se_puede(db):
    _crear_usuario("operador")
    _crear_usuario("otro", profile_name="Secretaría")
    producto, materia = _crear_productos()
    app = _app()
    client = app.test_client()
    _login(client, username="operador")
    client.post("/produccion", data=_payload_part(producto, materia))
    part = ProductionPart.get()
    client.post("/logout")

    _login(client, username="otro")
    response = client.post(f"/produccion/{part.id}/anular", data={"motivo": "prueba"})

    assert response.status_code == 302
    assert part.is_voided is False


def test_el_qr_de_turno_prellena_el_turno(db):
    _crear_usuario()
    producto, materia = _crear_productos()
    app = _app()
    client = app.test_client()
    _login(client)

    response = client.get("/produccion?turno=Tarde")

    assert response.status_code == 200
    assert b'value="Tarde" selected' in response.data


def test_la_hoja_de_qr_solo_la_imprime_un_administrador(db):
    _crear_usuario("operador")
    _crear_usuario("admin", profile_name="Administrador")
    producto, materia = _crear_productos()
    app = _app()
    client = app.test_client()

    _login(client, username="operador")
    response = client.get("/produccion/turnos.pdf")
    assert response.status_code == 302

    client.post("/logout")
    _login(client, username="admin")
    response = client.get("/produccion/turnos.pdf")
    assert response.status_code == 200
    assert response.data[:4] == b"%PDF"


def test_el_esquema_agrega_la_columna_del_operario(db):
    """La base real todavia no tiene la columna: el esquema la agrega.

    Es el paso que hay que hacer en la base del cliente antes de que abran
    los puestos actualizados (``validate_runtime_schema`` corta el arranque
    del Desktop si la columna falta).
    """
    from app.config.schema import ensure_runtime_schema, validate_runtime_schema

    db.execute_sql("ALTER TABLE production_part DROP COLUMN recorded_by")
    assert "recorded_by" not in {
        column.name for column in db.get_columns("production_part")
    }

    ensure_runtime_schema(db)
    validate_runtime_schema(db)

    columns = {column.name for column in db.get_columns("production_part")}
    assert "recorded_by" in columns


def test_un_producto_sin_rol_sigue_siendo_embolsable(db):
    """Un producto sin ``stock_role`` tiene que poder embolsarse.

    En SQL ``stock_role != 'materia_prima'`` es NULL cuando ``stock_role`` es
    NULL, y un WHERE NULL descarta la fila: sin el cuidado extra, un producto
    sin rol cargado desaparecería de la lista de embolsables.
    """
    producto = Product.create(
        name="BOLSA SIN ROL CARGADO",
        unit="kg",
        peso_unitario_kg=Decimal("25.000"),
        product_kind=PRODUCT_KIND_PRODUCT,
        stock_role=None,
    )

    ids = [item.id for item in production_service.products_for_bags()]

    assert producto.id in ids


def test_la_materia_prima_no_se_ofrece_como_producto_embolsable(db):
    _crear_usuario()
    producto, materia = _crear_productos()
    app = _app()
    client = app.test_client()
    _login(client)

    response = client.get("/produccion")

    assert response.status_code == 200
    html = response.data.decode("utf-8")
    nombres_productos = _nombres_de_combo(html, "opciones-productos")
    nombres_materias = _nombres_de_combo(html, "opciones-materias")
    assert "BOLSAS DE FECULA NATIVA" in nombres_productos
    assert "ALMIDON DE MAIZ A GRANEL" not in nombres_productos
    assert "ALMIDON DE MAIZ A GRANEL" in nombres_materias


def _nombres_de_combo(html, id_script):
    """Nombres que ofrece un combo, leidos del JSON que se embebe."""
    import json

    bloque = html.split(f'id="{id_script}"')[1].split(">", 1)[1].split("</script>")[0]
    return [opcion["nombre"] for opcion in json.loads(bloque)]


def test_los_productos_se_eligen_con_un_combo_con_busqueda(db):
    """El combo es de busqueda, no una lista para deslizar.

    Es el mismo criterio que el escritorio con ``enable_combo_autocomplete``:
    se escribe y se elige de la lista, y no se puede guardar un valor escrito
    a mano.
    """
    _crear_usuario()
    producto, materia = _crear_productos()
    app = _app()
    client = app.test_client()
    _login(client)

    response = client.get("/produccion")

    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert 'class="combo-buscar"' in html
    assert 'name="product_0"' in html
    assert 'name="materia_0"' in html
    assert "opciones-productos" in html
    assert "opciones-materias" in html
    # El id va en un campo oculto: el texto escrito no alcanza para guardar.
    bloque = html.split('data-grupo="productos"')[1].split("</div>")[0]
    assert 'type="hidden"' in bloque
    assert "combo-buscar" in bloque


def test_un_producto_inexistente_no_se_guarda(db):
    """Un id que no existe no crea ninguna linea: no se puede inventar."""
    _crear_usuario()
    producto, materia = _crear_productos()
    app = _app()
    client = app.test_client()
    _login(client)

    payload = _payload_part(producto, materia)
    payload["product_0"] = "999999"
    response = client.post("/produccion", data=payload)

    assert response.status_code == 200
    assert ProductionPart.select().count() == 0
    assert b"Carg" in response.data


def test_la_seleccion_se_conserva_al_volver_a_cargar_el_formulario(db):
    """Si el alta falla, el producto elegido sigue en el formulario."""
    _crear_usuario()
    producto, materia = _crear_productos()
    app = _app()
    client = app.test_client()
    _login(client)

    payload = _payload_part(producto, materia)
    payload["kg_0"] = ""  # sin consumo: el servicio rechaza el parte
    response = client.post("/produccion", data=payload)

    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert f'value="{producto.id}"' in html
    assert "BOLSAS DE FECULA NATIVA" in html
    assert ProductionPart.select().count() == 0


def test_el_qr_de_produccion_desde_el_inicio_abre_produccion(db):
    app = _app()
    client = app.test_client()

    response = client.post("/", data={"qr": "http://femag.local:8000/produccion?turno=Tarde"})

    assert response.status_code == 302
    assert "/produccion" in response.headers["Location"]
    assert "turno=Tarde" in response.headers["Location"]
