from datetime import date

from app.config.database import database_proxy
from app.models.load_orders import (
    LoadOrder,
    LoadOrderBudgetStatus,
    LoadOrderDestination,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
    LoadOrderStatusHistory,
)
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, TipoIVA, Truck
from app.models.system import NumberSequence
from app.services.audit_service import AuditService
from app.services.driver_availability_service import DriverAvailabilityService
from app.services.master_service import MasterService
from app.services.pallet_composition_service import AllocationDraft, PalletCompositionService, PalletDraft, RequestedLine


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
        order_date = self._validate_order_date(order_date)
        carrier, driver, truck = self._validate_logistic_header(carrier, driver, truck)
        normalized_destinations = self._validate_destinations(
            destinations,
            legacy_client=client,
            legacy_delivery_address=delivery_address,
            legacy_products=products,
        )
        normalized_pallets = self._validate_pallets(pallets, normalized_destinations)
        self.driver_availability.ensure_available(driver)
        with database_proxy.atomic():
            order = LoadOrder.create(
                order_number=self._next_order_number(),
                date=order_date,
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
        destinations = changes.pop("destinations", None)
        pallets = changes.pop("pallets", None)
        normalized_destinations = None
        normalized_pallets = None
        if destinations is not None:
            if not order.is_unissued:
                raise ValueError("Solo se pueden editar clientes y productos de ordenes pendientes.")
            normalized_destinations = self._validate_destinations(
                destinations,
                legacy_client=None,
                legacy_delivery_address=None,
                legacy_products=None,
            )
            if pallets is None:
                normalized_pallets = self._validate_pallets(
                    self._persisted_pallet_payload(order),
                    normalized_destinations,
                )
        if pallets is not None:
            if not order.is_unissued:
                raise ValueError("Solo se pueden editar pallets de ordenes pendientes.")
            pallet_destinations = normalized_destinations or self._persisted_destination_payload(order)
            normalized_pallets = self._validate_pallets(pallets, pallet_destinations)
        new_driver = changes.get("driver")
        candidate_carrier = changes.get("carrier", order.carrier)
        candidate_driver = changes.get("driver", order.driver)
        candidate_truck = changes.get("truck", order.truck)
        self._validate_logistic_header(candidate_carrier, candidate_driver, candidate_truck)
        if "date" in changes:
            changes["date"] = self._validate_order_date(changes["date"], allow_none=False)
        if new_driver is not None and new_driver.id != order.driver.id and order.is_active:
            self.driver_availability.ensure_available(new_driver, excluding_order=order)
            previous_driver = order.driver
        else:
            previous_driver = None
        for field, value in changes.items():
            if hasattr(order, field):
                setattr(order, field, value)
        order.updated_by = self.current_user
        with database_proxy.atomic():
            order.save()
            if normalized_destinations is not None:
                self._replace_destinations(order, normalized_destinations)
            if normalized_pallets is not None:
                self._replace_pallets(order, normalized_pallets)
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
        return LoadOrder.select().where(
            LoadOrder.status.not_in((LoadOrder.STATUS_ISSUED, *LoadOrder.FINAL_STATUSES))
        ).count()

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
        self._require_active(carrier, "transportista")
        self._require_active(driver, "chofer")
        self._require_active(truck, "camion")
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
            self._require_active(client, "cliente")
            self._require_active(delivery_address, "lugar de entrega")
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
            self._require_active(product, "producto")
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

    def _validate_pallets(self, pallets: list[dict], destinations: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        valid_lines = {
            (destination["client"].id, destination["delivery_address"].id, product["product"].id): (
                destination,
                product,
            )
            for destination in destinations
            for product in destination["products"]
        }
        next_sequence = 1
        for item in pallets or []:
            if not isinstance(item, dict):
                raise ValueError("Cada pallet de la orden debe ser un detalle valido.")
            pallet_type = item.get("pallet_type")
            if pallet_type is not None:
                pallet_type = self._require_instance(pallet_type, PalletType, "pallet")
            requested_copies = item.get("quantity", 1) if "sequence" not in item and not item.get("allocations") else 1
            if requested_copies is None or requested_copies <= 0:
                raise ValueError("La cantidad de pallet debe ser mayor a cero.")
            for copy_index in range(int(requested_copies)):
                sequence = item.get("sequence") if copy_index == 0 else None
                sequence = sequence or next_sequence
                if sequence <= 0 or any(existing["sequence"] == sequence for existing in normalized):
                    raise ValueError("El numero de pallet debe ser positivo y unico dentro de la orden.")
                allocations = []
                seen_lines: set[tuple[int, int, int]] = set()
                for allocation in item.get("allocations") or []:
                    if not isinstance(allocation, dict):
                        raise ValueError("Cada asignacion de pallet debe ser un detalle valido.")
                    client = self._require_instance(allocation.get("client"), Client, "cliente")
                    address = self._require_instance(
                        allocation.get("delivery_address"), ClientAddress, "lugar de entrega"
                    )
                    product = self._require_instance(allocation.get("product"), Product, "producto")
                    key = (client.id, address.id, product.id)
                    if key not in valid_lines:
                        raise ValueError("La mercaderia asignada al pallet no pertenece a la orden.")
                    if key in seen_lines:
                        raise ValueError("El articulo ya esta asignado a este pallet para el mismo destino.")
                    quantity = allocation.get("quantity")
                    if quantity is None or quantity <= 0:
                        raise ValueError("La cantidad asignada al pallet debe ser mayor a cero.")
                    seen_lines.add(key)
                    allocations.append(
                        {
                            "client": client,
                            "delivery_address": address,
                            "product": product,
                            "quantity": quantity,
                            "peso_unitario_kg": allocation.get("peso_unitario_kg", product.peso_unitario_kg),
                        }
                    )
                normalized.append(
                    {
                        **item,
                        "sequence": sequence,
                        "pallet_type": pallet_type,
                        "quantity": 1,
                        "allocations": allocations,
                    }
                )
                next_sequence = max(next_sequence, sequence + 1)

        result = PalletCompositionService().reconcile(
            requested=self._requested_lines(destinations),
            pallets=self._draft_pallets(normalized),
        )
        excess = [issue.message for issue in result.issues if issue.code == "excess"]
        if excess:
            raise ValueError(" ".join(excess))
        return normalized

    def _persisted_destination_payload(self, order: LoadOrder) -> list[dict]:
        return [
            {
                "client": destination.client,
                "delivery_address": destination.delivery_address,
                "products": [
                    {"product": product.product, "quantity": product.quantity}
                    for product in destination.products
                ],
            }
            for destination in order.destinations
        ]

    def _persisted_pallet_payload(self, order: LoadOrder) -> list[dict]:
        return [
            {
                "sequence": pallet.sequence,
                "pallet_type": pallet.pallet_type,
                "measure": pallet.measure,
                "weight": pallet.weight,
                "observations": pallet.observations,
                "allocations": [
                    {
                        "client": allocation.destination.client,
                        "delivery_address": allocation.destination.delivery_address,
                        "product": allocation.product,
                        "quantity": allocation.quantity,
                        "peso_unitario_kg": allocation.peso_unitario_kg,
                    }
                    for allocation in pallet.allocations
                ],
            }
            for pallet in order.pallets.order_by(LoadOrderPallet.sequence)
        ]

    def _requested_lines(self, destinations: list[dict]) -> list[RequestedLine]:
        return [
            RequestedLine(
                destination_id=destination["delivery_address"].id,
                product_id=product["product"].id,
                quantity=product["quantity"],
                label=(
                    f"{destination['client'].name} / {destination['delivery_address'].address} / "
                    f"{product['product'].name}"
                ),
            )
            for destination in destinations
            for product in destination["products"]
        ]

    def _draft_pallets(self, pallets: list[dict]) -> list[PalletDraft]:
        return [
            PalletDraft(
                sequence=pallet["sequence"],
                allocations=tuple(
                    AllocationDraft(
                        destination_id=allocation["delivery_address"].id,
                        product_id=allocation["product"].id,
                        quantity=allocation["quantity"],
                        peso_unitario_kg=allocation["peso_unitario_kg"],
                        label=(
                            f"{allocation['client'].name} / {allocation['delivery_address'].address} / "
                            f"{allocation['product'].name}"
                        ),
                    )
                    for allocation in pallet["allocations"]
                ),
            )
            for pallet in pallets
        ]

    def _require_instance(self, value, model_class, label: str):
        if value is None:
            raise ValueError(f"El {label} es obligatorio.")
        if not isinstance(value, model_class) or value.id is None:
            raise ValueError(f"El {label} no es valido.")
        try:
            return model_class.get_by_id(value.id)
        except model_class.DoesNotExist as exc:
            raise ValueError(f"El {label} no existe.") from exc

    def _require_active(self, value, label: str) -> None:
        if hasattr(value, "active") and value.active is False:
            raise ValueError(f"El {label} esta inactivo.")

    def _validate_order_date(self, value, *, allow_none: bool = True) -> date:
        if value is None:
            if allow_none:
                return date.today()
            raise ValueError("La fecha de la orden es obligatoria.")
        if not isinstance(value, date):
            raise ValueError("La fecha de la orden no es valida.")
        return value

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

    def _calculate_product_prices(self, product_item: dict, destination_client: Client) -> dict:
        product = product_item["product"]
        quantity = product_item["quantity"]
        precio = product_item.get("precio_neto_unitario")
        if precio is None:
            precio = self._price_for_client_list(product, destination_client)
        descuento = product_item.get("descuento_porcentaje")
        if descuento is None:
            descuento = destination_client.descuento_porcentaje or 0.0
        iva_porcentaje = product_item.get("iva_porcentaje")
        if iva_porcentaje is None:
            tipo_iva = product.tipo_iva
            iva_porcentaje = tipo_iva.porcentaje if tipo_iva else TipoIVA.iva_default().porcentaje
        neto_subtotal = quantity * precio
        descuento_importe = neto_subtotal * descuento / 100.0
        neto_gravado = neto_subtotal - descuento_importe
        iva_importe = neto_gravado * iva_porcentaje / 100.0
        total = neto_gravado + iva_importe
        return {
            "precio_neto_unitario": precio,
            "descuento_porcentaje": descuento,
            "neto_subtotal": neto_subtotal,
            "descuento_importe": descuento_importe,
            "neto_gravado": neto_gravado,
            "iva_porcentaje": iva_porcentaje,
            "iva_importe": iva_importe,
            "total": total,
        }

    def _price_for_client_list(self, product: Product, client: Client) -> float:
        price_list = client.lista_precios or 1
        if price_list not in (1, 2, 3, 4):
            raise ValueError("La lista de precios del cliente debe ser 1, 2, 3 o 4.")
        value = getattr(product, f"precio_lista_{price_list}") or 0.0
        if value:
            return value
        return product.precio_neto_base or 0.0

    def _replace_destinations(self, order: LoadOrder, destinations: list[dict]) -> None:
        LoadOrderProduct.delete().where(LoadOrderProduct.order == order).execute()
        LoadOrderDestination.delete().where(LoadOrderDestination.order == order).execute()
        LoadOrderBudgetStatus.delete().where(LoadOrderBudgetStatus.order == order).execute()
        for item in destinations:
            client = item["client"]
            destination = LoadOrderDestination.create(
                order=order,
                client=client,
                delivery_address=item["delivery_address"],
                sequence=item["sequence"],
                observations=item.get("observations"),
            )
            for product_item in item["products"]:
                product = product_item["product"]
                prices = self._calculate_product_prices(product_item, client)
                LoadOrderProduct.create(
                    order=order,
                    destination=destination,
                    product=product,
                    quantity=product_item["quantity"],
                    unit=product_item.get("unit") or product.unit,
                    observations=product_item.get("observations"),
                    **prices,
                )
            budget, _ = LoadOrderBudgetStatus.get_or_create(
                order=order,
                client=client,
                defaults={"status": LoadOrderBudgetStatus.STATUS_PENDING},
            )

    def _replace_pallets(self, order: LoadOrder, pallets: list[dict]) -> None:
        LoadOrderPalletAllocation.delete().where(
            LoadOrderPalletAllocation.pallet.in_(
                LoadOrderPallet.select(LoadOrderPallet.id).where(LoadOrderPallet.order == order)
            )
        ).execute()
        LoadOrderPallet.delete().where(LoadOrderPallet.order == order).execute()
        persisted_destinations = {
            (destination.client.id, destination.delivery_address.id): destination
            for destination in order.destinations
        }
        for item in pallets:
            pallet_type = item["pallet_type"]
            pallet = LoadOrderPallet.create(
                order=order,
                pallet_type=pallet_type,
                sequence=item["sequence"],
                measure=item.get("measure") or (pallet_type.measure if pallet_type else ""),
                weight=item.get("weight") if item.get("weight") is not None else 0,
                quantity=1,
                observations=item.get("observations"),
            )
            for allocation in item["allocations"]:
                destination = persisted_destinations[(allocation["client"].id, allocation["delivery_address"].id)]
                LoadOrderPalletAllocation.create(
                    pallet=pallet,
                    destination=destination,
                    product=allocation["product"],
                    quantity=allocation["quantity"],
                    peso_unitario_kg=allocation["peso_unitario_kg"],
                )

    def composition(self, order: LoadOrder):
        order = LoadOrder.get_by_id(order.id)
        requested = [
            RequestedLine(
                destination_id=product.destination.id,
                product_id=product.product.id,
                quantity=product.quantity,
                label=(
                    f"{product.destination.client.name} / {product.destination.delivery_address.address} / "
                    f"{product.product.name}"
                ),
            )
            for product in order.products
            if product.destination_id is not None
        ]
        pallets = [
            PalletDraft(
                sequence=pallet.sequence,
                allocations=tuple(
                    AllocationDraft(
                        destination_id=allocation.destination.id,
                        product_id=allocation.product.id,
                        quantity=allocation.quantity,
                        peso_unitario_kg=allocation.peso_unitario_kg,
                        label=(
                            f"{allocation.destination.client.name} / "
                            f"{allocation.destination.delivery_address.address} / {allocation.product.name}"
                        ),
                    )
                    for allocation in pallet.allocations
                ),
            )
            for pallet in order.pallets.order_by(LoadOrderPallet.sequence)
        ]
        return PalletCompositionService().reconcile(requested=requested, pallets=pallets)

    def _snapshot(self, order: LoadOrder) -> dict:
        return {
            "order_number": order.order_number,
            "status": order.status,
            "client_ids": [destination.client.id for destination in order.destinations],
            "driver_id": order.driver.id,
            "truck_id": order.truck.id,
        }
