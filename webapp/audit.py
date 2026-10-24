"""Registro de auditoría de la webapp (#778).

La webapp se usa desde el celular de la planta, donde varias personas se
pasan el mismo equipo y a veces la misma clave. Sin registro, un parte
cargado por error no tiene dueño y no hay forma de saber que pasó en el
turno ni desde que equipo se entro.

Escribe en la misma tabla ``AuditLog`` que usa el escritorio, para que la
pantalla de accesos (#779) muestre los dos origenes juntos y se pueda
distinguir por el puesto: la IP del celular en la webapp, el nombre de la
maquina en el escritorio.
"""

from __future__ import annotations

import logging
import socket

from flask import has_request_context, request

from app.models.audit import AuditLog


#: Los mismos modulos que usa el escritorio, para que los filtros de la
#: pantalla de accesos no tengan que distinguir el origen.
MODULE_SISTEMA = "Sistema"
MODULE_PRODUCCION = "Produccion"

#: Accesos. "login exitoso" y "login fallido" los escribe ``AuthService``;
#: la salida la escribe esta webapp porque el escritorio no la necesita.
ACTION_INGRESO = "login exitoso"
ACTION_SALIDA = "salida"

#: Carga de partes desde el celular.
ACTION_CARGA = "carga de parte"
ACTION_CONFIRMACION = "confirmacion de parte"
ACTION_ANULACION = "anulacion de parte"

logger = logging.getLogger("femag.webapp.audit")


def client_station() -> str:
    """De donde viene la peticion: la IP del celular en la planta.

    Es el dato que dice que equipo entro. Sin peticion (por ejemplo, una
    tarea programada) se usa el nombre de la maquina, como en el escritorio.
    """
    if has_request_context():
        address = (request.remote_addr or "").strip()
        if address:
            return address
    return socket.gethostname()


def record(
    *,
    user: str | None,
    module: str,
    action: str,
    record_ref: str | None = None,
    new_value: dict | None = None,
    observation: str | None = None,
) -> None:
    """Escribe una fila de auditoría sin romper la operación.

    Si la auditoría falla, el parte tiene que estar igual cargado: el
    problema se ve en el log del servidor, no en el celular del operario.
    """
    try:
        AuditLog.create(
            user=(user or None),
            module=module,
            action=action,
            record_ref=record_ref,
            old_value=None,
            new_value=new_value,
            observation=observation,
            workstation=client_station(),
        )
    except Exception:
        logger.exception(
            "No se pudo registrar el evento de auditoría %s/%s", module, action
        )


def record_exit(user: str | None) -> None:
    """Deja la salida de la webapp registrada."""
    if not user:
        return
    record(user=user, module=MODULE_SISTEMA, action=ACTION_SALIDA)
