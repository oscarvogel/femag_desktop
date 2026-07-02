from dataclasses import dataclass
from datetime import date

from peewee import InterfaceError, OperationalError

from app.config.database import database_proxy
from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, Driver, Product
from app.models.system import BackupLog


def future_module_message() -> str:
    return "Funcionalidad prevista para una próxima entrega."


@dataclass(frozen=True)
class QuickActionSpec:
    title: str
    route_key: str | None
    enabled: bool
    message: str | None = None


@dataclass(frozen=True)
class DashboardViewSpec:
    title: str
    quick_actions: tuple[QuickActionSpec, ...]
    summary_cards: dict[str, int | str]
    alerts: tuple[str, ...]


class DashboardService:
    def summary(self) -> dict[str, int | str | None]:
        if database_proxy.obj is None:
            return self.empty_summary()
        try:
            last_backup = BackupLog.select().order_by(BackupLog.started_at.desc()).first()
            closed_orders = LoadOrder.select().where(LoadOrder.status == LoadOrder.STATUS_CLOSED).count()
            return {
                "clientes": Client.select().count(),
                "productos": Product.select().count(),
                "choferes": Driver.select().count(),
                "transportistas": Carrier.select().count(),
                "ultimo_backup": last_backup.status if last_backup else "Sin registros",
                "ordenes_hoy": LoadOrder.select().where(LoadOrder.date == date.today()).count(),
                "ordenes_pendientes": LoadOrder.select()
                .where(LoadOrder.status == LoadOrder.STATUS_PENDING)
                .count(),
                "ordenes_cerradas": closed_orders,
                "choferes_bloqueados": Driver.select().where(Driver.available == False).count(),  # noqa: E712
                "acceso_rapido_nueva_orden": "Nueva orden de carga",
            }
        except (InterfaceError, OperationalError):
            return self.empty_summary()

    def empty_summary(self) -> dict[str, int | str | None]:
        return {
            "clientes": 0,
            "productos": 0,
            "choferes": 0,
            "transportistas": 0,
            "ultimo_backup": "Sin registros",
            "ordenes_hoy": 0,
            "ordenes_pendientes": 0,
            "ordenes_cerradas": 0,
            "choferes_bloqueados": 0,
            "acceso_rapido_nueva_orden": "Nueva orden de carga",
        }

    def view_spec(self, *, demo_mode: bool = False) -> DashboardViewSpec:
        summary = self.summary()
        quick_actions = (
            QuickActionSpec("Nueva orden de carga", "load_orders.new", True),
            QuickActionSpec("Buscar orden", "load_orders.search", True),
            QuickActionSpec("Nuevo cliente", "clients.new", True),
            QuickActionSpec("Registrar remito", None, False, future_module_message()),
            QuickActionSpec("F150", None, False, future_module_message()),
            QuickActionSpec("Registrar pago", "customer_ledger.register_payment", True),
            QuickActionSpec("Cuenta corriente", "customer_ledger.view", True),
        )
        cards = {
            "Órdenes creadas hoy": summary["ordenes_hoy"] or 0,
            "Órdenes pendientes": summary["ordenes_pendientes"] or 0,
            "Órdenes cerradas": summary["ordenes_cerradas"] or 0,
            "Choferes ocupados": summary["choferes_bloqueados"] or 0,
            "Último backup": summary["ultimo_backup"] or "Sin registros",
        }
        alerts = [
            f"Choferes bloqueados: {summary['choferes_bloqueados'] or 0}",
            f"Órdenes abiertas: {summary['ordenes_pendientes'] or 0}",
            f"Último backup: {summary['ultimo_backup'] or 'Sin registros'}",
            "Próximos módulos: remitos, F150.",
        ]
        if demo_mode:
            alerts.append("Modo demo visual con datos de prueba.")
        return DashboardViewSpec(
            title="Dashboard operativo",
            quick_actions=quick_actions,
            summary_cards=cards,
            alerts=tuple(alerts),
        )
