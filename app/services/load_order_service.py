from datetime import date

from app.config.database import database_proxy
from app.models.load_orders import LoadOrder, LoadOrderPallet, LoadOrderProduct, LoadOrderStatusHistory
from app.models.masters import Carrier, Client, ClientAddress, Driver, Truck
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
        client: Client,
        delivery_address: ClientAddress,
        carrier: Carrier,
        driver: Driver,
        truck: Truck,
        products: list[dict],
        pallets: list[dict],
        observations: str | None = None,
        order_date: date | None = None,
        require_order_date: bool = False,
    ) -> LoadOrder:
        effective_date = order_date or date.today()
        if require_order_date and order_date is None:
            raise ValueError("La fecha de la orden es obligatoria.")
        self._validate_header(
            client=client,
            delivery_address=delivery_address,
            carrier=carrier,
            driver=driver,
            truck=truck,
            order_date=effective_date,
        )
        self._validate_products(products)
        self._validate_pallets(pallets)
        self.driver_availability.ensure_available(driver)
        with database_proxy.atomic():
            order = LoadOrder.create(
                order_number=self._next_order_number(),
                date=effective_date,
                client=client,
                delivery_address=delivery_address,
                carrier=carrier,
                driver=driver,
                truck=truck,
                observations=observations,
                created_by=self.current_user,
                updated_by=self.current_user,
            )
            self._replace_products(order, products)
            self._replace_pallets(order, pallets)
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
        products = changes.pop("products", None)
        pallets = changes.pop("pallets", None)
        if "order_date" in changes:
            changes["date"] = changes.pop("order_date")
        self._validate_header(
            client=changes.get("client", order.client),
            delivery_address=changes.get("delivery_address", order.delivery_address),
            carrier=changes.get("carrier", order.carrier),
            driver=changes.get("driver", order.driver),
            truck=changes.get("truck", order.truck),
            order_date=changes.get("date", order.date),
        )
        if products is not None:
            self._validate_products(products)
        if pallets is not None:
            self._validate_pallets(pallets)
        new_driver = changes.get("driver")
        if new_driver is not None and new_driver.id != order.driver.id and order.is_active:
            self.driver_availability.ensure_available(new_driver, excluding_order=order)
            previous_driver = order.driver
        else:
            previous_driver = None
        with database_proxy.atomic():
            for field, value in changes.items():
                if hasattr(order, field):
                    setattr(order, field, value)
            order.updated_by = self.current_user
            order.save()
            if products is not None:
                self._replace_products(order, products)
            if pallets is not None:
                self._replace_pallets(order, pallets)
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
        if status == LoadOrder.STATUS_ISSUED:
            self._ensure_complete_for_issue(order)
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

    def list_orders(self, *, limit: int = 100) -> list[dict]:
        query = (
            LoadOrder.select()
            .order_by(LoadOrder.date.desc(), LoadOrder.order_number.desc())
            .limit(limit)
        )
        return [self._row(order) for order in query]

    def _replace_products(self, order: LoadOrder, products: list[dict]) -> None:
        LoadOrderProduct.delete().where(LoadOrderProduct.order == order).execute()
        for item in products:
            product = item["product"]
            LoadOrderProduct.create(
                order=order,
                product=product,
                quantity=item["quantity"],
                unit=item.get("unit") or product.unit,
                observations=item.get("observations"),
            )

    def _replace_pallets(self, order: LoadOrder, pallets: list[dict]) -> None:
        LoadOrderPallet.delete().where(LoadOrderPallet.order == order).execute()
        for item in pallets:
            pallet_type = item["pallet_type"]
            LoadOrderPallet.create(
                order=order,
                pallet_type=pallet_type,
                measure=item.get("measure") or pallet_type.measure,
                weight=item.get("weight") if item.get("weight") is not None else pallet_type.weight,
                quantity=item["quantity"],
                observations=item.get("observations"),
            )

    def _validate_header(
        self,
        *,
        client: Client | None,
        delivery_address: ClientAddress | None,
        carrier: Carrier | None,
        driver: Driver | None,
        truck: Truck | None,
        order_date: date | None,
    ) -> None:
        if client is None:
            raise ValueError("El cliente es obligatorio.")
        if delivery_address is None:
            raise ValueError("El domicilio de entrega es obligatorio.")
        if carrier is None:
            raise ValueError("El transportista es obligatorio.")
        if driver is None:
            raise ValueError("El chofer es obligatorio.")
        if truck is None:
            raise ValueError("El camion/patente es obligatorio.")
        if order_date is None:
            raise ValueError("La fecha de la orden es obligatoria.")

    def _validate_products(self, products: list[dict] | None) -> None:
        if not products:
            raise ValueError("La orden debe tener al menos un producto.")
        for item in products:
            product = item.get("product")
            if product is None:
                raise ValueError("El producto es obligatorio.")
            if float(item.get("quantity") or 0) <= 0:
                raise ValueError("La cantidad/pallets debe ser mayor a cero.")

    def _validate_pallets(self, pallets: list[dict] | None) -> None:
        for item in pallets or []:
            if item.get("pallet_type") is None:
                raise ValueError("El tipo de pallet es obligatorio.")
            if int(item.get("quantity") or 0) <= 0:
                raise ValueError("La cantidad/pallets debe ser mayor a cero.")

    def _ensure_complete_for_issue(self, order: LoadOrder) -> None:
        self._validate_header(
            client=order.client,
            delivery_address=order.delivery_address,
            carrier=order.carrier,
            driver=order.driver,
            truck=order.truck,
            order_date=order.date,
        )
        products = [
            {"product": item.product, "quantity": item.quantity}
            for item in LoadOrderProduct.select().where(LoadOrderProduct.order == order)
        ]
        self._validate_products(products)

    def _row(self, order: LoadOrder) -> dict:
        first_product = (
            LoadOrderProduct.select()
            .where(LoadOrderProduct.order == order)
            .order_by(LoadOrderProduct.id)
            .first()
        )
        pallet_count = sum(item.quantity for item in order.pallets)
        return {
            "id": order.id,
            "numero": order.order_number,
            "fecha": order.date,
            "cliente": order.client.name,
            "domicilio_entrega": order.delivery_address.address,
            "destino": f"{order.delivery_address.city}, {order.delivery_address.province}",
            "producto": first_product.product.name if first_product else "",
            "cantidad": first_product.quantity if first_product else 0,
            "pallets": pallet_count,
            "chofer": order.driver.name,
            "transportista": order.carrier.name,
            "camion": order.truck.domain,
            "observaciones": order.observations or "",
            "estado": order.status,
        }

    def _snapshot(self, order: LoadOrder) -> dict:
        return {
            "order_number": order.order_number,
            "status": order.status,
            "client_id": order.client.id,
            "driver_id": order.driver.id,
            "truck_id": order.truck.id,
        }
