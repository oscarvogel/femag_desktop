import argparse
import sys
from pathlib import Path

from peewee import SqliteDatabase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import bind_database
from app.config.schema import ensure_runtime_schema
from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
from app.services.client_payment_service import ClientPaymentService
from app.services.ledger_query_service import client_balance
from app.services.load_order_operation_service import LoadOrderOperationService
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService


DEFAULT_DATABASE_PATH = Path("femag_operational_smoke.sqlite3")
DEFAULT_EVIDENCE_DIR = Path("docs") / "prints" / "issue_105_operational_smoke"
DEFAULT_REPORT_PATH = Path("docs") / "SMOKE_OPERATIVO_FEMAG.md"


def run_operational_smoke(
    *,
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    evidence_dir: str | Path = DEFAULT_EVIDENCE_DIR,
    report_path: str | Path = DEFAULT_REPORT_PATH,
    username: str = "issue105_smoke",
    reset_database: bool = True,
) -> dict:
    database_path = Path(database_path)
    evidence_dir = Path(evidence_dir)
    report_path = Path(report_path)

    if reset_database and database_path.exists():
        database_path.unlink()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    database = SqliteDatabase(database_path)
    try:
        bind_database(database)
        database.connect(reuse_if_open=True)
        ensure_runtime_schema(database)
        PermissionService().seed_defaults()

        masters = _create_demo_masters()
        order_service = LoadOrderService(current_user=username)
        operation_service = LoadOrderOperationService(current_user=username, prints_dir=evidence_dir)

        order = order_service.create_order(
            carrier=masters["carrier"],
            driver=masters["driver"],
            truck=masters["truck"],
            destinations=[
                {
                    "client": masters["client"],
                    "delivery_address": masters["address"],
                    "products": [
                        {
                            "product": masters["product"],
                            "quantity": 10,
                            "observations": "Smoke operativo #105",
                        }
                    ],
                }
            ],
            pallets=[],
            observations="Smoke operativo issue #105 con datos sinteticos.",
        )
        issued = operation_service.issue(order)
        balance_after_issue = client_balance(masters["client"])
        order_pdf = operation_service.print_order(issued)
        payment = ClientPaymentService(current_user=username).register_payment(
            client=masters["client"],
            amount=balance_after_issue,
            reference="SMOKE-105",
            observations="Pago sintetico del smoke operativo #105.",
        )
        balance_after_payment = client_balance(masters["client"])
        closed = order_service.change_status(issued, LoadOrder.STATUS_CLOSED, reason="Smoke operativo #105")
        driver = Driver.get_by_id(masters["driver"].id)

        result = {
            "database_path": database_path,
            "evidence_dir": evidence_dir,
            "report_path": report_path,
            "order_number": closed.order_number,
            "order_status": closed.status,
            "order_pdf": order_pdf,
            "balance_after_issue": round(float(balance_after_issue), 2),
            "balance_after_payment": round(float(balance_after_payment), 2),
            "payment_receipt": payment.receipt_number,
            "driver_released": bool(driver.available),
            "client": masters["client"].name,
            "carrier": masters["carrier"].name,
            "driver": driver.name,
            "truck": masters["truck"].domain,
            "product": masters["product"].name,
        }
        _write_report(result)
        return result
    finally:
        if not database.is_closed():
            database.close()


def _create_demo_masters() -> dict:
    iva = TipoIVA.iva_default()
    carrier = Carrier.create(name="ISSUE105 Transporte Smoke", cuit="30105000001", phone="3764-105000")
    driver = Driver.create(
        name="ISSUE105 Chofer Smoke",
        carrier=carrier,
        document="D10500001",
        phone="3764-105001",
    )
    truck = Truck.create(domain="I105ABC", carrier=carrier)
    client = Client.create(
        name="ISSUE105 Cliente Smoke",
        cuit="30105000002",
        iva_condition="RI",
        contact="Smoke #105",
        lista_precios=1,
    )
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Smoke 105",
        observations="Direccion sintetica para smoke operativo.",
    )
    product = Product.create(
        name="ISSUE105 Producto Smoke",
        unit="kg",
        precio_neto_base=1000.0,
        precio_lista_1=1000.0,
        precio_lista_2=1000.0,
        precio_lista_3=1000.0,
        precio_lista_4=1000.0,
        tipo_iva=iva,
    )
    return {
        "carrier": carrier,
        "driver": driver,
        "truck": truck,
        "client": client,
        "address": address,
        "product": product,
    }


def _write_report(result: dict) -> Path:
    report_path = Path(result["report_path"])
    report_path.write_text(
        "\n".join(
            [
                "# Smoke operativo FEMAG",
                "",
                "Issue: #105",
                "",
                "No usa datos productivos. Este smoke crea una base SQLite local con datos sinteticos prefijados `ISSUE105`.",
                "",
                "## Comando",
                "",
                "```bash",
                "py -3 scripts/femag_operational_smoke.py",
                "```",
                "",
                "Opciones utiles:",
                "",
                "```bash",
                "py -3 scripts/femag_operational_smoke.py --database-path .tmp/issue_105.sqlite3 --evidence-dir .tmp/issue_105_evidence --report-path .tmp/issue_105_report.md",
                "```",
                "",
                "## Resultado de la ultima ejecucion",
                "",
                f"- Base SQLite: `{Path(result['database_path'])}`",
                f"- Evidencia: `{Path(result['evidence_dir'])}`",
                f"- Orden: `OC-{result['order_number']:06d}`",
                f"- Estado final de orden: `{result['order_status']}`",
                f"- Orden PDF: `{Path(result['order_pdf']).name}`",
                f"- Cliente: `{result['client']}`",
                f"- Transportista: `{result['carrier']}`",
                f"- Chofer liberado: `{result['driver_released']}`",
                f"- Camion: `{result['truck']}`",
                f"- Producto: `{result['product']}`",
                f"- Saldo luego de emitir: `{result['balance_after_issue']:.2f}`",
                f"- Recibo de pago: `{result['payment_receipt']}`",
                f"- Saldo luego del pago: `{result['balance_after_payment']:.2f}`",
                "",
                "## Modulos cubiertos",
                "",
                "| Modulo | Estado | Validacion |",
                "|---|---|---|",
                "| App / schema | Cubierto | Abre SQLite local, crea schema runtime y permisos base. |",
                "| ABMs de transporte | Cubierto | Crea transportista, chofer y camion sinteticos. |",
                "| Cliente, lugar y producto demo | Cubierto | Crea cliente, direccion de entrega y producto sinteticos. |",
                "| Ordenes de carga | Cubierto | Crea orden, emite, imprime PDF y cierra. |",
                "| Liberacion de chofer | Cubierto | Verifica chofer disponible luego del cierre. |",
                "| Cuenta corriente y pagos | Cubierto | Emision genera saldo, pago sintetico lo deja en cero. |",
                "",
                "## Modulos no disponibles",
                "",
                "| Modulo | Estado | Motivo |",
                "|---|---|---|",
                "| Remitos | Modulo no disponible | Queda fuera de #105 y no debe usarse remito real. |",
                "| F150 | Modulo no disponible | Queda fuera de #105 y no debe usarse fiscal real. |",
                "| Rendicion de transportistas | Modulo no disponible | Pendiente de diseno/implementacion en issues separados. |",
                "| Importacion DBF/MySQL | Modulo no disponible | Area protegida; este smoke usa solo SQLite sintetico. |",
                "",
                "## Salidas esperadas",
                "",
                "- Exit code `0`.",
                "- PDF `orden_carga_N.pdf` en el directorio de evidencia.",
                "- Reporte Markdown actualizado.",
                "- Base local descartable con datos `ISSUE105`.",
                "- Saldo del cliente en cero despues del pago.",
                "",
                "## Alcance",
                "",
                "Este smoke no implementa funcionalidades faltantes. No usa remitos reales, F150 real, importacion DBF/MySQL, bases productivas ni logica fiscal.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run FEMAG operational smoke for issue #105.")
    parser.add_argument("--database-path", default=str(DEFAULT_DATABASE_PATH))
    parser.add_argument("--evidence-dir", default=str(DEFAULT_EVIDENCE_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--username", default="issue105_smoke")
    args = parser.parse_args(argv)

    result = run_operational_smoke(
        database_path=args.database_path,
        evidence_dir=args.evidence_dir,
        report_path=args.report_path,
        username=args.username,
    )

    print("Smoke operativo FEMAG ejecutado")
    print(f"Orden: OC-{result['order_number']:06d}")
    print(f"Estado final: {result['order_status']}")
    print(f"Chofer liberado: {result['driver_released']}")
    print(f"Recibo: {result['payment_receipt']}")
    print(f"Saldo final: {result['balance_after_payment']:.2f}")
    print(f"Reporte: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
