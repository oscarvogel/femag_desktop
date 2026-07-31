import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Client
from app.services.auth_service import AuthService
from app.services.client_payment_service import ClientPaymentService
from app.services.payment_receipt_print_service import PaymentReceiptPrintService
from app.services.permission_service import PermissionService
from app.ui.customer_ledger import CustomerLedgerPage
from app.ui.desktop_app import FemagDesktopWindow
from scripts.generate_ux_screenshots import _capture


DEFAULT_OUTPUT = (
    Path("docs")
    / "screenshots"
    / "issue_13_payments"
    / "payment_receipt_actions.png"
)


def generate(target: Path, pdf_dir: Path | None = None) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS)
    try:
        PermissionService().seed_defaults()
        admin = AuthService().create_user(
            "captura13_admin",
            "secreto",
            "Administrador",
        )
        client = Client.create(
            name="Ferretería Avenida",
            cuit="30712345678",
            iva_condition="RI",
        )
        payments = ClientPaymentService(current_user=admin.username)
        active_payment = payments.register_payment(
            client=client,
            amount=2500,
            method="transferencia",
            reference="TRF-2026-0713",
            observations="Pago parcial de cuenta corriente",
        )
        annulled_payment = payments.register_payment(
            client=client,
            amount=750,
            method="efectivo",
            observations="Pago duplicado para evidencia",
        )
        payments.annul_payment(
            annulled_payment,
            authorized_by=admin,
            reason="Pago duplicado",
        )
        if pdf_dir is not None:
            PaymentReceiptPrintService(
                current_user=admin.username
            ).export_pdf(annulled_payment, pdf_dir)

        app = QApplication.instance() or QApplication([])
        window = FemagDesktopWindow(user=admin, demo_mode=True)
        window.resize(1440, 900)
        window._navigate_to_route("customer_ledger")
        window.show()
        app.processEvents()
        page = window.stack.currentWidget()
        if not isinstance(page, CustomerLedgerPage):
            raise RuntimeError("No se pudo abrir la cuenta corriente.")
        payment_row = next(
            row
            for row in range(page.movements_table.rowCount())
            if page.movements_table.item(row, 0).data(Qt.UserRole)
            == active_payment.id
        )
        page.movements_table.setCurrentCell(payment_row, 0)
        app.processEvents()
        _capture(window, target)
        window.close()
        return target
    finally:
        database.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Genera evidencia visual del issue #13")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        help="Opcional: genera un recibo anulado para validación visual",
    )
    args = parser.parse_args(argv)
    print(generate(args.output, args.pdf_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
