from __future__ import annotations

from app.models.security import User
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService


class ManagerialAccessService:
    def __init__(
        self,
        *,
        auth_service: AuthService | None = None,
        permission_service: PermissionService | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self.auth_service = auth_service or AuthService()
        self.permission_service = permission_service or PermissionService()
        self.audit_service = audit_service or AuditService()

    def authorize(self, username: str, password: str, *, requested_by: User | None = None) -> User | None:
        username = (username or "").strip()
        user = User.get_or_none(User.username == username, User.active == True)  # noqa: E712
        valid_password = bool(
            user is not None
            and self.auth_service._verify_password(password, user.password_hash)
        )
        allowed = bool(
            valid_password
            and user is not None
            and self.permission_service.can_view_managerial_dashboard(user)
        )
        authorized = user if allowed else None
        self._audit(requested_by=requested_by, authorizer=user, granted=allowed)
        return authorized

    def _audit(self, *, requested_by: User | None, authorizer: User | None, granted: bool) -> None:
        requester = requested_by.username if requested_by is not None else None
        authorizer_name = authorizer.username if authorizer is not None else None
        self.audit_service.record(
            user=requester or authorizer_name,
            module="Dashboard Gerencial",
            action="autorizar acceso" if granted else "rechazar acceso",
            record_ref=f"User:{authorizer.id}" if authorizer is not None else None,
            new_value={
                "requested_by": requester,
                "authorized_by": authorizer_name,
                "granted": granted,
            },
        )
