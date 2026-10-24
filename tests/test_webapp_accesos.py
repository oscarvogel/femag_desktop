"""La pantalla de accesos para administradores (#779).

Es la forma de responder "¿quien entro al servidor y que parte cargo?" sin
reconocer el servidor de MySQL a mano. Solo la puede ver un administrador:
son datos de acceso de toda la empresa.

Las aserciones miran la referencia de la fila ("ProductionPart:N") y no el
nombre de la accion: el desplegable de filtros lista todas las acciones
que hay en la base, asi que el texto aparece siempre en la pagina.
"""

from datetime import datetime, timedelta

from app.models.audit import AuditLog
from app.services.auth_service import AuthService
from webapp import create_app


PASSWORD = "clave-de-prueba-123"
MARCA = b"ProductionPart:"


def _app():
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    return app


def _crear_usuario(username, profile_name):
    return AuthService().create_user(
        username,
        PASSWORD,
        profile_name,
        display_name=username,
        actor="test",
    )


def _login(client, username):
    return client.post("/login", data={"username": username, "password": PASSWORD})


def _evento(user, module, action, *, numero=1, workstation="10.0.0.7", momento=None):
    campos = {
        "user": user,
        "module": module,
        "action": action,
        "record_ref": f"ProductionPart:{numero}",
        "new_value": {"parte": numero},
        "workstation": workstation,
    }
    if momento is not None:
        campos["occurred_at"] = momento
    return AuditLog.create(**campos)


def test_sin_sesion_no_se_ve_la_pantalla_de_accesos(db):
    app = _app()

    response = app.test_client().get("/accesos")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_un_usuario_comun_no_puede_ver_los_accesos(db):
    _crear_usuario("operador", "Secretaría")
    _evento("oscar", "Sistema", "login exitoso")
    app = _app()
    client = app.test_client()
    _login(client, "operador")

    response = client.get("/accesos")

    assert response.status_code == 302
    assert "/produccion" in response.headers["Location"]
    # Y no le filtro ninguna fila.
    assert MARCA not in response.data


def test_el_administrador_ve_los_accesos(db):
    _crear_usuario("admin", "Administrador")
    _evento("admin", "Sistema", "login exitoso")
    app = _app()
    client = app.test_client()
    _login(client, "admin")

    response = client.get("/accesos")

    assert response.status_code == 200
    assert b"Accesos" in response.data
    assert MARCA in response.data
    # De que equipo entro: en la webapp es la IP del celular.
    assert b"10.0.0.7" in response.data


def test_el_enlace_de_accesos_solo_sale_para_administradores(db):
    _crear_usuario("operador", "Secretaría")
    _crear_usuario("admin", "Administrador")
    app = _app()

    comun = app.test_client()
    _login(comun, "operador")
    assert b"Accesos" not in comun.get("/produccion").data

    admin = app.test_client()
    _login(admin, "admin")
    assert b"Accesos" in admin.get("/produccion").data


def test_los_filtros_de_la_pantalla_accesos(db):
    _crear_usuario("admin", "Administrador")
    _evento("oscar", "Sistema", "login exitoso", numero=1)
    _evento("maria", "Produccion", "carga de parte", numero=2)
    app = _app()
    client = app.test_client()
    _login(client, "admin")

    por_usuario = client.get("/accesos?usuario=maria")
    assert b"ProductionPart:2" in por_usuario.data
    assert b"ProductionPart:1" not in por_usuario.data

    por_modulo = client.get("/accesos?modulo=Produccion")
    assert b"ProductionPart:2" in por_modulo.data
    assert b"ProductionPart:1" not in por_modulo.data

    por_accion = client.get("/accesos?accion=carga%20de%20parte")
    assert b"ProductionPart:2" in por_accion.data
    assert b"ProductionPart:1" not in por_accion.data

    por_referencia = client.get("/accesos?referencia=ProductionPart:1")
    assert b"ProductionPart:1" in por_referencia.data
    assert b"ProductionPart:2" not in por_referencia.data


def test_la_pantalla_de_accesos_pagina(db):
    _crear_usuario("admin", "Administrador")
    app = _app()
    client = app.test_client()
    _login(client, "admin")
    # Los eventos van despues del ingreso: asi la primera pagina son los mas
    # recientes y la paginacion no depende de las filas del propio ingreso.
    for numero in range(1, 61):
        _evento("admin", "Sistema", "login exitoso", numero=numero)

    primera = client.get("/accesos")
    assert primera.status_code == 200
    # 50 filas por pagina, y son las mas recientes.
    assert primera.data.count(MARCA) == 50
    assert b"ProductionPart:60" in primera.data
    assert b"ProductionPart:10" not in primera.data

    segunda = client.get("/accesos?pagina=1")
    assert segunda.status_code == 200
    assert segunda.data.count(MARCA) == 10
    assert b"ProductionPart:10" in segunda.data
    assert b"ProductionPart:60" not in segunda.data


def test_el_rango_de_fechas_filtra(db):
    _crear_usuario("admin", "Administrador")
    _evento("admin", "Sistema", "login exitoso", momento=datetime(2026, 10, 21, 10, 0))
    app = _app()
    client = app.test_client()
    _login(client, "admin")

    dentro = client.get("/accesos?desde=2026-10-21&hasta=2026-10-21")
    assert MARCA in dentro.data

    fuera = client.get("/accesos?desde=2026-10-22&hasta=2026-10-23")
    assert MARCA not in fuera.data
