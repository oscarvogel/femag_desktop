"""Datos fiscales y certificados de exclusion de clientes (#871)."""

from __future__ import annotations

import os
import shutil
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from app.config.database import database_proxy
from app.models.masters import Client, ClientFiscalCertificate
from app.services.audit_service import AuditService

MAX_PDF_BYTES = 10 * 1024 * 1024
POR_VENCER_DAYS = 30

STATUS_SIN_CERTIFICADO = "sin_certificado"
STATUS_PROGRAMADA = "programada"
STATUS_VIGENTE = "vigente"
STATUS_POR_VENCER = "por_vencer"
STATUS_VENCIDA = "vencida"

STATUS_LABELS = {
    STATUS_SIN_CERTIFICADO: "Sin certificado",
    STATUS_PROGRAMADA: "Programada",
    STATUS_VIGENTE: "Vigente",
    STATUS_POR_VENCER: "Por vencer",
    STATUS_VENCIDA: "Vencida",
}


class ClientFiscalError(ValueError):
    pass


def default_docs_dir() -> Path:
    from app.services.fiscal_configuration_service import FiscalConfigurationService

    configured = FiscalConfigurationService.docs_dir()
    if configured:
        return Path(configured)
    base = os.getenv("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "FEMAG Desktop" / "documentos" / "fiscales"


class ClientFiscalService:
    def __init__(
        self,
        current_user: str,
        audit_service: AuditService | None = None,
        *,
        docs_dir: str | Path | None = None,
    ):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()
        self.docs_dir = Path(docs_dir) if docs_dir is not None else default_docs_dir()

    # ------------------------------------------------------------- certificados
    def upload_certificate(
        self,
        *,
        client: Client,
        kind: str,
        source_path: str | Path,
        valid_from: date | str | None,
        valid_until: date | str | None,
        observations: str | None = None,
    ) -> ClientFiscalCertificate:
        client = self._require_client(client)
        kind = self._validate_kind(kind)
        start = self._parse_date(valid_from, "desde")
        end = self._parse_date(valid_until, "hasta")
        if start is None:
            start = date.today()
        if end is None:
            raise ClientFiscalError("Debe indicar la vigencia hasta del certificado.")
        if end < start:
            raise ClientFiscalError(
                "La vigencia hasta no puede ser anterior a la vigencia desde."
            )

        source = Path(source_path)
        size = self._validate_pdf(source)

        destination = self._destination_path(client, kind, start)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, destination)
        except OSError as exc:
            raise ClientFiscalError(
                f"No se pudo guardar el certificado: {exc}"
            ) from exc

        relative_path = destination.relative_to(self.docs_dir).as_posix()
        previous = self.current_certificate(client, kind)
        try:
            with database_proxy.atomic():
                certificate = ClientFiscalCertificate.create(
                    client=client,
                    kind=kind,
                    valid_from=start,
                    valid_until=end,
                    file_path=relative_path,
                    original_name=source.name,
                    mime="application/pdf",
                    size_bytes=size,
                    uploaded_by=self.current_user,
                    observations=(observations or "").strip() or None,
                )
                self.audit_service.record(
                    user=self.current_user,
                    module="Maestros",
                    action="cargar certificado fiscal",
                    record_ref=f"Client:{client.id}",
                    old_value=self._audit_certificate(previous),
                    new_value=self._audit_certificate(certificate),
                )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return certificate

    def current_certificate(
        self, client: Client, kind: str
    ) -> ClientFiscalCertificate | None:
        client = self._require_client(client)
        kind = self._validate_kind(kind)
        return (
            ClientFiscalCertificate.select()
            .where(
                (ClientFiscalCertificate.client == client)
                & (ClientFiscalCertificate.kind == kind)
            )
            .order_by(
                ClientFiscalCertificate.valid_from.desc(),
                ClientFiscalCertificate.uploaded_at.desc(),
                ClientFiscalCertificate.id.desc(),
            )
            .first()
        )

    def certificates(
        self, client: Client, kind: str | None = None
    ) -> list[ClientFiscalCertificate]:
        client = self._require_client(client)
        query = ClientFiscalCertificate.select().where(
            ClientFiscalCertificate.client == client
        )
        if kind is not None:
            query = query.where(
                ClientFiscalCertificate.kind == self._validate_kind(kind)
            )
        return list(
            query.order_by(
                ClientFiscalCertificate.valid_from.desc(),
                ClientFiscalCertificate.uploaded_at.desc(),
                ClientFiscalCertificate.id.desc(),
            )
        )

    def absolute_path(self, certificate: ClientFiscalCertificate) -> Path:
        return self.docs_dir / Path(certificate.file_path)

    def certificate_state(
        self, client: Client, kind: str, *, today: date | None = None
    ) -> dict:
        today = today or date.today()
        certificate = self.current_certificate(client, kind)
        if certificate is None:
            return self._state_payload(kind, STATUS_SIN_CERTIFICADO, None, today)
        status = self.status_for_dates(
            certificate.valid_from, certificate.valid_until, today=today
        )
        return self._state_payload(kind, status, certificate, today)

    @staticmethod
    def status_for_dates(
        valid_from: date, valid_until: date, *, today: date | None = None
    ) -> str:
        today = today or date.today()
        if today < valid_from:
            return STATUS_PROGRAMADA
        if today > valid_until:
            return STATUS_VENCIDA
        if valid_until <= today + timedelta(days=POR_VENCER_DAYS):
            return STATUS_POR_VENCER
        return STATUS_VIGENTE

    def client_fiscal_summary(
        self, client: Client, *, today: date | None = None
    ) -> dict:
        client = self._require_client(client)
        rentas = self.certificate_state(
            client, ClientFiscalCertificate.RENTAS, today=today
        )
        iva = self.certificate_state(client, ClientFiscalCertificate.IVA, today=today)
        states = {
            ClientFiscalCertificate.RENTAS: rentas,
            ClientFiscalCertificate.IVA: iva,
        }
        return {
            "client_id": client.id,
            "client_name": client.name,
            "rentas_alicuota": client.rentas_alicuota,
            "fiscal_observations": client.fiscal_observations,
            "rentas": rentas,
            "iva": iva,
            "has_certificate": any(
                state["status"] != STATUS_SIN_CERTIFICADO
                for state in states.values()
            ),
            "has_expired": any(
                state["status"] == STATUS_VENCIDA for state in states.values()
            ),
        }

    def fiscal_notices_for_clients(
        self, clients: list[Client], *, today: date | None = None
    ) -> list[dict]:
        """Avisos para la orden de carga: exclusion vigente o vencida por cliente."""

        notices = []
        for client in clients:
            summary = self.client_fiscal_summary(client, today=today)
            messages = []
            has_expired = False
            for state in (summary["rentas"], summary["iva"]):
                if state["status"] == STATUS_SIN_CERTIFICADO:
                    continue
                if state["status"] == STATUS_VENCIDA:
                    has_expired = True
                    messages.append(
                        f"{state['label']} VENCIDA el "
                        f"{state['valid_until']:%d/%m/%Y}"
                    )
                elif state["status"] == STATUS_POR_VENCER:
                    messages.append(
                        f"{state['label']} por vencer el "
                        f"{state['valid_until']:%d/%m/%Y}"
                    )
                elif state["status"] == STATUS_VIGENTE:
                    messages.append(
                        f"{state['label']} vigente hasta "
                        f"{state['valid_until']:%d/%m/%Y}"
                    )
                elif state["status"] == STATUS_PROGRAMADA:
                    messages.append(
                        f"{state['label']} desde "
                        f"{state['valid_from']:%d/%m/%Y}"
                    )
            if messages:
                notices.append(
                    {
                        "client_id": client.id,
                        "client_name": client.name,
                        "has_expired": has_expired,
                        "messages": messages,
                        "summary": summary,
                    }
                )
        return notices

    def clients_with_expired_certificates(
        self, *, today: date | None = None
    ) -> list[dict]:
        today = today or date.today()
        latest: dict[tuple[int, str], ClientFiscalCertificate] = {}
        rows = (
            ClientFiscalCertificate.select()
            .order_by(
                ClientFiscalCertificate.client,
                ClientFiscalCertificate.kind,
                ClientFiscalCertificate.valid_from.desc(),
                ClientFiscalCertificate.uploaded_at.desc(),
                ClientFiscalCertificate.id.desc(),
            )
        )
        for certificate in rows:
            key = (certificate.client_id, certificate.kind)
            latest.setdefault(key, certificate)
        expired = []
        for certificate in latest.values():
            if certificate.valid_until < today:
                expired.append(
                    {
                        "client_id": certificate.client_id,
                        "client_name": certificate.client.name,
                        "kind": certificate.kind,
                        "label": ClientFiscalCertificate.KIND_LABELS.get(
                            certificate.kind, certificate.kind
                        ),
                        "valid_until": certificate.valid_until,
                    }
                )
        expired.sort(key=lambda row: (row["client_name"], row["kind"]))
        return expired

    # ------------------------------------------------------------- datos fiscales
    def update_fiscal_data(
        self,
        client: Client,
        *,
        rentas_alicuota=None,
        fiscal_observations: str | None = None,
    ) -> Client:
        client = self._require_client(client)
        old_value = self._audit_client(client)
        alicuota = self._parse_alicuota(rentas_alicuota)
        observations = (fiscal_observations or "").strip() or None
        with database_proxy.atomic():
            client.rentas_alicuota = alicuota
            client.fiscal_observations = observations
            client.save(
                only=[Client.rentas_alicuota, Client.fiscal_observations]
            )
            self.audit_service.record(
                user=self.current_user,
                module="Maestros",
                action="modificar datos fiscales",
                record_ref=f"Client:{client.id}",
                old_value=old_value,
                new_value=self._audit_client(client),
            )
        return client

    # ------------------------------------------------------------- validaciones
    def _require_client(self, client: Client) -> Client:
        if client is None or not isinstance(client, Client):
            raise ClientFiscalError("Debe seleccionar un cliente.")
        try:
            return Client.get_by_id(client.id)
        except Client.DoesNotExist as exc:
            raise ClientFiscalError("El cliente seleccionado no existe.") from exc

    @staticmethod
    def _validate_kind(kind: str) -> str:
        normalized = (kind or "").strip().lower()
        if normalized not in ClientFiscalCertificate.KINDS:
            raise ClientFiscalError("El tipo de certificado debe ser Rentas o IVA.")
        return normalized

    @staticmethod
    def _parse_date(value, label: str) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value.strip())
            except ValueError as exc:
                raise ClientFiscalError(
                    f"La vigencia {label} no es una fecha valida."
                ) from exc
        raise ClientFiscalError(f"La vigencia {label} no es una fecha valida.")

    @staticmethod
    def _parse_alicuota(value) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            alicuota = Decimal(str(value).replace(",", "."))
        except (InvalidOperation, ValueError) as exc:
            raise ClientFiscalError("La alicuota de Rentas no es valida.") from exc
        if alicuota < 0 or alicuota > 100:
            raise ClientFiscalError(
                "La alicuota de Rentas debe estar entre 0 y 100."
            )
        return alicuota.quantize(Decimal("0.01"))

    def _validate_pdf(self, source: Path) -> int:
        if not source.exists() or not source.is_file():
            raise ClientFiscalError("El archivo del certificado no existe.")
        if source.suffix.lower() != ".pdf":
            raise ClientFiscalError("El certificado debe ser un archivo PDF.")
        size = source.stat().st_size
        if size <= 0:
            raise ClientFiscalError("El archivo del certificado esta vacio.")
        if size > MAX_PDF_BYTES:
            raise ClientFiscalError(
                "El certificado supera el limite de 10 MB."
            )
        with source.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise ClientFiscalError(
                    "El archivo no parece un PDF valido."
                )
        return size

    def _destination_path(
        self, client: Client, kind: str, valid_from: date
    ) -> Path:
        filename = (
            f"{kind}_{valid_from.isoformat()}_{uuid4().hex[:8]}.pdf"
        )
        return self.docs_dir / "clientes" / str(client.id) / filename

    @staticmethod
    def _state_payload(
        kind: str,
        status: str,
        certificate: ClientFiscalCertificate | None,
        today: date,
    ) -> dict:
        days_left = (
            (certificate.valid_until - today).days if certificate is not None else None
        )
        return {
            "kind": kind,
            "label": ClientFiscalCertificate.KIND_LABELS.get(kind, kind),
            "status": status,
            "status_label": STATUS_LABELS[status],
            "certificate": certificate,
            "valid_from": certificate.valid_from if certificate else None,
            "valid_until": certificate.valid_until if certificate else None,
            "days_left": days_left,
        }

    @staticmethod
    def _audit_certificate(
        certificate: ClientFiscalCertificate | None,
    ) -> dict | None:
        if certificate is None:
            return None
        return {
            "kind": certificate.kind,
            "valid_from": certificate.valid_from.isoformat(),
            "valid_until": certificate.valid_until.isoformat(),
            "file_path": certificate.file_path,
            "original_name": certificate.original_name,
            "uploaded_by": certificate.uploaded_by,
        }

    @staticmethod
    def _audit_client(client: Client) -> dict:
        return {
            "client_id": client.id,
            "rentas_alicuota": (
                str(client.rentas_alicuota)
                if client.rentas_alicuota is not None
                else None
            ),
            "fiscal_observations": client.fiscal_observations,
        }


__all__ = [
    "ClientFiscalError",
    "ClientFiscalService",
    "MAX_PDF_BYTES",
    "POR_VENCER_DAYS",
    "STATUS_LABELS",
    "STATUS_POR_VENCER",
    "STATUS_PROGRAMADA",
    "STATUS_SIN_CERTIFICADO",
    "STATUS_VENCIDA",
    "STATUS_VIGENTE",
    "default_docs_dir",
]
