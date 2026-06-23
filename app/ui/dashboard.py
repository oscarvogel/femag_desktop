from datetime import date

from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, Driver, Product
from app.models.system import BackupLog


def future_module_message() -> str:
    return "Funcionalidad prevista para una próxima entrega."


class DashboardService:
    def summary(self) -> dict[str, int | str | None]:
        last_backup = BackupLog.select().order_by(BackupLog.started_at.desc()).first()
        return {
            "clientes": Client.select().count(),
            "productos": Product.select().count(),
            "choferes": Driver.select().count(),
            "transportistas": Carrier.select().count(),
            "ultimo_backup": last_backup.status if last_backup else None,
            "ordenes_hoy": LoadOrder.select().where(LoadOrder.date == date.today()).count(),
            "ordenes_pendientes": LoadOrder.select()
            .where(LoadOrder.status == LoadOrder.STATUS_PENDING)
            .count(),
            "choferes_bloqueados": Driver.select().where(Driver.available == False).count(),  # noqa: E712
            "acceso_rapido_nueva_orden": "Nueva orden de carga",
        }
