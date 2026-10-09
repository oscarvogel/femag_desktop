"""Regresión: el auditor debe resolver la MISMA conexión que `app.main --ui`.

En una PC normal de FEMAG el `.env` del repo puede quedar apuntando a la demo
SQLite (``FEMAG_DB_ENGINE=sqlite``, ``FEMAG_DEMO=1``), pero la app NO usa esa
base: ``app.main.run_ui()`` detecta que existe configuración segura del puesto
(DPAPI) y fuerza MySQL antes de llamar a ``load_settings()``.

Si el auditor no replica ese preámbulo, audita ``femag_demo.sqlite3`` en
silencio y el operador cree que auditó producción.

Invariantes:

1. La configuración normal de FEMAG = MySQL ⇒ el auditor usa MySQL.
2. Se abre con ``ReadOnlyMySQLDatabase``, nunca con ``FemagMySQLDatabase``.
3. No se ejecuta ``ensure_runtime_schema()`` ni la siembra de medios de pago.
4. Si MySQL no se puede resolver o abrir, el auditor FALLA. No cae a SQLite.
5. La contraseña jamás se imprime.
"""

import pytest
from peewee import OperationalError

from app.config import secure_credentials
from app.config.database import FemagMySQLDatabase
from app.services.monetary_audit_readonly import (
    EffectiveConfigurationError,
    ReadOnlyMySQLDatabase,
    open_audit_database,
    resolve_audit_database,
)


CONEXION_MYSQL = secure_credentials.RuntimeConnection(
    host="10.20.30.40",
    port=3307,
    database="femag",
    user="femag_app",
    password="clave-secreta-no-imprimir",
)


@pytest.fixture()
def mysql_normal(monkeypatch):
    """Configuración normal de FEMAG en un puesto: `.env` demo + DPAPI MySQL."""
    monkeypatch.setenv("FEMAG_DEMO", "1")
    monkeypatch.setenv("FEMAG_DB_ENGINE", "sqlite")
    monkeypatch.setenv("FEMAG_SQLITE_PATH", "femag_demo.sqlite3")
    monkeypatch.setenv("FEMAG_SECURE_CONFIG", "0")
    monkeypatch.setattr(
        secure_credentials, "has_runtime_configuration", lambda config_dir=None: True
    )
    monkeypatch.setattr(
        secure_credentials,
        "load_runtime_connection",
        lambda config_dir=None: CONEXION_MYSQL,
    )
    return CONEXION_MYSQL


@pytest.fixture()
def sin_configuracion_segura(monkeypatch):
    """Puesto sin configuración segura: la configuración efectiva manda."""
    monkeypatch.setenv("FEMAG_DEMO", "0")
    monkeypatch.setenv("FEMAG_DB_ENGINE", "sqlite")
    monkeypatch.setenv("FEMAG_SQLITE_PATH", "femag_demo.sqlite3")
    monkeypatch.setenv("FEMAG_SECURE_CONFIG", "0")
    monkeypatch.setattr(
        secure_credentials, "has_runtime_configuration", lambda config_dir=None: False
    )
    return secure_credentials


def _no_conectar(monkeypatch):
    """Evita cualquier conexión MySQL real durante el test."""
    monkeypatch.setattr(
        ReadOnlyMySQLDatabase,
        "connect",
        lambda self, *args, **kwargs: True,
    )


def _reventar_si_se_usa(nombre):
    def _boom(*args, **kwargs):
        raise AssertionError(f"No se debe llamar a {nombre}.")

    return _boom


# ---------------------------------------------------------------------------
# 1) La configuración normal de FEMAG resuelve MySQL
# ---------------------------------------------------------------------------


def test_la_configuracion_normal_de_femag_resuelve_mysql_aunque_el_env_diga_sqlite(
    mysql_normal,
):
    target = resolve_audit_database()

    assert target.engine == "mysql"
    assert target.secure_config is True
    assert target.host == "10.20.30.40"
    assert target.port == 3307
    assert target.database == "femag"
    assert target.user == "femag_app"
    assert target.password == "clave-secreta-no-imprimir"
    assert target.sqlite_path is None


def test_el_ambiente_se_deja_como_lo_deja_la_app(mysql_normal):
    resolve_audit_database()

    import os

    assert os.environ["FEMAG_SECURE_CONFIG"] == "1"
    assert os.environ["FEMAG_DB_ENGINE"] == "mysql"
    assert os.environ["FEMAG_DEMO"] == "0"


def test_el_preambulo_es_el_mismo_que_usa_la_app(mysql_normal):
    """``run_ui`` y el auditor comparten la resolución; no hay dos copias.

    Comprobación estática: importar ``app.main`` requiere PyQt y ``truststore``
    (no disponibles en todos los entornos), pero la regla que importa es que el
    preámbulo de conexión viva en un solo lugar.
    """
    from app.config.settings import resolve_effective_connection_settings
    from pathlib import Path

    main_source = Path("app/main.py").read_text(encoding="utf-8")

    assert "resolve_effective_connection_settings" in main_source
    assert 'os.environ["FEMAG_SECURE_CONFIG"] = "1"' not in main_source
    assert resolve_effective_connection_settings(demo_mode=False, configure=False) is True
    assert resolve_effective_connection_settings(demo_mode=True, configure=False) is False


# ---------------------------------------------------------------------------
# 2) Se abre con ReadOnlyMySQLDatabase, sin tocar el esquema
# ---------------------------------------------------------------------------


def test_el_auditor_abre_readonlymysql_y_no_femagmysql(mysql_normal, monkeypatch):
    _no_conectar(monkeypatch)
    monkeypatch.setattr(
        "app.config.schema.ensure_runtime_schema", _reventar_si_se_usa("ensure_runtime_schema")
    )
    monkeypatch.setattr(
        "app.services.client_payment_service.ClientPaymentService.ensure_default_payment_methods",
        _reventar_si_se_usa("ensure_default_payment_methods"),
    )

    handle = open_audit_database()

    assert isinstance(handle.database, ReadOnlyMySQLDatabase)
    assert not isinstance(handle.database, FemagMySQLDatabase)
    assert handle.database.database == "femag"
    assert handle.database.connect_params["host"] == "10.20.30.40"
    assert handle.database.connect_params["port"] == 3307
    assert handle.database.connect_params["user"] == "femag_app"
    assert handle.database.connect_params["password"] == CONEXION_MYSQL.password
    assert "sql_allowlist_guard" in handle.protections


def test_el_auditor_no_abre_nunca_femagmysql(mysql_normal, monkeypatch):
    """Ni la resolución ni la apertura pueden construir el conector que migra."""
    _no_conectar(monkeypatch)
    monkeypatch.setattr(
        secure_credentials, "load_runtime_connection", lambda config_dir=None: CONEXION_MYSQL
    )

    created = []
    original_init = FemagMySQLDatabase.__init__

    def _spy(self, *args, **kwargs):
        created.append(args)
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(FemagMySQLDatabase, "__init__", _spy)
    open_audit_database()

    assert created == []


# ---------------------------------------------------------------------------
# 3) Si MySQL falla, falla. Nunca cae a SQLite.
# ---------------------------------------------------------------------------


def test_si_mysql_no_abre_no_cae_a_sqlite(mysql_normal, monkeypatch):
    def _fallar_conexion(self, *args, **kwargs):
        raise OperationalError(
            "Can't connect to MySQL server on '10.20.30.40' (110)"
        )

    monkeypatch.setattr(ReadOnlyMySQLDatabase, "connect", _fallar_conexion)
    monkeypatch.setattr(
        "app.services.monetary_audit_readonly.open_readonly_sqlite",
        _reventar_si_se_usa("open_readonly_sqlite"),
    )

    with pytest.raises(OperationalError):
        open_audit_database()


def test_si_no_se_puede_resolver_la_credencial_falla_explicitamente(monkeypatch):
    monkeypatch.setenv("FEMAG_DEMO", "1")
    monkeypatch.setenv("FEMAG_DB_ENGINE", "sqlite")
    monkeypatch.setenv("FEMAG_SECURE_CONFIG", "0")
    monkeypatch.setattr(
        secure_credentials, "has_runtime_configuration", lambda config_dir=None: True
    )

    def _sin_credencial(config_dir=None):
        raise secure_credentials.SecureConfigurationError(
            "La conexion MySQL todavia no esta configurada en este puesto."
        )

    monkeypatch.setattr(secure_credentials, "load_runtime_connection", _sin_credencial)

    with pytest.raises(secure_credentials.SecureConfigurationError):
        resolve_audit_database()


def test_la_configuracion_segura_no_puede_terminar_en_sqlite(mysql_normal, monkeypatch):
    """Contradicción imposible: si hay config segura, el motor es MySQL."""
    import app.config.settings as settings_module

    real_load = settings_module.load_settings

    def _mintiendo():
        from dataclasses import replace

        return replace(real_load(), db_engine="sqlite")

    monkeypatch.setattr(settings_module, "load_settings", _mintiendo)

    with pytest.raises(EffectiveConfigurationError):
        resolve_audit_database()


def test_el_cli_falla_explicitamente_y_no_imprime_la_password(mysql_normal, monkeypatch, capsys):
    from scripts.audit_monetary_integrity import main

    def _fallar_conexion(self, *args, **kwargs):
        raise OperationalError("Can't connect to MySQL server on '10.20.30.40' (110)")

    monkeypatch.setattr(ReadOnlyMySQLDatabase, "connect", _fallar_conexion)
    monkeypatch.setattr(
        "app.services.monetary_audit_readonly.open_readonly_sqlite",
        _reventar_si_se_usa("open_readonly_sqlite"),
    )

    assert main(["--budget-number", "73"]) == 2

    capturado = capsys.readouterr()
    assert "Database engine: MySQL" in capturado.out
    assert "Host: 10.20.30.40" in capturado.out
    assert "Can't connect to MySQL server" in capturado.err
    assert "femag_demo.sqlite3" not in capturado.out + capturado.err
    assert CONEXION_MYSQL.password not in capturado.out + capturado.err


# ---------------------------------------------------------------------------
# 4) Encabezado: qué conexión se audita, sin contraseña
# ---------------------------------------------------------------------------


def test_el_encabezado_informa_la_conexion_sin_la_password(mysql_normal):
    target = resolve_audit_database()

    encabezado = "\n".join(target.header_lines())

    assert "Database engine: MySQL" in encabezado
    assert "Host: 10.20.30.40" in encabezado
    assert "Port: 3307" in encabezado
    assert "Database: femag" in encabezado
    assert "User: femag_app" in encabezado
    assert "clave-secreta-no-imprimir" not in encabezado
    assert "femag_app:clave" not in encabezado


def test_el_repr_del_objetivo_tambien_oculta_la_password(mysql_normal):
    target = resolve_audit_database()

    assert CONEXION_MYSQL.password not in repr(target)
    assert "host='10.20.30.40'" in repr(target)


# ---------------------------------------------------------------------------
# 5) SQLite sólo cuando la configuración efectiva lo indica
# ---------------------------------------------------------------------------


def test_sqlite_solo_cuando_la_configuracion_efectiva_lo_indica(sin_configuracion_segura):
    target = resolve_audit_database()

    assert target.engine == "sqlite"
    assert target.secure_config is False
    assert target.sqlite_path is not None
    assert str(target.sqlite_path) == "femag_demo.sqlite3"
    assert target.host is None
    assert target.user is None


def test_con_configuracion_segura_nunca_habilita_sqlite(mysql_normal):
    """Aunque el entorno diga SQLite, la config segura del puesto manda."""
    import os

    assert os.environ["FEMAG_DB_ENGINE"] == "sqlite"
    assert os.environ["FEMAG_DEMO"] == "1"

    target = resolve_audit_database()

    assert target.engine == "mysql"
    assert target.sqlite_path is None
