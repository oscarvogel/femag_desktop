from __future__ import annotations

import ctypes
import json
import os
from urllib.parse import urlparse
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


APP_DIR_NAME = "FEMAG Desktop"
CONFIG_FILE_NAME = "connection.json"
CREDENTIAL_FILE_NAME = "connection.credential"
WHATSAPP_CONFIG_FILE_NAME = "whatsapp.json"
WHATSAPP_CREDENTIAL_FILE_NAME = "whatsapp.credential"
CRYPTPROTECT_UI_FORBIDDEN = 0x01


class SecureConfigurationError(RuntimeError):
    """Raised when the local connection configuration cannot be used."""


@dataclass(frozen=True)
class RuntimeConnection:
    host: str
    port: int
    database: str
    user: str
    password: str

    def validate(self) -> None:
        if not self.host.strip():
            raise ValueError("Ingrese el servidor MySQL.")
        if not 1 <= self.port <= 65535:
            raise ValueError("El puerto MySQL debe estar entre 1 y 65535.")
        if not self.database.strip():
            raise ValueError("Ingrese el nombre de la base de datos.")
        if not self.user.strip():
            raise ValueError("Ingrese el usuario MySQL.")
        if not self.password:
            raise ValueError("Ingrese la contrasena MySQL.")


@dataclass(frozen=True)
class RuntimeWhatsAppConfiguration:
    api_url: str
    api_key: str
    instance_id: str = "default"
    timeout_seconds: float = 15.0
    enabled: bool = True

    def validate(self) -> None:
        parsed_url = urlparse(self.api_url.strip())
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("Ingrese una URL válida para el gateway de WhatsApp.")
        if not self.instance_id.strip():
            raise ValueError("Ingrese la instancia de WhatsApp.")
        if not 1 <= float(self.timeout_seconds) <= 120:
            raise ValueError("El tiempo de espera debe estar entre 1 y 120 segundos.")
        if self.enabled and not self.api_key:
            raise ValueError("Ingrese la API key de WhatsApp.")


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def default_config_dir() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / APP_DIR_NAME


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect_password(password: str) -> bytes:
    if os.name != "nt":
        raise SecureConfigurationError("El almacenamiento seguro de credenciales requiere Windows.")
    source, source_buffer = _blob(password.encode("utf-8"))
    target = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "FEMAG Desktop MySQL",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(target),
    ):
        raise SecureConfigurationError("Windows no pudo cifrar la contrasena MySQL.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)
        ctypes.memset(source_buffer, 0, len(source_buffer))


def unprotect_password(encrypted: bytes) -> str:
    if os.name != "nt":
        raise SecureConfigurationError("El almacenamiento seguro de credenciales requiere Windows.")
    source, source_buffer = _blob(encrypted)
    target = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(target)
    ):
        raise SecureConfigurationError(
            "No se pudo recuperar la contrasena guardada. Vuelva a configurar la conexion."
        )
    try:
        return ctypes.string_at(target.pbData, target.cbData).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecureConfigurationError("La credencial local no es valida.") from exc
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)
        ctypes.memset(source_buffer, 0, len(source_buffer))


def protect_secret(value: str, *, description: str) -> bytes:
    if os.name != "nt":
        raise SecureConfigurationError("El almacenamiento seguro de credenciales requiere Windows.")
    source, source_buffer = _blob(value.encode("utf-8"))
    target = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        description,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(target),
    ):
        raise SecureConfigurationError("Windows no pudo cifrar la credencial de WhatsApp.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)
        ctypes.memset(source_buffer, 0, len(source_buffer))


def unprotect_secret(encrypted: bytes) -> str:
    if os.name != "nt":
        raise SecureConfigurationError("El almacenamiento seguro de credenciales requiere Windows.")
    source, source_buffer = _blob(encrypted)
    target = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(target)
    ):
        raise SecureConfigurationError(
            "No se pudo recuperar la API key guardada. Vuelva a configurar WhatsApp."
        )
    try:
        return ctypes.string_at(target.pbData, target.cbData).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecureConfigurationError("La credencial local de WhatsApp no es válida.") from exc
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)
        ctypes.memset(source_buffer, 0, len(source_buffer))


def save_runtime_connection(connection: RuntimeConnection, config_dir: Path | None = None) -> None:
    connection.validate()
    target_dir = config_dir or default_config_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    encrypted = protect_password(connection.password)
    config = {
        "version": 1,
        "host": connection.host.strip(),
        "port": connection.port,
        "database": connection.database.strip(),
        "user": connection.user.strip(),
    }
    credential_tmp = target_dir / f"{CREDENTIAL_FILE_NAME}.tmp"
    config_tmp = target_dir / f"{CONFIG_FILE_NAME}.tmp"
    credential_tmp.write_bytes(encrypted)
    config_tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(credential_tmp, target_dir / CREDENTIAL_FILE_NAME)
    os.replace(config_tmp, target_dir / CONFIG_FILE_NAME)


def load_runtime_connection(config_dir: Path | None = None) -> RuntimeConnection:
    target_dir = config_dir or default_config_dir()
    try:
        config = json.loads((target_dir / CONFIG_FILE_NAME).read_text(encoding="utf-8"))
        encrypted = (target_dir / CREDENTIAL_FILE_NAME).read_bytes()
        connection = RuntimeConnection(
            host=str(config["host"]),
            port=int(config["port"]),
            database=str(config["database"]),
            user=str(config["user"]),
            password=unprotect_password(encrypted),
        )
        connection.validate()
        return connection
    except SecureConfigurationError:
        raise
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SecureConfigurationError("La conexion MySQL todavia no esta configurada en este puesto.") from exc


def has_runtime_configuration(config_dir: Path | None = None) -> bool:
    target_dir = config_dir or default_config_dir()
    return (target_dir / CONFIG_FILE_NAME).is_file() and (
        target_dir / CREDENTIAL_FILE_NAME
    ).is_file()


def save_runtime_whatsapp_configuration(
    configuration: RuntimeWhatsAppConfiguration, config_dir: Path | None = None
) -> None:
    configuration.validate()
    target_dir = config_dir or default_config_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    encrypted = protect_secret(configuration.api_key, description="FEMAG Desktop WhatsApp API key")
    config = {
        "version": 1,
        "enabled": configuration.enabled,
        "api_url": configuration.api_url.strip().rstrip("/"),
        "instance_id": configuration.instance_id.strip(),
        "timeout_seconds": float(configuration.timeout_seconds),
    }
    credential_tmp = target_dir / f"{WHATSAPP_CREDENTIAL_FILE_NAME}.tmp"
    config_tmp = target_dir / f"{WHATSAPP_CONFIG_FILE_NAME}.tmp"
    credential_tmp.write_bytes(encrypted)
    config_tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(credential_tmp, target_dir / WHATSAPP_CREDENTIAL_FILE_NAME)
    os.replace(config_tmp, target_dir / WHATSAPP_CONFIG_FILE_NAME)


def load_runtime_whatsapp_configuration(
    config_dir: Path | None = None,
) -> RuntimeWhatsAppConfiguration:
    target_dir = config_dir or default_config_dir()
    try:
        config = json.loads((target_dir / WHATSAPP_CONFIG_FILE_NAME).read_text(encoding="utf-8"))
        encrypted = (target_dir / WHATSAPP_CREDENTIAL_FILE_NAME).read_bytes()
        configuration = RuntimeWhatsAppConfiguration(
            api_url=str(config["api_url"]),
            api_key=unprotect_secret(encrypted),
            instance_id=str(config["instance_id"]),
            timeout_seconds=float(config["timeout_seconds"]),
            enabled=bool(config["enabled"]),
        )
        configuration.validate()
        return configuration
    except SecureConfigurationError:
        raise
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SecureConfigurationError("WhatsApp todavía no está configurado en este puesto.") from exc


def has_runtime_whatsapp_configuration(config_dir: Path | None = None) -> bool:
    target_dir = config_dir or default_config_dir()
    return (target_dir / WHATSAPP_CONFIG_FILE_NAME).is_file() and (
        target_dir / WHATSAPP_CREDENTIAL_FILE_NAME
    ).is_file()
