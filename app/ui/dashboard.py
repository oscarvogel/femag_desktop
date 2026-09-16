from dataclasses import dataclass
from datetime import date, timedelta

from peewee import InterfaceError, OperationalError

from app.config.database import database_proxy
from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, Driver, Product
from app.models.system import BackupLog
from app.reports.collection_due_report import CollectionDueFilters, CollectionDueReportService
from app.services.ledger_query_service import client_balances


def future_module_message() -> str:
    return "Funcionalidad prevista para una próxima entrega."


@dataclass(frozen=True)
class QuickActionSpec:
    title: str
    route_key: str | None
    enabled: bool
    message: str | None = None


@dataclass(frozen=True)
class CollectionCardSpec:
    title: str
    amount: float
    count: int
    route_key: str


@dataclass(frozen=True)
class DashboardViewSpec:
    title: str
    quick_actions: tuple[QuickActionSpec, ...]
    summary_cards: dict[str, int | str]
    alerts: tuple[str, ...]
    collection_cards: tuple[CollectionCardSpec, ...] = ()
    overdue_rows: tuple[dict, ...] = ()
    upcoming_rows: tuple[dict, ...] = ()


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
                .where(LoadOrder.status.not_in((LoadOrder.STATUS_ISSUED, *LoadOrder.FINAL_STATUSES)))
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

    def collection_snapshot(self, *, today: date | None = None) -> dict:
        today = today or date.today()
        empty = {
            "overdue_amount": 0.0,
            "overdue_count": 0,
            "due_today_amount": 0.0,
            "due_today_count": 0,
            "next_7_amount": 0.0,
            "next_7_count": 0,
            "next_30_amount": 0.0,
            "next_30_count": 0,
            "debtor_balance": 0.0,
            "debtor_clients": 0,
            "overdue_rows": (),
            "upcoming_rows": (),
        }
        if database_proxy.obj is None:
            return empty
        try:
            result = CollectionDueReportService().report(CollectionDueFilters(), today=today)
            rows = tuple(result.rows)
            overdue = tuple(row for row in rows if row["due_date"] < today)
            due_today = tuple(row for row in rows if row["due_date"] == today)
            next_7 = tuple(
                row for row in rows if today < row["due_date"] <= today + timedelta(days=7)
            )
            next_30 = tuple(
                row for row in rows if today < row["due_date"] <= today + timedelta(days=30)
            )
            debtor_rows = tuple(row for row in client_balances() if float(row["balance"]) > 0.01)
            upcoming = tuple(row for row in rows if row["due_date"] >= today)
            return {
                "overdue_amount": round(sum(float(row["total_amount"]) for row in overdue), 2),
                "overdue_count": len(overdue),
                "due_today_amount": round(sum(float(row["total_amount"]) for row in due_today), 2),
                "due_today_count": len(due_today),
                "next_7_amount": round(sum(float(row["total_amount"]) for row in next_7), 2),
                "next_7_count": len(next_7),
                "next_30_amount": round(sum(float(row["total_amount"]) for row in next_30), 2),
                "next_30_count": len(next_30),
                "debtor_balance": round(sum(float(row["balance"]) for row in debtor_rows), 2),
                "debtor_clients": len(debtor_rows),
                "overdue_rows": tuple(sorted(overdue, key=lambda row: (row["due_date"], row["client_name"]))[:5]),
                "upcoming_rows": tuple(sorted(upcoming, key=lambda row: (row["due_date"], row["client_name"]))[:5]),
            }
        except Exception:
            return empty

    def view_spec(self, *, demo_mode: bool = False) -> DashboardViewSpec:
        summary = self.summary()
        collections = self.collection_snapshot()
        quick_actions = (
            QuickActionSpec("Nueva orden de carga", "load_orders.new", True),
            QuickActionSpec("Buscar orden", "load_orders.search", True),
            QuickActionSpec("Nuevo cliente", "clients.new", True),
            QuickActionSpec("Registrar remito", "remittances.new", True),
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
            "Próximo módulo: F150.",
        ]
        if demo_mode:
            alerts.append("Modo demo visual con datos de prueba.")
        collection_cards = (
            CollectionCardSpec(
                "Presupuestos vencidos",
                collections["overdue_amount"],
                collections["overdue_count"],
                "collection_due_report",
            ),
            CollectionCardSpec(
                "Vence hoy",
                collections["due_today_amount"],
                collections["due_today_count"],
                "collection_due_report",
            ),
            CollectionCardSpec(
                "Próximos 7 días",
                collections["next_7_amount"],
                collections["next_7_count"],
                "collection_due_report",
            ),
            CollectionCardSpec(
                "Próximos 30 días",
                collections["next_30_amount"],
                collections["next_30_count"],
                "collection_due_report",
            ),
            CollectionCardSpec(
                "Saldo deudor clientes",
                collections["debtor_balance"],
                collections["debtor_clients"],
                "customer_ledger",
            ),
        )
        return DashboardViewSpec(
            title="Dashboard operativo",
            quick_actions=quick_actions,
            summary_cards=cards,
            alerts=tuple(alerts),
            collection_cards=collection_cards,
            overdue_rows=collections["overdue_rows"],
            upcoming_rows=collections["upcoming_rows"],
        )
