from __future__ import annotations

import re

from peewee import IntegrityError

from app.models.masters import Client, ClientEmail
from app.services.audit_service import AuditService


class ClientEmailError(ValueError):
    pass


class ClientEmailService:
    EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    @classmethod
    def normalize_email(cls, email: str) -> str:
        normalized = (email or "").strip().lower()
        if not cls.EMAIL_PATTERN.fullmatch(normalized):
            raise ClientEmailError("Ingrese un email valido.")
        return normalized

    def create(
        self,
        *,
        client: Client,
        email: str,
        label: str | None = None,
        is_primary: bool = False,
        active: bool = True,
        observations: str | None = None,
    ) -> ClientEmail:
        normalized = self.normalize_email(email)
        database = ClientEmail._meta.database
        try:
            with database.atomic():
                if ClientEmail.select().where(
                    (ClientEmail.client == client) & (ClientEmail.email == normalized)
                ).exists():
                    raise ClientEmailError("El cliente ya tiene registrado ese email.")
                has_active = ClientEmail.select().where(
                    (ClientEmail.client == client) & (ClientEmail.active == True)  # noqa: E712
                ).exists()
                primary = bool(active and (is_primary or not has_active))
                if primary:
                    self._clear_primary(client)
                row = ClientEmail.create(
                    client=client,
                    email=normalized,
                    label=self._clean(label),
                    is_primary=primary,
                    active=active,
                    observations=self._clean(observations),
                )
                self._ensure_primary(client)
                self._sync_legacy_email(client)
                self._record("crear_email", row)
                return row
        except IntegrityError as exc:
            raise ClientEmailError("El cliente ya tiene registrado ese email.") from exc

    def update(
        self,
        row: ClientEmail,
        *,
        email: str,
        label: str | None = None,
        is_primary: bool = False,
        active: bool = True,
        observations: str | None = None,
    ) -> ClientEmail:
        normalized = self.normalize_email(email)
        database = ClientEmail._meta.database
        with database.atomic():
            duplicate = ClientEmail.select().where(
                (ClientEmail.client == row.client)
                & (ClientEmail.email == normalized)
                & (ClientEmail.id != row.id)
            )
            if duplicate.exists():
                raise ClientEmailError("El cliente ya tiene registrado ese email.")
            if is_primary and not active:
                raise ClientEmailError("Un email principal debe estar activo.")
            if is_primary:
                self._clear_primary(row.client, exclude_id=row.id)
            row.email = normalized
            row.label = self._clean(label)
            row.active = bool(active)
            row.is_primary = bool(is_primary and active)
            row.observations = self._clean(observations)
            row.save()
            self._ensure_primary(row.client)
            self._sync_legacy_email(row.client)
            self._record("editar_email", row)
            return row

    def toggle_active(self, row: ClientEmail) -> ClientEmail:
        return self.update(
            row,
            email=row.email,
            label=row.label,
            is_primary=row.is_primary and not row.active,
            active=not row.active,
            observations=row.observations,
        )

    def set_primary(self, row: ClientEmail) -> ClientEmail:
        if not row.active:
            raise ClientEmailError("Active el email antes de marcarlo como principal.")
        return self.update(
            row,
            email=row.email,
            label=row.label,
            is_primary=True,
            active=True,
            observations=row.observations,
        )

    @staticmethod
    def active_for_client(client: Client) -> list[ClientEmail]:
        return list(
            ClientEmail.select()
            .where((ClientEmail.client == client) & (ClientEmail.active == True))  # noqa: E712
            .order_by(ClientEmail.is_primary.desc(), ClientEmail.id)
        )

    @staticmethod
    def _clean(value: str | None) -> str | None:
        return (value or "").strip() or None

    @staticmethod
    def _clear_primary(client: Client, exclude_id: int | None = None) -> None:
        query = ClientEmail.update(is_primary=False).where(ClientEmail.client == client)
        if exclude_id is not None:
            query = query.where(ClientEmail.id != exclude_id)
        query.execute()

    @staticmethod
    def _ensure_primary(client: Client) -> None:
        active = ClientEmail.select().where(
            (ClientEmail.client == client) & (ClientEmail.active == True)  # noqa: E712
        )
        if not active.exists():
            ClientEmail.update(is_primary=False).where(ClientEmail.client == client).execute()
            return
        if not active.where(ClientEmail.is_primary == True).exists():  # noqa: E712
            first = active.order_by(ClientEmail.id).first()
            first.is_primary = True
            first.save()

    @staticmethod
    def _sync_legacy_email(client: Client) -> None:
        primary = (
            ClientEmail.select()
            .where(
                (ClientEmail.client == client)
                & (ClientEmail.active == True)  # noqa: E712
                & (ClientEmail.is_primary == True)  # noqa: E712
            )
            .first()
        )
        client.email = primary.email if primary is not None else None
        client.save()

    def _record(self, action: str, row: ClientEmail) -> None:
        self.audit_service.record(
            user=self.current_user,
            module="Clientes",
            action=action,
            record_ref=f"ClientEmail:{row.id}",
            new_value={
                "client_id": row.client.id,
                "email": row.email,
                "label": row.label,
                "is_primary": row.is_primary,
                "active": row.active,
            },
        )
