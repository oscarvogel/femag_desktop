from dataclasses import dataclass
from datetime import date

from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.services.load_order_service import LoadOrderService
from app.ui.abm import ABMViewSpec, build_abm_spec


@dataclass(frozen=True)
class LoadOrderSectionSpec:
    title: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class LoadOrderFormSpec:
    title: str
    sections: tuple[LoadOrderSectionSpec, ...]
    detail_columns: tuple[str, ...]
    detail_actions: tuple[str, ...]
    primary_actions: tuple[str, ...]
    driver_status_messages: dict[str, str]


@dataclass(frozen=True)
class LoadOrderWorkspaceSpec:
    title: str
    subtitle: str
    kpis: tuple[str, ...]
    toolbar_actions: tuple[str, ...]
    table_columns: tuple[str, ...]
    detail_fields: tuple[str, ...]
    detail_actions: tuple[str, ...]
    status_labels: tuple[str, ...]


@dataclass(frozen=True)
class LoadOrderScreenOption:
    id: int
    label: str


@dataclass(frozen=True)
class LoadOrderTableRow:
    id: int
    number: str
    date: str
    client: str
    delivery: str
    product: str
    quantity: str
    driver: str
    carrier: str
    truck: str
    status: str


@dataclass(frozen=True)
class LoadOrderScreenState:
    title: str
    subtitle: str
    rows: tuple[LoadOrderTableRow, ...]
    clients: tuple[LoadOrderScreenOption, ...]
    delivery_addresses: tuple[LoadOrderScreenOption, ...]
    carriers: tuple[LoadOrderScreenOption, ...]
    trucks: tuple[LoadOrderScreenOption, ...]
    drivers: tuple[LoadOrderScreenOption, ...]
    products: tuple[LoadOrderScreenOption, ...]
    statuses: tuple[str, ...]
    primary_actions: tuple[str, ...]
    empty_message: str


def build_load_order_view_spec() -> ABMViewSpec:
    return build_abm_spec(
        entity="ordenes_carga",
        title="Órdenes de carga",
        permissions_menu="Operaciones",
        fields=(
            "order_number",
            "date",
            "carrier",
            "driver",
            "truck",
            "status",
            "observations",
            "destinations",
            "products",
            "destination_products",
            "pallets",
        ),
        actions=("ver", "crear", "modificar", "imprimir", "anular", "cerrar"),
    )


def build_load_order_workspace_spec() -> LoadOrderWorkspaceSpec:
    return LoadOrderWorkspaceSpec(
        title="Órdenes de carga",
        subtitle="Gestione y controle las órdenes de carga del sistema",
        kpis=("Pendientes", "Emitidas hoy", "Camiones en carga", "Entregas del día"),
        toolbar_actions=("Nuevo", "Editar", "Emitir", "Imprimir", "Anular", "Buscar"),
        table_columns=(
            "N° orden",
            "Fecha",
            "Clientes",
            "Destinos",
            "Productos",
            "Pallets",
            "Chofer",
            "Transportista",
            "Camión / patente",
            "Estado",
        ),
        detail_fields=(
            "Fecha de orden",
            "Clientes / destinos",
            "Detalle de productos",
            "Cantidad (Pallets)",
            "Peso estimado",
            "Chofer asignado",
            "Transportista",
            "Camión / Acoplado",
            "Observaciones",
        ),
        detail_actions=("Editar", "Historial"),
        status_labels=tuple((*LoadOrder.ACTIVE_STATUSES, *LoadOrder.FINAL_STATUSES)),
    )


def build_load_order_form_spec() -> LoadOrderFormSpec:
    return LoadOrderFormSpec(
        title="Nueva orden de carga",
        sections=(
            LoadOrderSectionSpec(
                "Datos de la carga",
                ("Número", "Fecha", "Estado", "Observaciones"),
            ),
            LoadOrderSectionSpec(
                "Transporte",
                ("Transportista", "Camión", "Chofer", "Vehículo limpio y apto"),
            ),
        ),
        detail_columns=(
            "Cliente / destinatario",
            "Localidad / destino",
            "Producto / detalle",
            "Bolsas x 25 kg",
            "Bolsas x 10 kg",
            "Pack",
            "Pallet",
            "Lote",
            "Fecha elaboración",
            "Observaciones",
        ),
        detail_actions=("Agregar cliente", "Quitar cliente", "Agregar producto", "Quitar producto"),
        primary_actions=("Guardar orden", "Emitir/Cerrar", "Anular"),
        driver_status_messages={
            "available": "Chofer disponible para nueva carga.",
            "blocked": "El chofer seleccionado ya tiene una carga activa.",
        },
    )


def build_load_order_screen_state(
    *,
    current_user: str,
    selected_carrier_id: int | None = None,
    selected_truck_id: int | None = None,
    filter_status: str | None = None,
    filter_client_id: int | None = None,
    filter_date: date | None = None,
) -> LoadOrderScreenState:
    service = LoadOrderService(current_user=current_user)
    filter_client = _optional_model(Client, filter_client_id)
    rows = tuple(
        _to_table_row(order)
        for order in service.list_orders(status=filter_status or None, client=filter_client, day=filter_date)
    )
    return LoadOrderScreenState(
        title="Órdenes de carga",
        subtitle="Consulta, alta y control operativo de cargas multi-cliente",
        rows=rows,
        clients=_client_options(),
        delivery_addresses=_delivery_address_options(),
        carriers=_carrier_options(),
        trucks=_truck_options(selected_carrier_id),
        drivers=_driver_options(selected_carrier_id, selected_truck_id),
        products=_product_options(),
        statuses=("", *LoadOrder.ACTIVE_STATUSES, *LoadOrder.FINAL_STATUSES),
        primary_actions=("Nueva orden", "Guardar orden", "Emitir/Cerrar", "Anular"),
        empty_message="Sin órdenes de carga para los filtros seleccionados.",
    )


def create_load_order_from_screen(
    *,
    current_user: str,
    carrier_id: int | None,
    truck_id: int | None,
    driver_id: int | None,
    destinations: list[dict],
    observations: str | None = None,
    order_date: date | None = None,
) -> LoadOrder:
    service = LoadOrderService(current_user=current_user)
    carrier = _required_model(Carrier, carrier_id, "transportista")
    truck = _required_model(Truck, truck_id, "camion")
    driver = _required_model(Driver, driver_id, "chofer")
    return service.create_order(
        carrier=carrier,
        truck=truck,
        driver=driver,
        destinations=[_destination_from_screen(destination) for destination in destinations],
        pallets=[],
        observations=observations,
        order_date=order_date,
    )


def _destination_from_screen(destination: dict) -> dict:
    return {
        "client": _required_model(Client, destination.get("client_id"), "cliente"),
        "delivery_address": _required_model(
            ClientAddress,
            destination.get("delivery_address_id"),
            "lugar de entrega",
        ),
        "products": [
            {
                "product": _required_model(Product, product.get("product_id"), "producto"),
                "quantity": _required_quantity(product.get("quantity")),
                "unit": product.get("unit"),
                "observations": product.get("observations"),
            }
            for product in destination.get("products", [])
        ],
        "observations": destination.get("observations"),
    }


def _required_quantity(quantity):
    if quantity is None:
        raise ValueError("La cantidad de producto debe ser mayor a cero.")
    return float(quantity)


def _optional_model(model_class, value_id: int | None):
    if value_id is None:
        return None
    try:
        return model_class.get_by_id(value_id)
    except model_class.DoesNotExist:
        return None


def _required_model(model_class, value_id: int | None, label: str):
    if value_id is None:
        raise ValueError(f"El {label} es obligatorio.")
    try:
        return model_class.get_by_id(value_id)
    except model_class.DoesNotExist as exc:
        raise ValueError(f"El {label} no existe.") from exc


def _to_table_row(order: LoadOrder) -> LoadOrderTableRow:
    destinations = list(order.destinations.order_by())
    products = list(order.products)
    clients = _summarize_clients(destinations)
    deliveries = _summarize_deliveries(destinations)
    total_quantity = sum(product.quantity for product in products)
    product_label = _summarize_products(products)
    return LoadOrderTableRow(
        id=order.id,
        number=f"OC-{order.order_number:06d}",
        date=order.date.strftime("%d/%m/%Y"),
        client=clients,
        delivery=deliveries,
        product=product_label,
        quantity=f"{total_quantity:g} total" if products else "",
        driver=order.driver.name,
        carrier=order.carrier.name,
        truck=order.truck.domain,
        status=order.status,
    )


def _summarize_clients(destinations) -> str:
    names = []
    for destination in destinations:
        if destination.client.name not in names:
            names.append(destination.client.name)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"VARIOS ({len(names)})"


def _summarize_deliveries(destinations) -> str:
    cities = []
    for destination in destinations:
        if destination.delivery_address.city not in cities:
            cities.append(destination.delivery_address.city)
    return "; ".join(cities)


def _summarize_products(products) -> str:
    if not products:
        return ""
    if len(products) == 1:
        return products[0].product.name
    return f"{len(products)} productos"


def _client_options() -> tuple[LoadOrderScreenOption, ...]:
    return tuple(
        LoadOrderScreenOption(client.id, client.name)
        for client in Client.select().where(Client.active == True).order_by(Client.name)  # noqa: E712
    )


def _delivery_address_options() -> tuple[LoadOrderScreenOption, ...]:
    return tuple(
        LoadOrderScreenOption(address.id, f"{address.client.name} - {address.address}, {address.city}")
        for address in ClientAddress.select().join(Client).where(ClientAddress.active == True).order_by(Client.name, ClientAddress.city)  # noqa: E712
    )


def _carrier_options() -> tuple[LoadOrderScreenOption, ...]:
    return tuple(
        LoadOrderScreenOption(carrier.id, carrier.name)
        for carrier in Carrier.select().where(Carrier.active == True).order_by(Carrier.name)  # noqa: E712
    )


def _truck_options(carrier_id: int | None) -> tuple[LoadOrderScreenOption, ...]:
    query = Truck.select().where(Truck.active == True).order_by(Truck.domain)  # noqa: E712
    if carrier_id is not None:
        query = query.where(Truck.carrier == carrier_id)
    return tuple(LoadOrderScreenOption(truck.id, truck.domain) for truck in query)


def _driver_options(carrier_id: int | None, truck_id: int | None) -> tuple[LoadOrderScreenOption, ...]:
    query = Driver.select().where(Driver.active == True, Driver.available == True).order_by(Driver.name)  # noqa: E712
    if truck_id is not None:
        truck = _optional_model(Truck, truck_id)
        if truck is None:
            return ()
        if carrier_id is not None and truck.carrier.id != carrier_id:
            return ()
        query = query.where(Driver.carrier == truck.carrier)
    elif carrier_id is not None:
        query = query.where(Driver.carrier == carrier_id)
    return tuple(LoadOrderScreenOption(driver.id, driver.name) for driver in query)


def _product_options() -> tuple[LoadOrderScreenOption, ...]:
    return tuple(
        LoadOrderScreenOption(product.id, product.name)
        for product in Product.select().where(Product.active == True).order_by(Product.name)  # noqa: E712
    )
