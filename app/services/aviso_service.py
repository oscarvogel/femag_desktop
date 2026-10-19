import logging
from dataclasses import dataclass
from datetime import datetime

from app.models.notifications import AvisoLectura
from app.models.security import User

logger = logging.getLogger(__name__)

#: Avisos que no se apagan marcando "leído".
#:
#: Son los que avisan de plata que no está registrada: el problema sigue
#: existiendo hasta que se repara, así que silenciarlo con el botón "Marcar
#: todo leído" dejaría al sistema caído sin avisar otra vez (#726).
PERSISTENT_TYPES = frozenset({"orden_sin_cuenta_corriente"})


@dataclass(frozen=True)
class AvisoView:
    titulo: str
    descripcion: str
    tipo: str
    prioridad: str
    route_key: str
    referencia_id: int | None
    created_at: datetime


class AvisoService:
    def get_for_user(self, user: User) -> list[AvisoView]:
        if user is None or not user.active:
            return []
        avisos: list[AvisoView] = []
        if self._can_see(user, ["Administración", "Administrador"]):
            # La alarma de plata va PRIMERA: es lo que no se puede dejar de
            # ver, y el listado de avisos pendientes ya tiene ruido (#726).
            avisos += self._orden_sin_cuenta_corriente()
        if self._can_see(user, ["Secretaría", "Administración", "Administrador"]):
            avisos += self._orden_sin_cierre()
            avisos += self._deuda_vencida()
        if self._can_see(user, ["Administración", "Administrador"]):
            avisos += self._producto_revision()
        return self._filter_leidos(user, avisos)

    def count_unread(self, user: User) -> int:
        return len(self.get_for_user(user))

    def mark_read(self, user: User, tipo: str, referencia_id: int | None):
        rec, _ = AvisoLectura.get_or_create(
            user=user,
            tipo=tipo,
            referencia_id=referencia_id,
            defaults={"leido_at": datetime.utcnow()},
        )
        rec.leido_at = datetime.utcnow()
        rec.save()

    def mark_all_read(self, user: User):
        for aviso in self.get_for_user(user):
            self.mark_read(user, aviso.tipo, aviso.referencia_id)

    def reactivate_all(self, user: User) -> int:
        return (
            AvisoLectura.update(leido_at=None, oculto_hasta=None)
            .where(AvisoLectura.user == user)
            .execute()
        )

    def _filter_leidos(self, user: User, avisos: list[AvisoView]) -> list[AvisoView]:
        filtered = []
        for aviso in avisos:
            if aviso.tipo in PERSISTENT_TYPES:
                # Estos avisos no se apagan marcando "leído": se apagan cuando
                # la orden queda reparada. Si se apagaran, el sistema volvería
                # a caer sin avisar nada (#726).
                filtered.append(aviso)
                continue
            rec = AvisoLectura.get_or_none(
                (AvisoLectura.user == user)
                & (AvisoLectura.tipo == aviso.tipo)
                & (AvisoLectura.referencia_id == aviso.referencia_id)
            )
            if rec and rec.leido_at:
                continue
            filtered.append(aviso)
        return filtered

    def _can_see(self, user: User, allowed_profiles: list[str]) -> bool:
        try:
            return user.profile.name in allowed_profiles
        except Exception:
            return False

    def _orden_sin_cierre(self) -> list[AvisoView]:
        from app.models.load_orders import LoadOrder

        out: list[AvisoView] = []
        query = (
            LoadOrder.select()
            .where(LoadOrder.status == LoadOrder.STATUS_ISSUED)
            .order_by(LoadOrder.id.desc())
            .limit(20)
        )
        for order in query:
            client_name = ""
            try:
                destination = order.destinations.first()
                if destination and destination.client:
                    client_name = destination.client.name
                elif getattr(order, "client", None) and getattr(order.client, "name", None):
                    client_name = order.client.name
            except Exception:
                client_name = ""
            out.append(
                AvisoView(
                    titulo=f"OC-{order.order_number:06d} sin cerrar",
                    descripcion=f"Cliente {client_name}" if client_name else "Sin cliente",
                    tipo="orden_sin_cierre",
                    prioridad="alta",
                    route_key="load_orders",
                    referencia_id=order.id,
                    created_at=datetime.utcnow(),
                )
            )
        return out

    def _deuda_vencida(self) -> list[AvisoView]:
        from app.models.masters import Client
        from app.services.ledger_query_service import client_balance

        out: list[AvisoView] = []
        for client in Client.select().where(Client.active == True).limit(50):  # noqa: E712
            balance = client_balance(client)
            if balance > 0:
                out.append(
                    AvisoView(
                        titulo=f"Deuda {client.name}",
                        descripcion=f"Saldo ${balance:.2f}",
                        tipo="deuda_vencida",
                        prioridad="media",
                        route_key="clients",
                        referencia_id=client.id,
                        created_at=datetime.utcnow(),
                    )
                )
        return out

    def _orden_sin_cuenta_corriente(self) -> list[AvisoView]:
        """Órdenes emitidas sin movimiento en la cuenta corriente del cliente.

        Es la alarma del incidente #726: una orden emitida a medias deja
        mercadería afuera y **plata sin registrar**. El aviso se arma con el
        monto que falta, porque eso es lo que la empresa está perdiendo.

        Si la detección falla, no se inventa ninguna alarma: se registra el
        error y se sigue, para no dejar al administrador con un aviso falso
        que lo haga desconfiar del sistema.
        """
        from app.services.load_order_ledger_repair_service import (
            LoadOrderLedgerRepairService,
        )

        out: list[AvisoView] = []
        try:
            service = LoadOrderLedgerRepairService(current_user="aviso_sistema")
            findings = service.find_orders_missing_ledger()
        except Exception:
            logger.exception("No se pudo detectar órdenes sin cuenta corriente")
            return []
        for finding in findings:
            documentos = len(finding.ledger_gaps)
            out.append(
                AvisoView(
                    titulo=f"{finding.order_reference} sin cuenta corriente",
                    descripcion=(
                        f"{documentos} documento(s) · "
                        f"${finding.total_amount:,.2f} sin registrar"
                    ),
                    tipo="orden_sin_cuenta_corriente",
                    prioridad="alta",
                    route_key="load_orders",
                    referencia_id=finding.order_id,
                    created_at=datetime.utcnow(),
                )
            )
        return out

    def _producto_revision(self) -> list[AvisoView]:
        from app.models.masters import Product

        out: list[AvisoView] = []
        query = Product.select().where(
            (Product.review_required == True) | (Product.peso_unitario_kg == 0)  # noqa: E712
        ).limit(20)
        for product in query:
            out.append(
                AvisoView(
                    titulo=product.name,
                    descripcion="Revisión pendiente",
                    tipo="producto_revision",
                    prioridad="baja",
                    route_key="products",
                    referencia_id=product.id,
                    created_at=datetime.utcnow(),
                )
            )
        return out
