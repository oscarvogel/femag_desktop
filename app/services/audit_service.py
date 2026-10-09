import socket

from app.models.audit import AuditLog
from app.models.base import utc_now

WORKSTATION_VERSION_MODULE = "Sistema"
WORKSTATION_VERSION_ACTION = "version de puesto"


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

    def record_workstation_version(self, version: str, *, workstation: str | None = None) -> AuditLog:
        """Deja que version esta corriendo en cada puesto, con **una** fila por puesto.

        Sin esto la version solo vive en la maquina (titulo de la ventana y barra de
        estado), y cuando un puesto queda trabado por version hay que ir equipo por
        equipo a preguntarla. Con esto sale de una consulta.

        No se inserta una fila por arranque: se actualiza la del puesto, asi la tabla
        no crece con cada inicio. Un insert por apertura seria ruido puro, y el
        `workstation` ya viene del AuditLog, no hace falta duplicarlo en otro lado.
        """
        host = workstation or socket.gethostname()
        # JSONTextField serializa el dict al escribir y lo parsea al leer.
        payload = {"version": version}
        row = (
            AuditLog.select()
            .where(
                (AuditLog.module == WORKSTATION_VERSION_MODULE)
                & (AuditLog.action == WORKSTATION_VERSION_ACTION)
                & (AuditLog.workstation == host)
            )
            .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            .first()
        )
        if row is None:
            return AuditLog.create(
                user=None,
                module=WORKSTATION_VERSION_MODULE,
                action=WORKSTATION_VERSION_ACTION,
                record_ref=host,
                new_value=payload,
                observation=f"FEMAG {version}",
                workstation=host,
            )
        row.new_value = payload
        row.observation = f"FEMAG {version}"
        row.occurred_at = utc_now()
        row.save()
        return row
