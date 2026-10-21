"""Autenticacion de la webapp movil (#754).

La webapp se usa desde el celular de la planta, donde pueden embolsar varias
personas. Por eso la captura de produccion pide usuario y clave: el parte
tiene que quedar a nombre de quien lo cargo.

Los usuarios son **los mismos** que usa FEMAG Desktop (``app.models.security.User``),
validados con ``AuthService``: no hay un segundo juego de credenciales que
mantener ni sincronizar.

El secreto de la sesion se resuelve en este orden:

1. ``FEMAG_WEB_SECRET_KEY`` (entorno), para despliegues que lo injectan.
2. Un archivo en el directorio de configuracion del puesto, si ya existe.
3. Uno nuevo, aleatorio, guardado en ese mismo directorio.

No se usa un secreto fijo en el codigo: con la clave escrita en el repositorio
cualquiera que conozca el repositorio podria firmar una cookie de sesion
inventada y entrar como otro usuario.
"""

from __future__ import annotations

import os
import secrets
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import flash, redirect, request, session, url_for

from app.models.security import User
from app.services.auth_service import AuthService

SESSION_USER_KEY = "femag_username"

#: La sesion vive lo que dura un turno de trabajo: el mismo celular no vuelve
#: a pedir la clave a la manana, pero a la noche ya esta cerrada.
SESSION_LIFETIME = timedelta(hours=12)

SECRET_FILE_NAME = "webapp_secret.key"


def _secret_path() -> Path:
    configured = os.getenv("FEMAG_WEB_SECRET_FILE", "").strip()
    if configured:
        return Path(configured)
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        base = Path(local_app_data) / "FEMAG Desktop"
    else:
        config_home = os.getenv("XDG_CONFIG_HOME", "").strip()
        base = (Path(config_home) if config_home else Path.home() / ".config") / "FEMAG Desktop"
    return base / SECRET_FILE_NAME


def resolve_secret_key() -> str:
    """Devuelve el secreto de sesion, creandolo la primera vez si hace falta."""
    configured = os.getenv("FEMAG_WEB_SECRET_KEY", "").strip()
    if configured:
        return configured

    path = _secret_path()
    try:
        if path.is_file():
            stored = path.read_text(encoding="utf-8").strip()
            if stored:
                return stored
    except OSError:
        pass

    value = secrets.token_urlsafe(48)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    except OSError:
        # Si no se puede guardar, el secreto cambia en cada arranque: se caen
        # las sesiones abiertas, pero no queda una clave conocida en el disco.
        pass
    return value


def login_user(username: str, password: str) -> bool:
    """Valida las credenciales contra los usuarios de FEMAG Desktop."""
    user = AuthService().authenticate(username, password)
    if user is None:
        return False
    session.clear()
    session[SESSION_USER_KEY] = user.username
    session.permanent = True
    return True


def logout_user() -> None:
    session.clear()


def current_username() -> str | None:
    username = session.get(SESSION_USER_KEY)
    return username if isinstance(username, str) and username else None


def is_administrator() -> bool:
    """True si el usuario de la sesion es administrador.

    Se usa para lo que es de la casa y no del turno: imprimir la hoja de QR de
    la planta, por ejemplo.
    """
    username = current_username()
    if not username:
        return False
    user = User.get_or_none((User.username == username) & (User.active == True))  # noqa: E712
    if user is None:
        return False
    return (user.profile.name or "").strip().lower() == "administrador"


def _internal_target() -> str:
    """El camino interno de la peticion actual, con su query string."""
    target = request.full_path
    if target.endswith("?"):
        target = target[:-1]
    return target


def _safe_next(target: str | None) -> str | None:
    """Solo destinos internos: un ``next`` con host ajeno es una redireccion
    abierta y no debe aceptarse."""
    if not target:
        return None
    if not target.startswith("/") or target.startswith("//"):
        return None
    return target


def login_required(view):
    """Exige sesion iniciada y, si no hay, manda al login."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_username():
            flash("Iniciá sesión para registrar producción.", "error")
            return redirect(url_for("login", next=_internal_target()))
        return view(*args, **kwargs)

    return wrapped


def redirect_after_login(default_endpoint: str = "home") -> str:
    target = _safe_next(request.args.get("next"))
    return target or url_for(default_endpoint)
