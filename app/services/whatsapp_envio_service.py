from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from app.models.security import User
from app.models.whatsapp import WhatsAppEnvio
from app.services.account_statement_share_service import normalize_whatsapp_phone
from app.services.whatsapp_api_client import TERMINAL_STATUSES, WhatsAppApiClient


def _parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_phone(phone: str) -> str:
    normalized = normalize_whatsapp_phone(phone)
    if not re.fullmatch(r"\d{8,20}", normalized):
        raise ValueError("El número de WhatsApp no tiene un formato internacional válido.")
    return normalized


class WhatsAppEnvioService:
    def __init__(self, client: WhatsAppApiClient | None = None):
        self.client = client or WhatsAppApiClient()

    def _resolve_instance_for_user(self, usuario) -> str:
        user_instance = ""
        user_id = getattr(usuario, "id", None)
        if user_id is not None:
            persisted_user = User.get_or_none(User.id == user_id)
            if persisted_user is not None:
                user_instance = (persisted_user.whatsapp_instance_id or "").strip()
        else:
            user_instance = (getattr(usuario, "whatsapp_instance_id", None) or "").strip()
        if user_instance:
            return user_instance
        legacy_instance = (getattr(getattr(self.client, "config", None), "instance_id", None) or "").strip()
        if legacy_instance:
            return legacy_instance
        raise ValueError(
            "El usuario no tiene una instancia de WhatsApp asociada. "
            "Configúrela desde Sistema > WhatsApp."
        )

    def create_attempt(
        self,
        *,
        tipo_documento: str,
        documento_id: str,
        destinatario: str,
        caption: str,
        pdf_path: Path,
        usuario=None,
    ) -> WhatsAppEnvio:
        phone = normalize_phone(destinatario)
        instance_id = self._resolve_instance_for_user(usuario)
        envio = WhatsAppEnvio.create(
            tipo_documento=tipo_documento,
            documento_id=str(documento_id),
            destinatario=phone,
            instance_id=instance_id,
            external_ref=f"pending:{tipo_documento}:{documento_id}:{time.time_ns()}",
            caption=caption or None,
            nombre_archivo=Path(pdf_path).name,
            mime_type="application/pdf",
            estado="preparing",
            usuario=usuario,
        )
        envio.external_ref = f"femag:{tipo_documento}:{documento_id}:{envio.id}"
        envio.save()
        return envio

    def _apply_status(self, envio: WhatsAppEnvio, data: dict) -> WhatsAppEnvio:
        envio.estado = str(data.get("status") or envio.estado)
        envio.provider_message_id = data.get("providerMessageId") or envio.provider_message_id
        envio.error = data.get("error") or (envio.error if envio.estado == "failed" else None)
        envio.accepted_at = _parse_datetime(data.get("acceptedAt")) or envio.accepted_at
        envio.delivered_at = _parse_datetime(data.get("deliveredAt")) or envio.delivered_at
        envio.read_at = _parse_datetime(data.get("readAt")) or envio.read_at
        envio.failed_at = _parse_datetime(data.get("failedAt")) or envio.failed_at
        envio.save()
        return envio

    def send_pdf(
        self,
        *,
        envio: WhatsAppEnvio,
        pdf_path: Path,
        poll_attempts: int = 4,
        poll_interval: float = 1.0,
    ) -> WhatsAppEnvio:
        try:
            if not envio.instance_id:
                raise ValueError("El envío no tiene una instancia de WhatsApp registrada.")
            data = self.client.upload_document(
                phone=envio.destinatario,
                file_path=Path(pdf_path),
                caption=envio.caption,
                external_ref=envio.external_ref,
                actor_id=str(envio.usuario_id) if envio.usuario_id else None,
                actor_name=getattr(envio.usuario, "display_name", None)
                or getattr(envio.usuario, "username", None),
                instance_id=envio.instance_id,
            )
            envio.message_id = data.get("messageId")
            envio.estado = data.get("status") or "queued"
            envio.error = None
            envio.save()
            if not envio.message_id:
                raise RuntimeError("El gateway no devolvió messageId.")

            for _ in range(max(0, poll_attempts)):
                status = self.client.get_message(
                    envio.message_id,
                    instance_id=envio.instance_id,
                )
                self._apply_status(envio, status)
                if envio.estado in TERMINAL_STATUSES:
                    break
                if poll_interval:
                    time.sleep(poll_interval)
            return envio
        except Exception as exc:
            envio.estado = "failed"
            envio.error = str(exc)
            if envio.failed_at is None:
                envio.failed_at = datetime.now().astimezone()
            envio.save()
            raise

    def refresh_status(self, envio: WhatsAppEnvio) -> WhatsAppEnvio:
        if not envio.message_id:
            return envio
        if not envio.instance_id:
            raise ValueError("El envío no tiene una instancia de WhatsApp registrada.")
        return self._apply_status(
            envio,
            self.client.get_message(
                envio.message_id,
                instance_id=envio.instance_id,
            ),
        )

    @staticmethod
    def history(tipo_documento: str, documento_id: str):
        return (
            WhatsAppEnvio.select()
            .where(
                (WhatsAppEnvio.tipo_documento == tipo_documento)
                & (WhatsAppEnvio.documento_id == str(documento_id))
            )
            .order_by(WhatsAppEnvio.created_at.desc())
        )
