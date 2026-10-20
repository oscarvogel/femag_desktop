"""Renderiza la impresion del remito (preimpreso y vista previa) para revisar posiciones.

Uso:
    python scripts/render_remito_print_evidence.py [carpeta_destino]

Genera, para el layout vigente y para el layout anterior, un PDF y un PNG de
cada variante. Sirve para verificar de forma visual los milimetros de cada
bloque contra el talonario preimpreso antes de mandar a imprimir.

Para una vista previa simple de un remito de ejemplo (sin comparacion antes/despues)
esta ``scripts/generate_issue_351_remittance_print.py``.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from peewee import SqliteDatabase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MM_TO_PT = 72.0 / 25.4


def _build_demo_remittance():
    from app.config.database import bind_database
    from app.models import ALL_MODELS
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.remittance_service import RemittanceService

    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS)

    client = Client.create(name="Cliente FEMAG", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12 km 3 - Parque Industrial",
        is_primary=True,
    )
    carrier = Carrier.create(name="Transporte Norte", cuit="30777777770")
    driver = Driver.create(name="Juan Perez", carrier=carrier, document="12345678")
    truck = Truck.create(domain="AB123CD", carrier=carrier)
    fecula = Product.create(name="Fecula de mandioca", unit="kg")
    almidon = Product.create(name="Almidon", unit="bolsa")

    service = RemittanceService(current_user="render_evidence")
    remittance = service.create_manual(
        client=client,
        delivery_address=address,
        carrier=carrier,
        truck=truck,
        driver=driver,
        items=[
            {"product": fecula, "quantity": 25, "printed_description": "BOL FECULA 2° CALIDAD"},
            {"product": almidon, "quantity": 10, "printed_description": "BOL ALMIDON 1° CALIDAD"},
        ],
    )
    _prepare_for_issue(remittance)
    remittance = service.issue(remittance)
    return remittance, database


def _prepare_for_issue(remittance) -> None:
    remittance.physical_point_of_sale = 1
    remittance.physical_number = 9999
    remittance.save()


def _render(pdf_path: Path, png_path: Path, *, dpi: int = 150) -> None:
    import pymupdf

    document = pymupdf.open(str(pdf_path))
    page = document[0]
    page.get_pixmap(dpi=dpi).save(str(png_path))
    document.close()


def _report_positions(template, label: str) -> None:
    print(f"\n== {label} ==")
    fields = [
        ("fecha", template.date_x, template.date_y, False),
        ("cliente", template.client_x, template.client_y, True),
        ("domicilio", template.address_x, template.address_y, True),
        ("ciudad", template.city_x, template.city_y, True),
        ("provincia", template.province_x, template.province_y, True),
        ("cuit", template.cuit_x, template.cuit_y, True),
        ("iva", template.iva_x, template.iva_y, True),
        ("documento", template.document_x, template.document_y, True),
        ("detalle (inicio)", template.detail_x, template.first_detail_y, True),
        ("transporte", template.carrier_x, template.carrier_y, True),
        ("chofer", template.driver_x, template.driver_y, True),
    ]
    for name, x_mm, y_mm, shifted in fields:
        shift_mm = (template.content_shift_up_points / MM_TO_PT) if shifted else 0.0
        print(f"  {name:<18} x={x_mm:>6.1f} mm   y={y_mm:>6.1f} mm   (impreso {y_mm + shift_mm:.1f} mm)")
    last_detail = template.first_detail_y - (template.max_detail_rows - 1) * template.detail_step
    print(f"  {'detalle (ultimo)':<18} y={last_detail:>6.1f} mm (con {template.max_detail_rows} renglones)")


def main() -> int:
    from app.services.remittance_print_service import RemittancePrintService, RemittancePrintTemplate

    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/prints/remito_layout")
    destination.mkdir(parents=True, exist_ok=True)

    current = RemittancePrintTemplate()
    previous = replace(
        current,
        address_y=223,
        city_y=223,
        province_y=223,
        cuit_y=212,
        iva_y=202,
        first_detail_y=186,
    )

    remittance, database = _build_demo_remittance()
    try:
        for label, template in (("anterior", previous), ("actual", current)):
            service = RemittancePrintService(current_user="render_evidence", template=template)
            preview_pdf = destination / f"remito_preview_{label}.pdf"
            preprinted_pdf = destination / f"remito_preimpreso_{label}.pdf"
            service.export_preview(remittance, preview_pdf)
            service.export_preprinted(remittance, preprinted_pdf)
            _render(preview_pdf, destination / f"remito_preview_{label}.png")
            _render(preprinted_pdf, destination / f"remito_preimpreso_{label}.png")
            _report_positions(template, f"layout {label}")
    finally:
        database.close()

    print(f"\nArchivos generados en: {destination.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
