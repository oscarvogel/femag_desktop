import argparse
import sys
from pathlib import Path

from peewee import SqliteDatabase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import bind_database
from app.config.schema import ensure_runtime_schema
from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.services.load_order_operation_service import LoadOrderOperationService
from app.services.load_order_print_service import LoadOrderPrintService
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService


DEFAULT_EVIDENCE_DIR = Path("docs") / "prints" / "issue_73_integral_demo"
DEFAULT_DATABASE_PATH = Path("backups") / "issue_73_integral_demo.sqlite3"


def run_integral_demo(
    *,
    database,
    evidence_dir: str | Path = DEFAULT_EVIDENCE_DIR,
    username: str = "issue73_demo",
) -> dict:
    bind_database(database)
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    PermissionService().seed_defaults()

    masters = _ensure_demo_masters()
    order = _create_load_order(username, masters)
    operations = LoadOrderOperationService(current_user=username, prints_dir=evidence_dir)
    issued = operations.issue(order)

    print_service = LoadOrderPrintService(current_user=username)
    output_dir = Path(evidence_dir)
    order_html = print_service.export_order(issued, output_dir)
    summary_html = print_service.export_summary(issued, output_dir)
    reprint_html = operations.reprint_order(issued)

    annulled = operations.annul(issued, can_annul=True)
    originals = _movements_for(annulled, reversal=False)
    reversals = _movements_for(annulled, reversal=True)
    readme = _write_readme(
        output_dir=output_dir,
        order=annulled,
        order_html=order_html,
        summary_html=summary_html,
        reprint_html=reprint_html,
        originals=len(originals),
        reversals=len(reversals),
    )

    return {
        "order": annulled,
        "order_number": annulled.order_number,
        "status": annulled.status,
        "carrier": annulled.carrier.name,
        "driver": annulled.driver.name,
        "truck": annulled.truck.domain,
        "destinations": annulled.destinations.count(),
        "products": annulled.products.count(),
        "ledger_originals": len(originals),
        "ledger_reversals": len(reversals),
        "ledger_total": len(originals) + len(reversals),
        "order_html": order_html,
        "summary_html": summary_html,
        "reprint_html": reprint_html,
        "readme": readme,
    }


def _ensure_demo_masters() -> dict:
    carrier, _ = Carrier.get_or_create(
        name="ISSUE73 Transporte Demo",
        defaults={"cuit": "30730000001", "phone": "3764-730000"},
    )
    driver, _ = Driver.get_or_create(
        name="ISSUE73 Chofer Demo",
        defaults={"carrier": carrier, "document": "D73000001", "phone": "3764-730001"},
    )
    driver.carrier = carrier
    driver.available = True
    driver.save()
    truck, _ = Truck.get_or_create(domain="I730ABC", defaults={"carrier": carrier})
    truck.carrier = carrier
    truck.save()

    client_norte, _ = Client.get_or_create(
        cuit="30730000002",
        defaults={"name": "ISSUE73 Cliente Norte", "iva_condition": "RI", "contact": "Demo Norte"},
    )
    client_sur, _ = Client.get_or_create(
        cuit="30730000003",
        defaults={"name": "ISSUE73 Cliente Sur", "iva_condition": "RI", "contact": "Demo Sur"},
    )
    address_norte_a = _get_or_create_address(
        client=client_norte,
        city="Posadas",
        address="Ruta 12 km 73",
        observations="Destino norte principal",
    )
    address_norte_b = _get_or_create_address(
        client=client_norte,
        city="Eldorado",
        address="Parque Industrial lote 73",
        observations="Segundo destino del mismo cliente",
    )
    address_sur = _get_or_create_address(
        client=client_sur,
        city="Obera",
        address="Deposito Sur calle 73",
        observations="Destino sur",
    )

    product_bolsa, _ = Product.get_or_create(name="ISSUE73 Producto bolsa", defaults={"unit": "bolsas"})
    product_pack, _ = Product.get_or_create(name="ISSUE73 Producto pack", defaults={"unit": "packs"})
    product_granel, _ = Product.get_or_create(name="ISSUE73 Producto granel", defaults={"unit": "kg"})

    return {
        "carrier": carrier,
        "driver": driver,
        "truck": truck,
        "client_norte": client_norte,
        "client_sur": client_sur,
        "address_norte_a": address_norte_a,
        "address_norte_b": address_norte_b,
        "address_sur": address_sur,
        "product_bolsa": product_bolsa,
        "product_pack": product_pack,
        "product_granel": product_granel,
    }


def _get_or_create_address(*, client: Client, city: str, address: str, observations: str) -> ClientAddress:
    existing = ClientAddress.get_or_none(
        (ClientAddress.client == client)
        & (ClientAddress.address_type == "entrega")
        & (ClientAddress.province == "Misiones")
        & (ClientAddress.city == city)
        & (ClientAddress.address == address)
    )
    if existing is not None:
        return existing
    return ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city=city,
        address=address,
        is_primary=False,
        observations=observations,
    )


def _create_load_order(username: str, masters: dict) -> LoadOrder:
    return LoadOrderService(current_user=username).create_order(
        carrier=masters["carrier"],
        driver=masters["driver"],
        truck=masters["truck"],
        destinations=[
            {
                "client": masters["client_norte"],
                "delivery_address": masters["address_norte_a"],
                "products": [
                    {"product": masters["product_bolsa"], "quantity": 120, "observations": "Primer destino"},
                    {"product": masters["product_pack"], "quantity": 30, "observations": "Complemento"},
                ],
            },
            {
                "client": masters["client_norte"],
                "delivery_address": masters["address_norte_b"],
                "products": [{"product": masters["product_granel"], "quantity": 2500, "observations": "Granel"}],
            },
            {
                "client": masters["client_sur"],
                "delivery_address": masters["address_sur"],
                "products": [{"product": masters["product_bolsa"], "quantity": 75, "observations": "Sur"}],
            },
        ],
        pallets=[],
        observations="Demo integral issue #73: orden multi-cliente/multi-destino documental.",
    )


def _movements_for(order: LoadOrder, *, reversal: bool) -> list[ClientAccountMovement]:
    return list(
        ClientAccountMovement.select()
        .where(
            (ClientAccountMovement.load_order == order)
            & (ClientAccountMovement.is_reversal == reversal)
        )
        .order_by(ClientAccountMovement.id)
    )


def _write_readme(
    *,
    output_dir: Path,
    order: LoadOrder,
    order_html: Path,
    summary_html: Path,
    reprint_html: Path,
    originals: int,
    reversals: int,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    readme = output_dir / "README.md"
    computer_use_note = _existing_computer_use_note(readme)
    readme.write_text(
        "\n".join(
            [
                "# Evidencia Issue #73 - Demo integral Ordenes de carga",
                "",
                f"- Orden: OC-{order.order_number:06d}",
                f"- Estado final: {order.status}",
                f"- Transportista: {order.carrier.name}",
                f"- Chofer: {order.driver.name}",
                f"- Camion / patente: {order.truck.domain}",
                f"- Destinos: {order.destinations.count()}",
                f"- Productos: {order.products.count()}",
                f"- Orden HTML: `{order_html.name}`",
                f"- Hoja/sobre HTML: `{summary_html.name}`",
                f"- Reimpresion HTML: `{reprint_html.name}`",
                f"- Cuenta corriente documental: {originals} movimientos originales y {reversals} reversos.",
                "",
                "## Flujo validado por script",
                "",
                "1. Asegura maestros sinteticos.",
                "2. Crea Orden de carga multi-cliente/multi-destino.",
                "3. Emite la orden.",
                "4. Genera Orden HTML A4.",
                "5. Genera hoja/sobre HTML A4.",
                "6. Reimprime como copia operativa.",
                "7. Verifica cuenta corriente documental.",
                "8. Anula la orden.",
                "9. Verifica reversos documentales.",
                "",
                "## Computer Use",
                "",
                computer_use_note,
                "",
                "## Alcance",
                "",
                "No fiscal. No remito, F150, AFIP/ARCA, factura, presupuesto, rendicion ni Delivery*.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return readme


def _existing_computer_use_note(readme: Path) -> str:
    default = (
        "Pendiente de registrar en la revision del PR #73. Si falla por PyQt/Windows, "
        "no cerrar #69 como validado visualmente."
    )
    if not readme.exists():
        return default
    text = readme.read_text(encoding="utf-8")
    marker = "## Computer Use"
    start = text.find(marker)
    if start < 0:
        return default
    after_marker = text[start + len(marker) :]
    next_section = after_marker.find("\n## ")
    note = after_marker[:next_section].strip() if next_section >= 0 else after_marker.strip()
    return note or default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run issue #73 integral load-order demo.")
    parser.add_argument("--database-path", default=str(DEFAULT_DATABASE_PATH))
    parser.add_argument("--evidence-dir", default=str(DEFAULT_EVIDENCE_DIR))
    parser.add_argument("--username", default="issue73_demo")
    args = parser.parse_args(argv)

    database_path = Path(args.database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(database_path)
    try:
        result = run_integral_demo(database=database, evidence_dir=args.evidence_dir, username=args.username)
    finally:
        if not database.is_closed():
            database.close()

    print("Demo integral issue #73 ejecutada")
    print(f"Orden: OC-{result['order_number']:06d}")
    print(f"Estado final: {result['status']}")
    print(f"Destinos: {result['destinations']}")
    print(f"Productos: {result['products']}")
    print(f"Cuenta corriente: {result['ledger_originals']} movimientos + {result['ledger_reversals']} reversos")
    print(f"Evidencia: {result['readme']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
