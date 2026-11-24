"""Capturas de la pantalla "Cuenta corriente productores" (#941).

Arma una base en memoria con productores **ficticios**, abre la ventana real de
FEMAG Desktop en la ruta ``supplier_ledger`` y la captura a la resolucion del
cliente (1638x969) y a 1366x768. Tambien captura el dialogo de registrar pago.

Uso: python scripts/generate_issue_941_screenshots.py [--output-dir DIR]
"""

import argparse
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from peewee import SqliteDatabase  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from app.config.database import bind_database  # noqa: E402
from app.models import ALL_MODELS, SYNC_MODELS  # noqa: E402
from app.models.security import User, UserProfile  # noqa: E402
from app.models.suppliers import (  # noqa: E402
    Supplier,
    SupplierDocument,
    SupplierDocumentExclusion,
    SupplierLegacyCode,
)
from app.services.permission_service import PermissionService  # noqa: E402
from app.services.supplier_ledger_service import (  # noqa: E402
    AllocationRequest,
    SupplierLedgerService,
)
from generate_ux_screenshots import _capture  # noqa: E402

DEFAULT_OUTPUT = Path("docs") / "screenshots" / "issue_941"
T = SupplierDocument.KIND_TICKET
P = SupplierDocument.KIND_PROMISSORY_NOTE

# Productores ficticios: nombres y montos inventados para la captura.
DEMO = [
    ("COOPERATIVA YERBATERA DEMO", ("0101", "0102"), [(T, "250000.00", 40), (T, "180000.00", 25), (T, "95000.00", 6)], []),
    ("ACOPIO LOS PINOS DEMO", ("0201",), [(T, "310000.00", 70), (T, "42000.00", 12)], [(P, "60000.00", 90)]),
    ("PRODUCTOR EJEMPLO UNO", ("0301",), [(T, "88000.50", 15)], []),
    ("PRODUCTOR EJEMPLO DOS", ("0302",), [(T, "45000.00", 33)], [(P, "15000.00", 120)]),
    ("PRODUCTOR EJEMPLO TRES", ("0303",), [], [(P, "30000.00", 200)]),
    ("COLONO DE PRUEBA", ("0401", "0402"), [(T, "12500.00", 4)], []),
]


def _seed() -> User:
    PermissionService().seed_defaults()
    today = date.today()
    counter = 44000
    for name, codes, tickets, notes in DEMO:
        supplier = Supplier.create(name=name, normalized_name=name)
        for code in codes:
            SupplierLegacyCode.create(
                supplier=supplier, code=code, source_key=f"demo:proveedo:{code}", name=name
            )
        for kind, amount, age in tickets + notes:
            counter += 1
            code = f"{counter:012d}" if kind == T else f"{counter % 1000:04d}"
            SupplierDocument.create(
                supplier=supplier,
                kind=kind,
                source_key=f"demo:{kind}:{counter}",
                source_code=code,
                issued_at=date.fromordinal(today.toordinal() - age),
                date_inferred=(counter % 5 == 0),
                amount=Decimal(amount),
                balance=Decimal(amount),
                source_hash="demo",
            )
    SupplierDocumentExclusion.create(
        kind=T,
        source_key="demo:movi:excluido",
        source_code="000000043999",
        supplier_code="0101",
        amount=Decimal("15800.00"),
        reason=SupplierDocumentExclusion.REASON_NO_QUANTITY,
    )
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="captura941", password_hash="x", profile=profile)

    ledger = SupplierLedgerService(user.username)
    ledger.open_ledger_from_imports(cutoff=today)
    first = Supplier.get(Supplier.name == DEMO[0][0])
    ticket = first.documents.where(SupplierDocument.kind == T).order_by(SupplierDocument.id).first()
    ledger.register_payment(
        supplier=first,
        amount=Decimal("100000"),
        method="transferencia",
        allocations=[AllocationRequest(ticket, Decimal("100000"))],
        reference="TRF 000123",
        observations="Pago parcial de captura",
    )
    return user


def generate(output_dir: Path) -> list[Path]:
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.supplier_payment_dialog import SupplierPaymentDialog

    output_dir.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables([*ALL_MODELS, *SYNC_MODELS])
    app = QApplication.instance() or QApplication([])
    user = _seed()

    # Igual que las capturas de #946: se captura la pagina sola a cada
    # resolucion. La ventana principal tiene su propio ancho minimo y no
    # baja de el, asi que no sirve para mostrar como entra en 1366x768.
    window = FemagDesktopWindow(user=user, demo_mode=True)
    window._navigate_to_route("supplier_ledger")
    app.processEvents()
    page = window.stack.currentWidget()
    page.setParent(None)
    page.show()

    targets = []
    for width, height in ((1638, 969), (1366, 768)):
        page.resize(width, height)
        app.processEvents()
        target = output_dir / f"01_cuenta_corriente_productores_{width}x{height}.png"
        _capture(page, target)
        targets.append(target)

    page.detail_tabs.setCurrentIndex(1)
    page.payment_table.selectRow(0)
    page.resize(1366, 768)
    app.processEvents()
    target = output_dir / "02_pagos_del_productor_1366x768.png"
    _capture(page, target)
    targets.append(target)

    tickets = page._pending_tickets()
    dialog = SupplierPaymentDialog(page.detail_title.text(), tickets, parent=page)
    dialog.set_allocation(0, float(tickets[0].pending))
    if len(tickets) > 1:
        dialog.set_allocation(1, 20000)
    dialog.reference_edit.setText("TRF 000456")
    dialog.show()
    app.processEvents()
    target = output_dir / "03_registrar_pago.png"
    _capture(dialog, target)
    targets.append(target)
    dialog.close()
    page.close()
    window.close()
    return targets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    for target in generate(args.output_dir):
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
