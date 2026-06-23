import socket

from app.models.audit import AuditLog


class AuditService:
    def record(
        self,
        *,
        user: str | None,
        module: str,
        action: str,
        record_ref: str | None = None,
        old_value=None,
        new_value=None,
        observation: str | None = None,
        workstation: str | None = None,
    ) -> AuditLog:
        return AuditLog.create(
            user=user,
            module=module,
            action=action,
            record_ref=record_ref,
            old_value=old_value,
            new_value=new_value,
            observation=observation,
            workstation=workstation or socket.gethostname(),
        )
