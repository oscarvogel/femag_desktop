from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models.notifications import AvisoLectura
from app.models.security import User


@dataclass(frozen=True)
class AvisoView:
    titulo: str
    descripcion: str
    tipo: str
    prioridad: str  # alta/media/baja
    route_key: str
    referencia_id: int | None
    created_at: datetime


class AvisoService:
    def get_for_user(self, user: User) -> list[AvisoView]:
        if user is None or not user.active:
            return []
        # TODO tipos se añaden en Task 2; infra retorna []
        return self._filter_leidos(user, [])

    def count_unread(self, user: User) -> int:
        return len(self.get_for_user(user))

    def mark_read(self, user: User, tipo: str, referencia_id: int | None):
        AvisoLectura.get_or_create(user=user, tipo=tipo, referencia_id=referencia_id, defaults={"leido_at": datetime.utcnow()})
        rec = AvisoLectura.get((AvisoLectura.user == user) & (AvisoLectura.tipo == tipo) & (AvisoLectura.referencia_id == referencia_id))
        rec.leido_at = datetime.utcnow()
        rec.save()

    def mark_all_read(self, user: User):
        for aviso in self.get_for_user(user):
            self.mark_read(user, aviso.tipo, aviso.referencia_id)

    def _filter_leidos(self, user: User, avisos: list[AvisoView]) -> list[AvisoView]:
        filtered = []
        for av in avisos:
            rec = AvisoLectura.get_or_none((AvisoLectura.user == user) & (AvisoLectura.tipo == av.tipo) & (AvisoLectura.referencia_id == av.referencia_id))
            if rec and rec.leido_at and (rec.oculto_hasta is None or rec.oculto_hasta > datetime.utcnow()):
                continue
            filtered.append(av)
        return filtered
