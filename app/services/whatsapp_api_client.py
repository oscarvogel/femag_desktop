from __future__ import annotations

import json
import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from peewee import DatabaseError

from app.config.settings import load_settings


TERMINAL_STATUSES = {"delivered", "read", "failed"}


class WhatsAppApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class WhatsAppApiConfig:
    base_url: str
    api_key: str
    instance_id: str | None = None
    timeout_seconds: float = 15.0
    enabled: bool = True

    @classmethod
    def from_settings(cls) -> "WhatsAppApiConfig":
        from app.config.database import database_proxy
        from app.services.whatsapp_configuration_service import WhatsAppCentralConfigurationService

        if database_proxy.obj is not None:
            try:
                central = WhatsAppCentralConfigurationService.load()
            except DatabaseError:
                central = None
            if central is not None:
                return cls(
                    base_url=central.api_url,
                    api_key=central.api_key,
                    instance_id=None,
                    timeout_seconds=central.timeout_seconds,
                    enabled=central.enabled,
                )

        # Compatibilidad transitoria con instalaciones que aún conservan
        # configuración local previa al issue #416.
        from app.config.secure_credentials import (
            has_runtime_whatsapp_configuration,
            load_runtime_whatsapp_configuration,
        )

        if has_runtime_whatsapp_configuration():
            runtime_configuration = load_runtime_whatsapp_configuration()
            return cls(
                base_url=runtime_configuration.api_url,
                api_key=runtime_configuration.api_key,
                instance_id=runtime_configuration.instance_id,
                timeout_seconds=runtime_configuration.timeout_seconds,
                enabled=runtime_configuration.enabled,
            )

        settings = load_settings()
        return cls(
            base_url=settings.whatsapp_api_url,
            api_key=settings.whatsapp_api_key,
            instance_id=settings.whatsapp_instance_id or None,
            timeout_seconds=settings.whatsapp_api_timeout,
            enabled=settings.whatsapp_enabled,
        )

    def validate(self) -> None:
        if not self.enabled:
            raise WhatsAppApiError("El envío por WhatsApp está deshabilitado en esta instalación.")
        if not self.base_url:
            raise WhatsAppApiError("Falta configurar la URL de WhatsApp.")
        if not self.api_key:
            raise WhatsAppApiError("Falta configurar la API key de WhatsApp.")


class WhatsAppApiClient:
    def __init__(self, config: WhatsAppApiConfig | None = None):
        self.config = config or WhatsAppApiConfig.from_settings()
        self.config.validate()

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.config.api_key,
            "Accept": "application/json",
            "User-Agent": "FEMAG-Desktop/whatsapp",
        }

    def _resolve_instance(self, instance_id: str | None) -> str:
        resolved = (instance_id or self.config.instance_id or "").strip()
        if not resolved:
            raise WhatsAppApiError(
                "El usuario no tiene una instancia de WhatsApp asociada."
            )
        return resolved

    @staticmethod
    def _response_data(response):
        raw = response.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WhatsAppApiError("El gateway devolvió una respuesta inválida.") from exc
        if not payload.get("success"):
            raise WhatsAppApiError(payload.get("error") or payload.get("message") or "Error del gateway.")
        return payload.get("data")

    @staticmethod
    def _http_error(exc: HTTPError) -> WhatsAppApiError:
        try:
            body = exc.read().decode("utf-8")
            payload = json.loads(body)
            message = payload.get("error") or payload.get("message")
        except Exception:
            message = None
        return WhatsAppApiError(message or f"El gateway respondió HTTP {exc.code}.")

    def _get(self, path: str):
        request = Request(
            f"{self.config.base_url}{path}",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                return self._response_data(response)
        except HTTPError as exc:
            raise self._http_error(exc) from exc
        except URLError as exc:
            raise WhatsAppApiError("No se pudo conectar con el gateway de WhatsApp.") from exc

    def list_instances(self) -> list[dict]:
        data = self._get("/api/v1/instances")
        return list(data or [])

    def get_instance_status(self, instance_id: str) -> dict:
        resolved = self._resolve_instance(instance_id)
        return dict(self._get(f"/api/v1/instances/{resolved}/status") or {})

    def upload_document(
        self,
        *,
        phone: str,
        file_path: Path,
        caption: str | None,
        external_ref: str,
        actor_id: str | None = None,
        actor_name: str | None = None,
        instance_id: str | None = None,
    ) -> dict:
        file_path = Path(file_path)
        if not file_path.is_file():
            raise WhatsAppApiError(f"No existe el archivo a enviar: {file_path}")
        resolved_instance = self._resolve_instance(instance_id)

        boundary = f"----FEMAG{uuid.uuid4().hex}"
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/pdf"
        fields = {
            "phone": phone,
            "mediaType": "document",
            "externalRef": external_ref,
            "sourceApp": "femag_desktop",
        }
        if caption:
            fields["caption"] = caption
        if actor_id:
            fields["actorId"] = actor_id
        if actor_name:
            fields["actorName"] = actor_name

        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ])
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8"),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        body = b"".join(chunks)
        url = (
            f"{self.config.base_url}/api/v1/instances/"
            f"{resolved_instance}/media/upload"
        )
        headers = self._headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        headers["Content-Length"] = str(len(body))
        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                if response.status != 202:
                    raise WhatsAppApiError(f"El gateway respondió HTTP {response.status}; se esperaba 202.")
                return dict(self._response_data(response) or {})
        except HTTPError as exc:
            raise self._http_error(exc) from exc
        except URLError as exc:
            raise WhatsAppApiError("No se pudo conectar con el gateway de WhatsApp.") from exc

    def get_message(self, message_id: str, *, instance_id: str | None = None) -> dict:
        resolved_instance = self._resolve_instance(instance_id)
        data = self._get(
            f"/api/v1/instances/{resolved_instance}/messages/{message_id}"
        )
        return dict(data or {})
