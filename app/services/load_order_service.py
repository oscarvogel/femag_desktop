from datetime import date

from app.config.database import database_proxy
from app.models.load_orders import LoadOrder, LoadOrderLine, LoadOrderStatusHistory
from app.models.masters import Carrier, Client, Driver, Truck
from app.models.system import NumberSequence
from app.services.audit_service import AuditService
from app.services.driver_availability_service import DriverAvailabilityService


class LoadOrderService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()
        self.driver_availability = DriverAvailabilityService(current_user, self.audit_service)

    def _next_order_number(self) -> int:
        sequence, _ = NumberSequence.get_or_create(name="load_order", defaults={"current_number": 0})
        sequence.current_number += 1
        sequence.save()
        return sequence.current_number

    def create_order(
        self,
        *,
        header_client: Client | None = None,
        header_client_text: str | None = None,
        destination: str,
        carrier: Carrier,
        driver: Driver,
        truck: Truck,
        lines: list[dict],
        vehicle_clean_and_suitable: bool = True,
        observations: str | None = None,
        order_date: date | None = None,
    ) -> LoadOrder:
        if not lines:
            raise ValueError("La orden debe tener al menos un renglon de despacho.")
        if not (header_client or header_client_text):
            raise ValueError("La orden debe indicar cliente de cabecera o texto de cabecera.")
        if not destination:
            raise ValueError("La orden debe indicar un destino general.")
        self.driver_availability.ensure_available(driver)
        with database_proxy.atomic():
            order = LoadOrder.create(
                order_number=self._next_order_number(),
                date=order_date or date.today(),
                header_client=header_client,
                header_client_text=header_client_text,
                destination=destination,
                carrier=carrier,
                driver=driver,
                truck=truck,
                vehicle_clean_and_suitable=vehicle_clean_and_suitable,
                observations=observations,
                created_by=self.current_user,
                updated_by=self.current_user,
            )
            self._replace_lines(order, lines)
            LoadOrderStatusHistory.create(
                order=order,
                old_status=None,
                new_status=order.status,
                user=self.current_user,
                observation="Creacion de orden",
            )
            self.driver_availability.lock_driver(driver, order)
            self.audit_service.record(
                user=self.current_user,
                module="Ordenes de carga",
                action="crear",
                record_ref=f"LoadOrder:{order.id}",
                new_value=self._snapshot(order),
            )
            return order

    def update_order(self, order: LoadOrder, **changes) -> LoadOrder:
        order = LoadOrder.get_by_id(order.id)
        old_snapshot = self._snapshot(order)
        new_driver = changes.get("driver")
        if new_driver is not None and new_driver.id != order.driver.id and order.is_active:
            self.driver_availability.ensure_available(new_driver, excluding_order=order)
            previous_driver = order.driver
        else:
            previous_driver = None
        for field, value in changes.items():
            if hasattr(order, field):
                setattr(order, field, value)
        order.updated_by = self.current_user
        order.save()
        if previous_driver is not None:
            self.driver_availability.release_driver(previous_driver, order)
            self.driver_availability.lock_driver(order.driver, order)
        self.audit_service.record(
            user=self.current_user,
            module="Ordenes de carga",
            action="modificar",
            record_ref=f"LoadOrder:{order.id}",
            old_value=old_snapshot,
            new_value=self._snapshot(order),
        )
        return order

    def change_status(self, order: LoadOrder, status: str, reason: str | None = None) -> LoadOrder:
        if status not in (*LoadOrder.ACTIVE_STATUSES, *LoadOrder.FINAL_STATUSES):
            raise ValueError(f"Estado de orden invalido: {status}")
        order = LoadOrder.get_by_id(order.id)
        old_status = order.status
        if old_status == status:
            return order
        if old_status in LoadOrder.FINAL_STATUSES and status in LoadOrder.ACTIVE_STATUSES:
            self.driver_availability.ensure_available(order.driver, excluding_order=order)
        order.status = status
        order.updated_by = self.current_user
        order.save()
        LoadOrderStatusHistory.create(
            order=order,
            old_status=old_status,
            new_status=status,
            user=self.current_user,
            observation=reason,
        )
        if status in LoadOrder.FINAL_STATUSES:
            self.driver_availability.release_driver(order.driver, order)
        elif status in LoadOrder.ACTIVE_STATUSES:
            self.driver_availability.lock_driver(order.driver, order)
        self.audit_service.record(
            user=self.current_user,
            module="Ordenes de carga",
            action="cambiar estado",
            record_ref=f"LoadOrder:{order.id}",
            old_value={"status": old_status},
            new_value={"status": status, "reason": reason},
        )
        return order

    def annul_order(self, order: LoadOrder, *, can_annul: bool, reason: str | None = None) -> LoadOrder:
        if not can_annul:
            raise PermissionError("No tiene permiso para anular ordenes de carga.")
        annulled = self.change_status(order, LoadOrder.STATUS_ANNULLED, reason=reason)
        self.audit_service.record(
            user=self.current_user,
            module="Ordenes de carga",
            action="anular",
            record_ref=f"LoadOrder:{annulled.id}",
            new_value={"status": annulled.status, "reason": reason},
        )
        return annulled

    def pending_count(self) -> int:
        return LoadOrder.select().where(LoadOrder.status == LoadOrder.STATUS_PENDING).count()

    def today_count(self, day: date | None = None) -> int:
        return LoadOrder.select().where(LoadOrder.date == (day or date.today())).count()

    def blocked_driver_count(self) -> int:
        return Driver.select().where(Driver.available == False).count()  # noqa: E712

    def presentation_totals(self, order: LoadOrder) -> dict[str, int]:
        totals = {"bags_25kg": 0, "bags_10kg": 0, "pack": 0, "pallet": 0}
        for line in order.lines:
            totals["bags_25kg"] += line.bags_25kg or 0
            totals["bags_10kg"] += line.bags_10kg or 0
            totals["pack"] += line.pack or 0
            totals["pallet"] += line.pallet or 0
        return totals

    def _replace_lines(self, order: LoadOrder, lines: list[dict]) -> None:
        LoadOrderLine.delete().where(LoadOrderLine.order == order).execute()
        for item in lines:
            LoadOrderLine.create(
                order=order,
                client=item.get("client"),
                recipient_text=item.get("recipient_text"),
                destination_text=item.get("destination_text"),
                product=item.get("product"),
                product_detail=item.get("product_detail"),
                bags_25kg=item.get("bags_25kg", 0),
                bags_10kg=item.get("bags_10kg", 0),
                pack=item.get("pack", 0),
                pallet=item.get("pallet", 0),
                lot_number=item.get("lot_number"),
                production_date=self._as_date(item.get("production_date")),
                observations=item.get("observations"),
            )

    def _as_date(self, value) -> date | None:
        if value is None or isinstance(value, date):
            return value
        return date.fromisoformat(value)

    def _snapshot(self, order: LoadOrder) -> dict:
        return {
            "order_number": order.order_number,
            "status": order.status,
            "header_client_id": order.header_client.id if order.header_client else None,
            "header_client_text": order.header_client_text,
            "destination": order.destination,
            "driver_id": order.driver.id,
            "truck_id": order.truck.id,
        }
