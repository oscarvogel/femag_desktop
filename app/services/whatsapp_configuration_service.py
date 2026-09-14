from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import load_settings
from app.models.system import AppParameter


class CentralConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class WhatsAppCentralConfiguration:
    api_url: str
    api_key: str
    timeout_seconds: float = 15.0
    enabled: bool = True

    def validate(self) -> None:
        parsed_url = urlparse((self.api_url or "").strip())
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("Ingrese una URL válida para el gateway de WhatsApp.")
        if not 1 <= float(self.timeout_seconds) <= 120:
            raise ValueError("El tiempo de espera debe estar entre 1 y 120 segundos.")
        if self.enabled and not self.api_key:
            raise ValueError("Ingrese la API key de WhatsApp.")


class WhatsAppCentralConfigurationService:
    PREFIX = "whatsapp."
    ENABLED_KEY = PREFIX + "enabled"
    API_URL_KEY = PREFIX + "api_url"
    API_KEY_KEY = PREFIX + "api_key_encrypted"
    TIMEOUT_KEY = PREFIX + "api_timeout"
    FORMAT_KEY = PREFIX + "secret_format"
    SECRET_FORMAT = "fernet-db-password-v1"
    _KDF_SALT = b"FEMAG Desktop WhatsApp central configuration v1"

    @staticmethod
    def _get(key: str) -> str | None:
        row = AppParameter.get_or_none(AppParameter.key == key)
        return row.value if row else None

    @staticmethod
    def _set(key: str, value: str | None) -> None:
        row, _ = AppParameter.get_or_create(key=key)
        row.value = value
        row.save()

    @classmethod
    def is_configured(cls) -> bool:
        return bool(cls._get(cls.API_URL_KEY) and cls._get(cls.API_KEY_KEY))

    @classmethod
    def _fernet(cls) -> Fernet:
        settings = load_settings()
        secret = settings.db_password
        if not secret:
            if settings.db_engine == "sqlite":
                # Sólo para demo/tests. Producción MySQL exige contraseña.
                secret = f"sqlite-demo:{settings.sqlite_path}"
            else:
                raise CentralConfigurationError(
                    "No se puede proteger la API key porque la conexión MySQL no tiene contraseña."
                )
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            secret.encode("utf-8"),
            cls._KDF_SALT,
            200_000,
            dklen=32,
        )
        return Fernet(base64.urlsafe_b64encode(derived))

    @classmethod
    def _encrypt(cls, value: str) -> str:
        return cls._fernet().encrypt(value.encode("utf-8")).decode("ascii")

    @classmethod
    def _decrypt(cls, value: str) -> str:
        try:
            return cls._fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
            raise CentralConfigurationError(
                "No se pudo recuperar la API key central. Si cambió la contraseña MySQL, vuelva a cargar la API key."
            ) from exc

    @classmethod
    def load(cls) -> WhatsAppCentralConfiguration | None:
        if not cls.is_configured():
            return None
        encrypted = cls._get(cls.API_KEY_KEY) or ""
        secret_format = cls._get(cls.FORMAT_KEY)
        if secret_format not in {None, cls.SECRET_FORMAT}:
            raise CentralConfigurationError("Formato de credencial WhatsApp no soportado.")
        try:
            timeout = float(cls._get(cls.TIMEOUT_KEY) or "15")
        except ValueError as exc:
            raise CentralConfigurationError("El timeout de WhatsApp guardado no es válido.") from exc
        configuration = WhatsAppCentralConfiguration(
            api_url=(cls._get(cls.API_URL_KEY) or "").strip().rstrip("/"),
            api_key=cls._decrypt(encrypted),
            timeout_seconds=timeout,
            enabled=(cls._get(cls.ENABLED_KEY) or "true").strip().lower()
            in {"1", "true", "yes", "si", "sí", "on"},
        )
        configuration.validate()
        return configuration

    @classmethod
    def save(cls, configuration: WhatsAppCentralConfiguration) -> None:
        configuration.validate()
        cls._set(cls.ENABLED_KEY, "true" if configuration.enabled else "false")
        cls._set(cls.API_URL_KEY, configuration.api_url.strip().rstrip("/"))
        cls._set(cls.TIMEOUT_KEY, str(float(configuration.timeout_seconds)))
        cls._set(cls.API_KEY_KEY, cls._encrypt(configuration.api_key))
        cls._set(cls.FORMAT_KEY, cls.SECRET_FORMAT)
