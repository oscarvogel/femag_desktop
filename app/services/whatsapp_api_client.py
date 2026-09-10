from __future__ import annotations

import json
import mimetypes
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TERMINAL_STATUSES = {"delivered", "read", "failed"}


class WhatsAppApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class WhatsAppApiConfig:
    base_url: str
    api_key: str
    instance_id: str
    timeout_seconds: float = 15.0
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "WhatsAppApiConfig":
        enabled = str(os.getenv("WHATSAPP_ENABLED", "true")).strip().lower() in {
            "1", "true", "yes", "si", "sí", "on"
        }
        return cls(
            base_url=os.getenv("WHATSAPP_API_URL", "").strip().rstrip("/"),
            api_key=os.getenv("WHATSAPP_API_KEY", "").strip(),
            instance_id=os.getenv("WHATSAPP_INSTANCE_ID", "default").strip(),
            timeout_seconds=float(os.getenv("WHATSAPP_API_TIMEOUT", "15")),
            enabled=enabled,
        )

    def validate(self) -> None:
        if not self.enabled:
            raise WhatsAppApiError("El envío por WhatsApp está deshabilitado en esta instalación.")
        if not self.base_url:
            raise WhatsAppApiError("Falta configurar WHATSAPP_API_URL.")
        if not self.api_key:
            raise WhatsAppApiError("Falta configurar WHATSAPP_API_KEY.")
        if not self.instance_id:
            raise WhatsAppApiError("Falta configurar WHATSAPP_INSTANCE_ID.")


class WhatsAppApiClient:
    def __init__(self, config: WhatsAppApiConfig | None = None):
        self.config = config or WhatsAppApiConfig.from_env()
        self.config.validate()

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.config.api_key,
            "Accept": "application/json",
            "User-Agent": "FEMAG-Desktop/whatsapp",
        }

    @staticmethod
    def _response_data(response) -> dict:
        raw = response.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WhatsAppApiError("El gateway devolvió una respuesta inválida.") from exc
        if not payload.get("success"):
            raise WhatsAppApiError(payload.get("error") or payload.get("message") or "Error del gateway.")
        return payload.get("data") or {}

    @staticmethod
    def _http_error(exc: HTTPError) -> WhatsAppApiError:
        try:
            body = exc.read().decode("utf-8")
            payload = json.loads(body)
            message = payload.get("error") or payload.get("message")
        except Exception:
            message = None
        return WhatsAppApiError(message or f"El gateway respondió HTTP {exc.code}.")

    def upload_document(
        self,
        *,
        phone: str,
        file_path: Path,
        caption: str | None,
        external_ref: str,
        actor_id: str | None = None,
        actor_name: str | None = None,
    ) -> dict:
        file_path = Path(file_path)
        if not file_path.is_file():
            raise WhatsAppApiError(f"No existe el archivo a enviar: {file_path}")

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
            f"{self.config.instance_id}/media/upload"
        )
        headers = self._headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        headers["Content-Length"] = str(len(body))
        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                if response.status != 202:
                    raise WhatsAppApiError(f"El gateway respondió HTTP {response.status}; se esperaba 202.")
                return self._response_data(response)
        except HTTPError as exc:
            raise self._http_error(exc) from exc
        except URLError as exc:
            raise WhatsAppApiError("No se pudo conectar con el gateway de WhatsApp.") from exc

    def get_message(self, message_id: str) -> dict:
        url = (
            f"{self.config.base_url}/api/v1/instances/"
            f"{self.config.instance_id}/messages/{message_id}"
        )
        request = Request(url, headers=self._headers(), method="GET")
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                return self._response_data(response)
        except HTTPError as exc:
            raise self._http_error(exc) from exc
        except URLError as exc:
            raise WhatsAppApiError("No se pudo consultar el estado del mensaje.") from exc
