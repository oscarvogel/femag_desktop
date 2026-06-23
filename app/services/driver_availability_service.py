from app.models.load_orders import LoadOrder
from app.models.masters import Driver
from app.services.audit_service import AuditService


class DriverAvailabilityService:
    def __init__(self, current_user: str | None = None, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def ensure_available(self, driver: Driver, *, excluding_order: LoadOrder | None = None) -> None:
        driver = Driver.get_by_id(driver.id)
        active_query = LoadOrder.select().where(
            LoadOrder.driver == driver,
            LoadOrder.status.in_(LoadOrder.ACTIVE_STATUSES),
        )
        if excluding_order is not None:
            active_query = active_query.where(LoadOrder.id != excluding_order.id)
        if not driver.available or active_query.exists():
            raise ValueError(f"El chofer {driver.name} esta bloqueado por una carga activa.")

    def lock_driver(self, driver: Driver, order: LoadOrder) -> None:
        Driver.update(available=False).where(Driver.id == driver.id).execute()
        self.audit_service.record(
            user=self.current_user,
            module="Ordenes de carga",
            action="bloquear chofer",
            record_ref=f"LoadOrder:{order.id}",
            new_value={"driver_id": driver.id, "order_number": order.order_number},
        )

    def release_driver(self, driver: Driver, order: LoadOrder) -> None:
        active_other_orders = (
            LoadOrder.select()
            .where(
                LoadOrder.driver == driver,
                LoadOrder.status.in_(LoadOrder.ACTIVE_STATUSES),
                LoadOrder.id != order.id,
            )
            .exists()
        )
        if not active_other_orders:
            Driver.update(available=True).where(Driver.id == driver.id).execute()
        self.audit_service.record(
            user=self.current_user,
            module="Ordenes de carga",
            action="liberar chofer",
            record_ref=f"LoadOrder:{order.id}",
            new_value={"driver_id": driver.id, "order_number": order.order_number},
        )

    def available_drivers(self):
        active_driver_ids = (
            LoadOrder.select(LoadOrder.driver)
            .where(LoadOrder.status.in_(LoadOrder.ACTIVE_STATUSES))
            .tuples()
        )
        blocked_ids = [row[0] for row in active_driver_ids]
        query = Driver.select().where(Driver.active == True, Driver.available == True)  # noqa: E712
        if blocked_ids:
            query = query.where(Driver.id.not_in(blocked_ids))
        return list(query.order_by(Driver.name))
