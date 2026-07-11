from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, Driver, Truck


def _format_order_number(num: int) -> str:
    return f"OC-{num:06d}"


def _order_search_text(order: LoadOrder) -> str:
    parts = [
        _format_order_number(order.order_number),
        str(order.order_number),
        order.date.strftime("%d/%m/%Y"),
        order.status,
        order.carrier.name if order.carrier else "",
        order.driver.name if order.driver else "",
        order.truck.domain if order.truck else "",
    ]
    clients = set()
    for dest in order.destinations:
        clients.add(dest.client.name)
    if order.client:
        clients.add(order.client.name)
    parts.extend(clients)
    return " ".join(parts).lower()


def search_orders(query: str) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    results = []
    for order in LoadOrder.select():
        if q in _order_search_text(order):
            results.append({
                "type": "orden",
                "id": order.id,
                "label": (
                    f"{_format_order_number(order.order_number)} - "
                    f"{order.date.strftime('%d/%m/%Y')} - "
                    f"{order.carrier.name if order.carrier else '-'} / "
                    f"{order.driver.name if order.driver else '-'}"
                ),
                "route": "load_orders",
                "ref": order.id,
            })
    return results


def search_clients(query: str) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    results = []
    for client in Client.select():
        text = f"{client.name} {client.cuit or ''}".lower()
        if q in text:
            results.append({
                "type": "cliente",
                "id": client.id,
                "label": f"{client.name} ({client.cuit or '-'})",
                "route": "clients",
                "ref": client.id,
            })
    return results


def search_drivers(query: str) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    results = []
    for driver in Driver.select():
        text = f"{driver.name} {driver.document or ''} {driver.carrier.name if driver.carrier else ''}".lower()
        if q in text:
            results.append({
                "type": "chofer",
                "id": driver.id,
                "label": f"{driver.name} ({driver.carrier.name if driver.carrier else 'sin transporte'})",
                "route": "drivers",
                "ref": driver.id,
            })
    return results


def search_carriers(query: str) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    results = []
    for carrier in Carrier.select():
        text = f"{carrier.name} {carrier.cuit or ''}".lower()
        if q in text:
            results.append({
                "type": "transportista",
                "id": carrier.id,
                "label": f"{carrier.name} ({carrier.cuit or '-'})",
                "route": "carriers",
                "ref": carrier.id,
            })
    return results


def search_trucks(query: str) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    results = []
    for truck in Truck.select():
        text = f"{truck.domain} {truck.carrier.name if truck.carrier else ''}".lower()
        if q in text:
            results.append({
                "type": "camion",
                "id": truck.id,
                "label": f"{truck.domain} ({truck.carrier.name if truck.carrier else 'sin transporte'})",
                "route": "trucks",
                "ref": truck.id,
            })
    return results


def global_search(query: str) -> dict[str, list[dict]]:
    return {
        "ordenes": search_orders(query),
        "clientes": search_clients(query),
        "choferes": search_drivers(query),
        "transportistas": search_carriers(query),
        "camiones": search_trucks(query),
    }
