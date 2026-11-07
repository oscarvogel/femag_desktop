from __future__ import annotations

from app.models.audit import AuditLog
from app.models.security import User


#: Etiquetas de filtro para los eventos que no tienen una identidad canónica.
UNATTRIBUTED_LABEL = "Sin atribuir"
SYSTEM_LABEL = "Sistema"

#: Alias históricos explícitos que no son una variación de mayúsculas/minúsculas.
#: Los dudosos no se mapean: quedan sin atribuir a propósito.
AUDIT_USER_ALIASES = {
    "gabreila": "gabriela",
}


def _users_by_casefold() -> dict[str, User]:
    return {user.username.strip().casefold(): user for user in User.select()}


def canonical_username(username: str | None) -> str | None:
    value = (username or "").strip()
    if not value:
        return None
    return AUDIT_USER_ALIASES.get(value.casefold(), value)


def resolve_audit_user_id(
    username: str | None,
    *,
    users: dict[str, User] | None = None,
) -> int | None:
    canonical = canonical_username(username)
    if canonical is None:
        return None
    users = users if users is not None else _users_by_casefold()
    user = users.get(canonical.casefold())
    return user.id if user is not None else None


def audit_user_aliases(username: str | None) -> list[str]:
    """Alias históricos que pertenecen a la misma identidad canónica."""
    canonical = canonical_username(username)
    if canonical is None:
        return []
    aliases = {canonical}
    for alias, target in AUDIT_USER_ALIASES.items():
        if target.casefold() == canonical.casefold():
            aliases.add(alias)
    return sorted(aliases)


def user_names() -> dict[int, str]:
    return {user.id: user.username for user in User.select()}


def backfill_audit_user_ids(*, dry_run: bool = False) -> dict[str, int]:
    """Completa `AuditLog.user_id` para los alias históricos conocidos.

    No reescribe `AuditLog.user`: el nombre original queda como evidencia. Los
    eventos que no se pueden atribuir con seguridad quedan en NULL.
    """
    users = _users_by_casefold()
    updated = 0
    unattributed = 0

    raw_users = (
        AuditLog.select(AuditLog.user)
        .where(AuditLog.user_id.is_null(True))
        .distinct()
    )
    for row in raw_users:
        raw_user = row.user
        user_id = resolve_audit_user_id(raw_user, users=users)
        condition = AuditLog.user_id.is_null(True)
        if raw_user is None:
            condition &= AuditLog.user.is_null(True)
        else:
            condition &= AuditLog.user == raw_user

        if user_id is None:
            unattributed += AuditLog.select().where(condition).count()
            continue
        if dry_run:
            updated += AuditLog.select().where(condition).count()
        else:
            updated += AuditLog.update(user_id=user_id).where(condition).execute()

    return {"updated": updated, "unattributed": unattributed}
