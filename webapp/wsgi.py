"""Entrada WSGI para contenedores (#803).

Gunicorn importa este modulo en cada worker. Aca se prepara la conexion y se
valida el esquema antes de atender trafico: si la base no esta lista, el
contenedor falla al arrancar en vez de responder errores 500 en cada request.
"""

from __future__ import annotations

import os

from app.config.database import initialize_runtime_database
from app.config.schema import validate_runtime_schema
from webapp import create_app

_database = initialize_runtime_database()

if os.getenv("FEMAG_WEB_VALIDATE_SCHEMA", "1") != "0":
    validate_runtime_schema(_database)

app = create_app()
