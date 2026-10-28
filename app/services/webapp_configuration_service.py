"""Configuracion del servidor web que abre las ordenes desde el celular (#801).

La URL base se guarda en ``AppParameter`` para que la compartan todos los
puestos: es una propiedad del servidor, no de la maquina que imprime. El QR de
la orden se arma con esa base y el token existente, sin tocar la base ni los
tokens historicos.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.models.system import AppParameter


class WebappConfigurationError(ValueError):
    pass


def normalize_public_url(value: str) -> str:
    """Valida y normaliza la URL base del servidor web.

    Solo se acepta ``http://`` o ``https://`` con host y puerto opcional. No se
    permiten credenciales, rutas, query ni fragmentos: la base se concatena con
    ``/orden/<token>`` y cualquier ruta sobrante romperia esa union.
    """
    raw = (value or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise WebappConfigurationError(
            "La URL del servidor debe empezar con http:// o https://."
        )
    if not parsed.hostname:
        raise WebappConfigurationError("La URL del servidor no tiene un host valido.")
    if parsed.username or parsed.password:
        raise WebappConfigurationError("La URL del servidor no debe incluir usuario ni clave.")
    if parsed.path not in {"", "/"}:
        raise WebappConfigurationError(
            "La URL del servidor no debe incluir una ruta; solo el host y el puerto."
        )
    if parsed.params or parsed.query or parsed.fragment:
        raise WebappConfigurationError(
            "La URL del servidor no debe incluir parametros, consulta ni fragmentos."
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise WebappConfigurationError("El puerto de la URL no es valido.") from exc
    if port is not None and not 1 <= port <= 65535:
        raise WebappConfigurationError("El puerto debe estar entre 1 y 65535.")

    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


class WebappConfigurationService:
    PUBLIC_URL_KEY = "webapp.public_url"

    @classmethod
    def public_url(cls) -> str:
        row = AppParameter.get_or_none(AppParameter.key == cls.PUBLIC_URL_KEY)
        return (row.value or "").strip().rstrip("/") if row else ""

    @classmethod
    def is_configured(cls) -> bool:
        return bool(cls.public_url())

    @classmethod
    def save_public_url(cls, value: str) -> str:
        normalized = normalize_public_url(value)
        row, _created = AppParameter.get_or_create(key=cls.PUBLIC_URL_KEY)
        row.value = normalized
        row.save(only=[AppParameter.value])
        return normalized

    @classmethod
    def order_url(cls, token: str) -> str:
        base = cls.public_url()
        if not base:
            return ""
        return f"{base}/orden/{token}"
