from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from peewee import InterfaceError, OperationalError

from app.config.database import database_proxy
from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, Driver, Product
from app.models.system import BackupLog
from app.reports.collection_due_report import CollectionDueFilters, CollectionDueReportService
from app.services.collection_exposure_service import (
    CollectionExposureService,
    client_balances_by_id,
)


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
    unit: str = "presupuesto"
    unit_plural: str = "presupuestos"
    tooltip: str = ""


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
        """
        Fotografia de cobranzas para las tarjetas del dashboard.

        Los importes son **exposicion por cliente**: lo que se puede exigir hoy
        de cada cliente, nunca mas que su saldo real. Los pagos y creditos de
        cuenta corriente ya estan descontados del saldo, asi que un cliente
        que pago no aparece con toda la masa de documentos vencidos que le
        quedaron en el historial.

        El detalle documento a documento (importe bruto de cada presupuesto) vive
        en el informe de vencimientos y en los paneles de detalle.
        """
        today = today or date.today()
        empty = {
            "overdue_amount": 0.0,
            "overdue_clients": 0,
            "due_today_amount": 0.0,
            "due_today_clients": 0,
            "next_7_amount": 0.0,
            "next_7_clients": 0,
            "next_30_amount": 0.0,
            "next_30_clients": 0,
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
            balances = client_balances_by_id()
            exposure = CollectionExposureService().snapshot(
                today=today,
                rows=rows,
                balances=balances,
            )
            overdue = tuple(row for row in rows if row["due_date"] < today)
            upcoming = tuple(row for row in rows if row["due_date"] >= today)
            debtor_balances = [
                balance for balance in balances.values() if balance > Decimal("0.01")
            ]
            return {
                "overdue_amount": exposure.overdue_amount,
                "overdue_clients": exposure.overdue_clients,
                "due_today_amount": exposure.due_today_amount,
                "due_today_clients": exposure.due_today_clients,
                "next_7_amount": exposure.next_7_amount,
                "next_7_clients": exposure.next_7_clients,
                "next_30_amount": exposure.next_30_amount,
                "next_30_clients": exposure.next_30_clients,
                "debtor_balance": float(sum(debtor_balances, Decimal("0.00"))),
                "debtor_clients": len(debtor_balances),
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
                "Deuda vencida",
                collections["overdue_amount"],
                collections["overdue_clients"],
                "collection_due_report",
                unit="cliente",
                unit_plural="clientes",
                tooltip=(
                    "Exposición por cliente: documentos vencidos menos los pagos y "
                    "créditos ya registrados. No supera la deuda real del cliente."
                ),
            ),
            CollectionCardSpec(
                "Vence hoy",
                collections["due_today_amount"],
                collections["due_today_clients"],
                "collection_due_report",
                unit="cliente",
                unit_plural="clientes",
                tooltip="Exposición por cliente de lo que vence hoy, descontando lo vencido.",
            ),
            CollectionCardSpec(
                "Próximos 7 días",
                collections["next_7_amount"],
                collections["next_7_clients"],
                "collection_due_report",
                unit="cliente",
                unit_plural="clientes",
                tooltip="Exposición por cliente de los próximos 7 días, descontando lo vencido.",
            ),
            CollectionCardSpec(
                "Próximos 30 días",
                collections["next_30_amount"],
                collections["next_30_clients"],
                "collection_due_report",
                unit="cliente",
                unit_plural="clientes",
                tooltip=(
                    "Exposición por cliente de los próximos 30 días (incluye los 7). "
                    "Ventana acumulada, como el informe de vencimientos."
                ),
            ),
            CollectionCardSpec(
                "Saldo deudor clientes",
                collections["debtor_balance"],
                collections["debtor_clients"],
                "customer_ledger",
                unit="cliente",
                unit_plural="clientes",
                tooltip="Suma de los saldos positivos de cuenta corriente.",
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
