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
        avisos: list[AvisoView] = []
        if self._can_see(user, ["Secretaría", "Administración", "Administrador"]):
            avisos += self._orden_sin_cierre()
            avisos += self._deuda_vencida()
        if self._can_see(user, ["Administración", "Administrador"]):
            avisos += self._producto_revision()
        return self._filter_leidos(user, avisos)

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

    def _can_see(self, user: User, allowed_profiles: list[str]) -> bool:
        try:
            return user.profile.name in allowed_profiles
        except Exception:
            return False

    def _orden_sin_cierre(self) -> list[AvisoView]:
        from app.models.load_orders import LoadOrder

        out: list[AvisoView] = []
        for o in LoadOrder.select().where(LoadOrder.status == LoadOrder.STATUS_ISSUED).order_by(LoadOrder.id.desc()).limit(20):
            # resolve client name via destinations if legacy client is None
            client_name = ""
            try:
                dest = o.destinations.first()
                if dest and dest.client:
                    client_name = dest.client.name
                elif getattr(o, "client", None) and getattr(o.client, "name", None):
                    client_name = o.client.name
            except Exception:
                client_name = ""
            out.append(
                AvisoView(
                    titulo=f"OC-{o.order_number:06d} sin cerrar",
                    descripcion=f"Cliente {client_name}".strip() if client_name else "Sin cliente",
                    tipo="orden_sin_cierre",
                    prioridad="alta",
                    route_key="load_orders",
                    referencia_id=o.id,
                    created_at=datetime.utcnow(),
                )
            )
        return out

    def _deuda_vencida(self) -> list[AvisoView]:
        from app.models.masters import Client
        from app.services.ledger_query_service import client_balance

        out: list[AvisoView] = []
        for c in Client.select().where(Client.active == True).limit(50):  # noqa: E712
            bal = client_balance(c)
            if bal > 0:
                out.append(
                    AvisoView(
                        titulo=f"Deuda {c.name}",
                        descripcion=f"Saldo ${bal:.2f}",
                        tipo="deuda_vencida",
                        prioridad="media",
                        route_key="clientes",
                        referencia_id=c.id,
                        created_at=datetime.utcnow(),
                    )
                )
        return out

    def _producto_revision(self) -> list[AvisoView]:
        from app.models.masters import Product

        out: list[AvisoView] = []
        for p in Product.select().where((Product.review_required == True) | (Product.peso_unitario_kg == 0)).limit(20):  # noqa: E712
            out.append(
                AvisoView(
                    titulo=p.name,
                    descripcion="Revisión pendiente",
                    tipo="producto_revision",
                    prioridad="baja",
                    route_key="products",
                    referencia_id=p.id,
                    created_at=datetime.utcnow(),
                )
            )
        return out
