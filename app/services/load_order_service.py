from collections import defaultdict
from datetime import date
from decimal import Decimal

from peewee import prefetch

from app.config.database import database_proxy
from app.models.load_orders import (
    LoadOrder,
    LoadOrderBudgetStatus,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
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
from app.services.pallet_composition_service import (
    AllocationDraft,
    LooseAllocationDraft,
    PalletCompositionService,
    PalletDraft,
    RequestedLine,
)


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
        loose_allocations: list[dict] | None = None,
        observations: str | None = None,
        order_date: date | None = None,
        trailer_domain: str | None = None,
    ) -> LoadOrder:
        order_date = self._validate_order_date(order_date)
        carrier, driver, truck = self._validate_logistic_header(carrier, driver, truck)
        trailer_domain = self._validate_trailer_domain(trailer_domain, carrier=carrier)
        normalized_destinations = self._validate_destinations(
            destinations,
            legacy_client=client,
            legacy_delivery_address=delivery_address,
            legacy_products=products,
        )
        normalized_pallets = self._validate_pallets(
            pallets,
            normalized_destinations,
            loose=loose_allocations,
        )
        normalized_loose = self._validate_loose(loose_allocations, normalized_destinations)
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
                trailer_domain=trailer_domain,
                observations=observations,
                created_by=self.current_user,
                updated_by=self.current_user,
            )
            self._replace_destinations(order, normalized_destinations)
            self._replace_pallets(order, normalized_pallets)
            self._replace_loose_allocations(order, normalized_loose)
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
        loose_allocations = changes.pop("loose_allocations", None)
        normalized_destinations = None
        normalized_pallets = None
        normalized_loose = None
        weight_snapshots = self._pallet_weight_snapshots(order)
        loose_weight_snapshots = self._loose_weight_snapshots(order)
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
                    weight_snapshots=weight_snapshots,
                    loose=loose_allocations if loose_allocations is not None else self._persisted_loose_payload(order),
                )
            if loose_allocations is None:
                normalized_loose = self._validate_loose(
                    self._persisted_loose_payload(order),
                    normalized_destinations,
                    weight_snapshots=loose_weight_snapshots,
                )
        if pallets is not None:
            if not order.is_unissued:
                raise ValueError("Solo se pueden editar pallets de ordenes pendientes.")
            pallet_destinations = normalized_destinations or self._persisted_destination_payload(order)
            normalized_pallets = self._validate_pallets(
                pallets,
                pallet_destinations,
                weight_snapshots=weight_snapshots,
                loose=loose_allocations if loose_allocations is not None else self._persisted_loose_payload(order),
            )
        if loose_allocations is not None:
            if not order.is_unissued:
                raise ValueError("Solo se pueden editar pallets de ordenes pendientes.")
            loose_destinations = normalized_destinations or self._persisted_destination_payload(order)
            normalized_loose = self._validate_loose(
                loose_allocations,
                loose_destinations,
                weight_snapshots=loose_weight_snapshots,
            )
            pallets_for_excess = normalized_pallets if normalized_pallets is not None else self._persisted_pallet_payload(order)
            self._raise_if_excess(loose_destinations, pallets_for_excess, loose_allocations)
        new_driver = changes.get("driver")
        candidate_carrier = changes.get("carrier", order.carrier)
        candidate_driver = changes.get("driver", order.driver)
        candidate_truck = changes.get("truck", order.truck)
        self._validate_logistic_header(candidate_carrier, candidate_driver, candidate_truck)
        if "trailer_domain" in changes:
            changes["trailer_domain"] = self._validate_trailer_domain(
                changes["trailer_domain"], carrier=candidate_carrier
            )
        elif (
            "carrier" in changes
            and order.trailer_domain
            and order.trailer_domain not in self._available_trailer_domains(candidate_carrier)
        ):
            raise ValueError(
                "El semi/acoplado seleccionado no pertenece al nuevo transportista."
            )
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
            if normalized_loose is not None:
                self._replace_loose_allocations(order, normalized_loose)
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
        if status == LoadOrder.STATUS_CLOSED:
            raise ValueError(
                "El cierre debe registrarse con LoadOrderClosureService para conservar su trazabilidad."
            )
        persisted_order = LoadOrder.get_by_id(order.id)
        if persisted_order.status == LoadOrder.STATUS_CLOSED and status in LoadOrder.ACTIVE_STATUSES:
            raise ValueError(
                "La reapertura debe registrarse con LoadOrderClosureService para conservar su trazabilidad."
            )
        return self._change_status(persisted_order, status, reason=reason)

    def _change_status(self, order: LoadOrder, status: str, reason: str | None = None) -> LoadOrder:
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
        order_number: int | None = None,
        limit: int | None = None,
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
        if order_number is not None:
            query = query.where(LoadOrder.order_number == order_number)
        query = query.order_by(LoadOrder.date.desc(), LoadOrder.order_number.desc())
        if limit is not None:
            query = query.limit(max(1, int(limit)))
        return list(query)

    def list_orders_page(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
        client: Client | None = None,
        day: date | None = None,
        order_number: int | None = None,
    ) -> tuple[list[LoadOrder], int]:
        """Devuelve una página de órdenes y el total global filtrado.

        La búsqueda se resuelve en SQL sobre toda la base; nunca se limita
        a las filas ya visibles en la grilla.
        """
        page = max(1, int(page))
        page_size = max(1, int(page_size))
        query = LoadOrder.select()
        if client is not None:
            client = self._require_instance(client, Client, "cliente")
            destination_orders = LoadOrderDestination.select(
                LoadOrderDestination.order
            ).where(LoadOrderDestination.client == client)
            query = query.where(
                (LoadOrder.client == client) | (LoadOrder.id.in_(destination_orders))
            )
        if day is not None:
            query = query.where(LoadOrder.date == day)
        if order_number is not None:
            query = query.where(LoadOrder.order_number == order_number)

        term = (search or "").strip()
        if term:
            carrier_ids = Carrier.select(Carrier.id).where(Carrier.name.contains(term))
            driver_ids = Driver.select(Driver.id).where(Driver.name.contains(term))
            truck_ids = Truck.select(Truck.id).where(Truck.domain.contains(term))
            client_ids = Client.select(Client.id).where(Client.name.contains(term))
            address_ids = ClientAddress.select(ClientAddress.id).where(
                ClientAddress.address.contains(term) | ClientAddress.city.contains(term)
            )
            destination_orders = LoadOrderDestination.select(
                LoadOrderDestination.order
            ).where(
                LoadOrderDestination.client.in_(client_ids)
                | LoadOrderDestination.delivery_address.in_(address_ids)
            )
            product_ids = Product.select(Product.id).where(Product.name.contains(term))
            product_orders = LoadOrderProduct.select(LoadOrderProduct.order).where(
                LoadOrderProduct.product.in_(product_ids)
            )

            condition = (
                LoadOrder.status.contains(term)
                | LoadOrder.observations.contains(term)
                | LoadOrder.carrier.in_(carrier_ids)
                | LoadOrder.driver.in_(driver_ids)
                | LoadOrder.truck.in_(truck_ids)
                | LoadOrder.id.in_(destination_orders)
                | LoadOrder.id.in_(product_orders)
            )
            normalized_number = term.upper().replace("OC-", "").strip()
            if normalized_number.isdigit():
                condition = condition | (LoadOrder.order_number == int(normalized_number))
            query = query.where(condition)

        total = query.count()
        rows = list(
            query.order_by(LoadOrder.date.desc(), LoadOrder.order_number.desc())
            .paginate(page, page_size)
        )
        return rows, total

    def build_grid_snapshots(self, orders: list[LoadOrder]) -> dict[int, dict]:
        """Construye datos de grilla en bloque, sin navegar FKs/backrefs por fila."""
        if not orders:
            return {}

        order_ids = [order.id for order in orders]
        carrier_ids = {order.carrier_id for order in orders if order.carrier_id}
        driver_ids = {order.driver_id for order in orders if order.driver_id}
        truck_ids = {order.truck_id for order in orders if order.truck_id}

        carriers = {
            row.id: row.name
            for row in Carrier.select(Carrier.id, Carrier.name).where(Carrier.id.in_(carrier_ids))
        } if carrier_ids else {}
        drivers = {
            row.id: row.name
            for row in Driver.select(Driver.id, Driver.name).where(Driver.id.in_(driver_ids))
        } if driver_ids else {}
        trucks = {
            row.id: row.domain
            for row in Truck.select(Truck.id, Truck.domain).where(Truck.id.in_(truck_ids))
        } if truck_ids else {}

        destination_rows = list(
            LoadOrderDestination.select().where(LoadOrderDestination.order.in_(order_ids))
        )
        client_ids = {row.client_id for row in destination_rows if row.client_id}
        address_ids = {
            row.delivery_address_id for row in destination_rows if row.delivery_address_id
        }
        clients = {
            row.id: row.name
            for row in Client.select(Client.id, Client.name).where(Client.id.in_(client_ids))
        } if client_ids else {}
        addresses = {
            row.id: (row.address, row.city)
            for row in ClientAddress.select(
                ClientAddress.id,
                ClientAddress.address,
                ClientAddress.city,
            ).where(ClientAddress.id.in_(address_ids))
        } if address_ids else {}

        destinations_by_order: dict[int, list[LoadOrderDestination]] = defaultdict(list)
        destination_meta: dict[int, tuple[int, int]] = {}
        for row in destination_rows:
            destinations_by_order[row.order_id].append(row)
            destination_meta[row.id] = (row.client_id, row.delivery_address_id)

        product_rows = list(
            LoadOrderProduct.select().where(LoadOrderProduct.order.in_(order_ids))
        )
        product_ids = {row.product_id for row in product_rows if row.product_id}
        products = {
            row.id: row.name
            for row in Product.select(Product.id, Product.name).where(Product.id.in_(product_ids))
        } if product_ids else {}
        products_by_order: dict[int, list[LoadOrderProduct]] = defaultdict(list)
        for row in product_rows:
            products_by_order[row.order_id].append(row)

        pallet_rows = list(
            LoadOrderPallet.select().where(LoadOrderPallet.order.in_(order_ids))
        )
        pallets_by_order: dict[int, list[LoadOrderPallet]] = defaultdict(list)
        pallet_order: dict[int, int] = {}
        for row in pallet_rows:
            pallets_by_order[row.order_id].append(row)
            pallet_order[row.id] = row.order_id

        pallet_ids = list(pallet_order)
        allocation_rows = list(
            LoadOrderPalletAllocation.select().where(
                LoadOrderPalletAllocation.pallet.in_(pallet_ids)
            )
        ) if pallet_ids else []
        allocations_by_pallet: dict[int, list[LoadOrderPalletAllocation]] = defaultdict(list)
        for row in allocation_rows:
            allocations_by_pallet[row.pallet_id].append(row)

        loose_rows = list(
            LoadOrderLooseAllocation.select().where(
                LoadOrderLooseAllocation.order.in_(order_ids)
            )
        )
        loose_by_order: dict[int, list[LoadOrderLooseAllocation]] = defaultdict(list)
        for row in loose_rows:
            loose_by_order[row.order_id].append(row)

        snapshots: dict[int, dict] = {}
        for order in orders:
            destinations = destinations_by_order.get(order.id, [])
            order_products = products_by_order.get(order.id, [])
            order_pallets = sorted(
                pallets_by_order.get(order.id, []),
                key=lambda row: row.sequence,
            )

            client_names = []
            delivery_cities = []
            destination_parts = []
            for destination in destinations:
                client_name = clients.get(destination.client_id, "")
                address, city = addresses.get(destination.delivery_address_id, ("", ""))
                if client_name and client_name not in client_names:
                    client_names.append(client_name)
                if city and city not in delivery_cities:
                    delivery_cities.append(city)
                destination_parts.append(
                    f"{client_name}: {address}, {city}".strip()
                )

            product_names = [products.get(row.product_id, "") for row in order_products]
            if len(product_names) == 1:
                products_summary = product_names[0]
            elif product_names:
                products_summary = f"{len(product_names)} productos"
            else:
                products_summary = ""

            requested = []
            product_parts = []
            for row in order_products:
                client_id, address_id = destination_meta.get(row.destination_id, (0, 0))
                client_name = clients.get(client_id, "")
                address, city = addresses.get(address_id, ("", ""))
                product_name = products.get(row.product_id, "")
                requested.append(
                    RequestedLine(
                        destination_id=row.destination_id,
                        product_id=row.product_id,
                        quantity=row.quantity,
                        label=f"{client_name} / {address} / {product_name}",
                    )
                )
                product_parts.append(
                    f"{client_name}: {product_name} x {row.quantity:g} {row.unit}"
                )

            pallet_drafts = []
            for pallet in order_pallets:
                allocations = []
                for allocation in allocations_by_pallet.get(pallet.id, []):
                    client_id, address_id = destination_meta.get(
                        allocation.destination_id, (0, 0)
                    )
                    client_name = clients.get(client_id, "")
                    address, _city = addresses.get(address_id, ("", ""))
                    product_name = products.get(allocation.product_id, "")
                    allocations.append(
                        AllocationDraft(
                            destination_id=allocation.destination_id,
                            product_id=allocation.product_id,
                            quantity=allocation.quantity,
                            peso_unitario_kg=allocation.peso_unitario_kg,
                            client_id=client_id,
                            label=f"{client_name} / {address} / {product_name}",
                        )
                    )
                pallet_drafts.append(
                    PalletDraft(
                        sequence=pallet.sequence,
                        allocations=tuple(allocations),
                    )
                )

            loose_drafts = []
            for allocation in loose_by_order.get(order.id, []):
                client_id, address_id = destination_meta.get(
                    allocation.destination_id, (0, 0)
                )
                client_name = clients.get(client_id, "")
                address, _city = addresses.get(address_id, ("", ""))
                product_name = products.get(allocation.product_id, "")
                loose_drafts.append(
                    LooseAllocationDraft(
                        destination_id=allocation.destination_id,
                        product_id=allocation.product_id,
                        quantity=allocation.quantity,
                        peso_unitario_kg=allocation.peso_unitario_kg,
                        client_id=client_id,
                        label=f"{client_name} / {address} / {product_name}",
                    )
                )

            composition = PalletCompositionService().reconcile(
                requested=requested,
                pallets=pallet_drafts,
                loose=loose_drafts,
            )
            first_pallet = order_pallets[0] if order_pallets else None
            snapshots[order.id] = {
                "clients_summary": (
                    f"VARIOS ({len(client_names)})"
                    if len(client_names) > 1
                    else (client_names[0] if client_names else "")
                ),
                "deliveries_summary": "; ".join(delivery_cities),
                "products_summary": products_summary,
                "destinations_text": "\n".join(destination_parts) or "-",
                "products_text": "\n".join(product_parts) or "-",
                "carrier_name": carriers.get(order.carrier_id, ""),
                "driver_name": drivers.get(order.driver_id, ""),
                "truck_domain": trucks.get(order.truck_id, ""),
                "composition": composition,
                "first_pallet_quantity": first_pallet.quantity if first_pallet else 0,
                "first_pallet_weight": (
                    f"{first_pallet.weight * first_pallet.quantity:g} kg"
                    if first_pallet
                    else "-"
                ),
            }
        return snapshots


    def list_orders_prefetched(
        self,
        *,
        status: str | None = None,
        day: date | None = None,
        order_number: int | None = None,
        limit: int | None = None,
    ) -> list[LoadOrder]:
        """Listado para UI con relaciones precargadas en bloque.

        Mantiene list_orders() intacto para servicios/tests que sólo necesitan
        cabeceras. Esta variante evita consultas N+1 al renderizar la grilla.
        """
        query = LoadOrder.select().order_by(
            LoadOrder.date.desc(),
            LoadOrder.order_number.desc(),
        )
        if status is not None:
            query = query.where(LoadOrder.status == status)
        if day is not None:
            query = query.where(LoadOrder.date == day)
        if order_number is not None:
            query = query.where(LoadOrder.order_number == order_number)
        if limit is not None:
            query = query.limit(max(1, int(limit)))

        destinations = LoadOrderDestination.select()
        products = LoadOrderProduct.select()
        pallets = LoadOrderPallet.select()
        allocations = LoadOrderPalletAllocation.select()
        loose = LoadOrderLooseAllocation.select()

        return list(
            prefetch(
                query,
                destinations,
                products,
                pallets,
                allocations,
                loose,
                Client,
                ClientAddress,
                Product,
                PalletType,
            )
        )

    def composition_from_loaded(self, order: LoadOrder):
        """Calcula composición usando relaciones ya precargadas, sin reconsultar DB."""
        products = list(order.products)
        pallets = sorted(list(order.pallets), key=lambda row: row.sequence)
        loose_allocations = list(order.loose_allocations)

        requested = [
            RequestedLine(
                destination_id=product.destination.id,
                product_id=product.product.id,
                quantity=product.quantity,
                label=(
                    f"{product.destination.client.name} / "
                    f"{product.destination.delivery_address.address} / "
                    f"{product.product.name}"
                ),
            )
            for product in products
            if product.destination_id is not None
        ]
        pallet_drafts = [
            PalletDraft(
                sequence=pallet.sequence,
                allocations=tuple(
                    AllocationDraft(
                        destination_id=allocation.destination.id,
                        product_id=allocation.product.id,
                        quantity=allocation.quantity,
                        peso_unitario_kg=allocation.peso_unitario_kg,
                        client_id=allocation.destination.client.id,
                        label=(
                            f"{allocation.destination.client.name} / "
                            f"{allocation.destination.delivery_address.address} / "
                            f"{allocation.product.name}"
                        ),
                    )
                    for allocation in list(pallet.allocations)
                ),
            )
            for pallet in pallets
        ]
        loose = [
            LooseAllocationDraft(
                destination_id=allocation.destination.id,
                product_id=allocation.product.id,
                quantity=allocation.quantity,
                peso_unitario_kg=allocation.peso_unitario_kg,
                client_id=allocation.destination.client.id,
                label=(
                    f"{allocation.destination.client.name} / "
                    f"{allocation.destination.delivery_address.address} / "
                    f"{allocation.product.name}"
                ),
            )
            for allocation in loose_allocations
        ]
        return PalletCompositionService().reconcile(
            requested=requested,
            pallets=pallet_drafts,
            loose=loose,
        )

    def validate_merchandise_uniqueness(self, order: LoadOrder) -> None:
        """Reject persisted orders that cannot be represented as unique pallet lines."""
        order = LoadOrder.get_by_id(order.id)
        self._require_unique_merchandise(self._persisted_destination_payload(order))

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
        self._require_unique_merchandise(normalized)
        return normalized

    def _require_unique_merchandise(self, destinations: list[dict]) -> None:
        seen_destinations: set[tuple[int, int]] = set()
        seen_lines: set[tuple[int, int, int]] = set()
        for destination in destinations:
            client = destination["client"]
            delivery_address = destination["delivery_address"]
            destination_key = (client.id, delivery_address.id)
            destination_label = f"{client.name} / {delivery_address.address}, {delivery_address.city}"
            if destination_key in seen_destinations:
                raise ValueError(
                    f"El cliente y lugar de entrega {destination_label} ya estan cargados en la orden. "
                    "Use el destino existente para agregar sus articulos."
                )
            seen_destinations.add(destination_key)
            for item in destination["products"]:
                product = item["product"]
                line_key = (*destination_key, product.id)
                if line_key in seen_lines:
                    raise ValueError(
                        f"El articulo {product.name} ya esta cargado para {destination_label}. "
                        "Quite el duplicado o edite la linea existente."
                    )
                seen_lines.add(line_key)

    def _validate_products(self, products: list[dict]) -> list[dict]:
        if not products:
            raise ValueError("La orden debe tener al menos un producto.")
        normalized = []
        for item in products:
            if not isinstance(item, dict):
                raise ValueError("Cada producto de la orden debe ser un detalle valido.")
            product = self._require_instance(item.get("product"), Product, "producto")
            self._require_active(product, "producto")
            self._require_loadable_product(product)
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

    def _validate_pallets(
        self,
        pallets: list[dict],
        destinations: list[dict],
        *,
        weight_snapshots: dict[tuple[int, int, int], Decimal] | None = None,
        loose: list[dict] | None = None,
    ) -> list[dict]:
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
                    self._require_loadable_product(product)
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
                            "peso_unitario_kg": (weight_snapshots or {}).get(
                                (sequence, address.id, product.id),
                                product.peso_unitario_kg,
                            ),
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
            loose=self._draft_loose(loose or []),
        )
        excess = [issue.message for issue in result.issues if issue.code == "excess"]
        if excess:
            raise ValueError(" ".join(excess))
        return normalized

    def _validate_loose(
        self,
        loose: list[dict] | None,
        destinations: list[dict],
        *,
        weight_snapshots: dict[tuple[int, int], Decimal] | None = None,
    ) -> list[dict]:
        normalized: list[dict] = []
        valid_lines = {
            (destination["client"].id, destination["delivery_address"].id, product["product"].id): (
                destination,
                product,
            )
            for destination in destinations
            for product in destination["products"]
        }
        for item in loose or []:
            if not isinstance(item, dict):
                raise ValueError("Cada asignacion suelta debe ser un detalle valido.")
            client = self._require_instance(item.get("client"), Client, "cliente")
            address = self._require_instance(item.get("delivery_address"), ClientAddress, "lugar de entrega")
            product = self._require_instance(item.get("product"), Product, "producto")
            self._require_loadable_product(product)
            key = (client.id, address.id, product.id)
            if key not in valid_lines:
                raise ValueError("La mercaderia suelta no pertenece a la orden.")
            quantity = item.get("quantity")
            if quantity is None or quantity <= 0:
                raise ValueError("La cantidad suelta debe ser mayor a cero.")
            normalized.append(
                {
                    "client": client,
                    "delivery_address": address,
                    "product": product,
                    "quantity": quantity,
                    "peso_unitario_kg": (weight_snapshots or {}).get(
                        (address.id, product.id),
                        product.peso_unitario_kg,
                    ),
                }
            )
        return normalized

    def _raise_if_excess(
        self,
        destinations: list[dict],
        pallets: list[dict],
        loose: list[dict],
    ) -> None:
        result = PalletCompositionService().reconcile(
            requested=self._requested_lines(destinations),
            pallets=self._draft_pallets(pallets),
            loose=self._draft_loose(loose or []),
        )
        excess = [issue.message for issue in result.issues if issue.code == "excess"]
        if excess:
            raise ValueError(" ".join(excess))

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

    def _persisted_loose_payload(self, order: LoadOrder) -> list[dict]:
        return [
            {
                "client": allocation.destination.client,
                "delivery_address": allocation.destination.delivery_address,
                "product": allocation.product,
                "quantity": allocation.quantity,
                "peso_unitario_kg": allocation.peso_unitario_kg,
            }
            for allocation in order.loose_allocations
        ]

    def _pallet_weight_snapshots(self, order: LoadOrder) -> dict[tuple[int, int, int], Decimal]:
        return {
            (pallet.sequence, allocation.destination.delivery_address.id, allocation.product.id):
                allocation.peso_unitario_kg
            for pallet in order.pallets
            for allocation in pallet.allocations
        }

    def _loose_weight_snapshots(self, order: LoadOrder) -> dict[tuple[int, int], Decimal]:
        return {
            (allocation.destination.delivery_address.id, allocation.product.id): allocation.peso_unitario_kg
            for allocation in order.loose_allocations
        }

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
                        client_id=allocation["client"].id,
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

    def _draft_loose(self, loose: list[dict]) -> list[LooseAllocationDraft]:
        return [
            LooseAllocationDraft(
                destination_id=allocation["delivery_address"].id,
                product_id=allocation["product"].id,
                quantity=allocation["quantity"],
                peso_unitario_kg=allocation.get("peso_unitario_kg") or allocation["product"].peso_unitario_kg,
                client_id=allocation["client"].id,
                label=(
                    f"{allocation['client'].name} / {allocation['delivery_address'].address} / "
                    f"{allocation['product'].name}"
                ),
            )
            for allocation in loose
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

    def _require_loadable_product(self, product: Product) -> None:
        if product.product_kind != "producto":
            raise ValueError(f"El artículo '{product.name}' no está habilitado para órdenes de carga.")

    def _validate_order_date(self, value, *, allow_none: bool = True) -> date:
        if value is None:
            if allow_none:
                return date.today()
            raise ValueError("La fecha de la orden es obligatoria.")
        if not isinstance(value, date):
            raise ValueError("La fecha de la orden no es valida.")
        return value

    @staticmethod
    def _normalize_trailer_domain(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("El semi/acoplado debe ser una patente valida.")
        cleaned = "".join(ch for ch in value.strip().upper() if ch.isalnum())
        return cleaned or None

    def _available_trailer_domains(self, carrier: Carrier | None) -> set[str]:
        if carrier is None:
            return set()
        query = Truck.select(Truck.trailer_domain).where(
            (Truck.active == True)  # noqa: E712
            & (Truck.carrier == carrier)
            & (Truck.trailer_domain.is_null(False))
        )
        return {
            normalized
            for row in query
            if row.trailer_domain
            for normalized in (self._normalize_trailer_domain(row.trailer_domain),)
            if normalized
        }

    def _validate_trailer_domain(
        self,
        value: object,
        *,
        carrier: Carrier,
    ) -> str | None:
        normalized = self._normalize_trailer_domain(value)
        if normalized is None:
            return None
        available = self._available_trailer_domains(carrier)
        if normalized not in available:
            raise ValueError(
                "El semi/acoplado seleccionado no pertenece al transportista de la orden."
            )
        return normalized

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

    def _replace_loose_allocations(self, order: LoadOrder, loose: list[dict]) -> None:
        LoadOrderLooseAllocation.delete().where(LoadOrderLooseAllocation.order == order).execute()
        persisted_destinations = {
            (destination.client.id, destination.delivery_address.id): destination
            for destination in order.destinations
        }
        for item in loose:
            destination = persisted_destinations[(item["client"].id, item["delivery_address"].id)]
            LoadOrderLooseAllocation.create(
                order=order,
                destination=destination,
                product=item["product"],
                quantity=item["quantity"],
                peso_unitario_kg=item["peso_unitario_kg"],
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
                        client_id=allocation.destination.client.id,
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
        loose = [
            LooseAllocationDraft(
                destination_id=allocation.destination.id,
                product_id=allocation.product.id,
                quantity=allocation.quantity,
                peso_unitario_kg=allocation.peso_unitario_kg,
                client_id=allocation.destination.client.id,
                label=(
                    f"{allocation.destination.client.name} / "
                    f"{allocation.destination.delivery_address.address} / {allocation.product.name}"
                ),
            )
            for allocation in order.loose_allocations
        ]
        return PalletCompositionService().reconcile(requested=requested, pallets=pallets, loose=loose)

    def _snapshot(self, order: LoadOrder) -> dict:
        return {
            "order_number": order.order_number,
            "status": order.status,
            "client_ids": [destination.client.id for destination in order.destinations],
            "driver_id": order.driver.id,
            "truck_id": order.truck.id,
            "trailer_domain": order.trailer_domain,
        }
