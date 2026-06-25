from datetime import date

from app.config.database import database_proxy
from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderPallet,
    LoadOrderProduct,
    LoadOrderStatusHistory,
)
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck
from app.models.system import NumberSequence
from app.services.audit_service import AuditService
from app.services.driver_availability_service import DriverAvailabilityService
from app.services.master_service import MasterService


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
        client: Client | None = None,
        delivery_address: ClientAddress | None = None,
        carrier: Carrier,
        driver: Driver,
        truck: Truck,
        products: list[dict] | None = None,
        destinations: list[dict] | None = None,
        pallets: list[dict] | None = None,
        observations: str | None = None,
        order_date: date | None = None,
    ) -> LoadOrder:
        carrier, driver, truck = self._validate_logistic_header(carrier, driver, truck)
        normalized_destinations = self._validate_destinations(
            destinations,
            legacy_client=client,
            legacy_delivery_address=delivery_address,
            legacy_products=products,
        )
        normalized_pallets = self._validate_pallets(pallets)
        self.driver_availability.ensure_available(driver)
        with database_proxy.atomic():
            order = LoadOrder.create(
                order_number=self._next_order_number(),
                date=order_date or date.today(),
                client=None,
                delivery_address=None,
                carrier=carrier,
                driver=driver,
                truck=truck,
                observations=observations,
                created_by=self.current_user,
                updated_by=self.current_user,
            )
            self._replace_destinations(order, normalized_destinations)
            self._replace_pallets(order, normalized_pallets)
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
        if "status" in changes:
            raise ValueError("El estado de la orden debe cambiarse con change_status o annul_order.")
        order = LoadOrder.get_by_id(order.id)
        old_snapshot = self._snapshot(order)
        new_driver = changes.get("driver")
        candidate_carrier = changes.get("carrier", order.carrier)
        candidate_driver = changes.get("driver", order.driver)
        candidate_truck = changes.get("truck", order.truck)
        self._validate_logistic_header(candidate_carrier, candidate_driver, candidate_truck)
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

    def list_orders(
        self,
        *,
        status: str | None = None,
        client: Client | None = None,
        day: date | None = None,
    ) -> list[LoadOrder]:
        query = LoadOrder.select()
        if status is not None:
            query = query.where(LoadOrder.status == status)
        if client is not None:
            client = self._require_instance(client, Client, "cliente")
            destination_orders = LoadOrderDestination.select(LoadOrderDestination.order).where(
                LoadOrderDestination.client == client
            )
            query = query.where((LoadOrder.client == client) | (LoadOrder.id.in_(destination_orders)))
        if day is not None:
            query = query.where(LoadOrder.date == day)
        return list(query.order_by(LoadOrder.date.desc(), LoadOrder.order_number.desc()))

    def _validate_logistic_header(
        self,
        carrier: Carrier,
        driver: Driver,
        truck: Truck,
    ) -> tuple[Carrier, Driver, Truck]:
        carrier = self._require_instance(carrier, Carrier, "transportista")
        driver = self._require_instance(driver, Driver, "chofer")
        truck = self._require_instance(truck, Truck, "camion")
        if truck.carrier.id != carrier.id:
            raise ValueError("El camion debe pertenecer al transportista seleccionado.")
        master_service = MasterService(current_user=self.current_user, audit_service=self.audit_service)
        if not master_service.is_driver_valid_for_carrier(driver, carrier):
            raise ValueError("El chofer debe pertenecer al transportista seleccionado.")
        if not master_service.is_driver_valid_for_truck(driver, truck):
            raise ValueError("El chofer debe ser valido para el camion seleccionado.")
        return carrier, driver, truck

    def _validate_destinations(
        self,
        destinations: list[dict] | None,
        *,
        legacy_client: Client | None,
        legacy_delivery_address: ClientAddress | None,
        legacy_products: list[dict] | None,
    ) -> list[dict]:
        if destinations is None:
            destinations = [
                {
                    "client": legacy_client,
                    "delivery_address": legacy_delivery_address,
                    "products": legacy_products or [],
                }
            ]
        if not destinations:
            raise ValueError("La orden debe tener al menos un cliente con productos.")
        normalized = []
        for index, item in enumerate(destinations, start=1):
            if not isinstance(item, dict):
                raise ValueError("Cada cliente de la orden debe ser un detalle valido.")
            client = self._require_instance(item.get("client"), Client, "cliente")
            delivery_address = self._require_instance(item.get("delivery_address"), ClientAddress, "lugar de entrega")
            if delivery_address.client.id != client.id:
                raise ValueError("El lugar de entrega debe pertenecer al cliente seleccionado.")
            products = item.get("products") or []
            if not products:
                raise ValueError("Cada cliente de la orden debe tener al menos un producto.")
            normalized.append(
                {
                    "client": client,
                    "delivery_address": delivery_address,
                    "sequence": item.get("sequence") or index,
                    "observations": item.get("observations"),
                    "products": self._validate_products(products),
                }
            )
        return normalized

    def _validate_products(self, products: list[dict]) -> list[dict]:
        if not products:
            raise ValueError("La orden debe tener al menos un producto.")
        normalized = []
        for item in products:
            if not isinstance(item, dict):
                raise ValueError("Cada producto de la orden debe ser un detalle valido.")
            product = self._require_instance(item.get("product"), Product, "producto")
            quantity = item.get("quantity")
            if quantity is None or quantity <= 0:
                raise ValueError("La cantidad de producto debe ser mayor a cero.")
            normalized.append(
                {
                    **item,
                    "product": product,
                    "quantity": quantity,
                }
            )
        return normalized

    def _validate_pallets(self, pallets: list[dict]) -> list[dict]:
        normalized = []
        for item in pallets or []:
            if not isinstance(item, dict):
                raise ValueError("Cada pallet de la orden debe ser un detalle valido.")
            pallet_type = self._require_instance(item.get("pallet_type"), PalletType, "pallet")
            quantity = item.get("quantity")
            if quantity is None or quantity <= 0:
                raise ValueError("La cantidad de pallet debe ser mayor a cero.")
            normalized.append(
                {
                    **item,
                    "pallet_type": pallet_type,
                    "quantity": quantity,
                }
            )
        return normalized

    def _require_instance(self, value, model_class, label: str):
        if value is None:
            raise ValueError(f"El {label} es obligatorio.")
        if not isinstance(value, model_class) or value.id is None:
            raise ValueError(f"El {label} no es valido.")
        try:
            return model_class.get_by_id(value.id)
        except model_class.DoesNotExist as exc:
            raise ValueError(f"El {label} no existe.") from exc

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

    def _replace_destinations(self, order: LoadOrder, destinations: list[dict]) -> None:
        LoadOrderProduct.delete().where(LoadOrderProduct.order == order).execute()
        LoadOrderDestination.delete().where(LoadOrderDestination.order == order).execute()
        for item in destinations:
            destination = LoadOrderDestination.create(
                order=order,
                client=item["client"],
                delivery_address=item["delivery_address"],
                sequence=item["sequence"],
                observations=item.get("observations"),
            )
            for product_item in item["products"]:
                product = product_item["product"]
                LoadOrderProduct.create(
                    order=order,
                    destination=destination,
                    product=product,
                    quantity=product_item["quantity"],
                    unit=product_item.get("unit") or product.unit,
                    observations=product_item.get("observations"),
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

    def _snapshot(self, order: LoadOrder) -> dict:
        return {
            "order_number": order.order_number,
            "status": order.status,
            "client_ids": [destination.client.id for destination in order.destinations],
            "driver_id": order.driver.id,
            "truck_id": order.truck.id,
        }
