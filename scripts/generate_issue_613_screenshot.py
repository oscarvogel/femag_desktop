"""Capturas de UX del issue #613: filtro por fecha en los movimientos.

Base en memoria con datos sinteticos: ninguna cifra ni cliente real entra en la
evidencia. Misma receta que scripts/generate_issue_581_screenshot.py.

Deja dos capturas que muestran lo que el issue pide y lo que el filtro NO puede
hacer: recalcular el saldo.
"""

import os
import sys
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.accounting import ClientAccountMovement
from app.models.masters import Client, Salesperson
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService
from app.ui.customer_ledger import CustomerLedgerPage
from app.ui.desktop_app import FemagDesktopWindow
from scripts.generate_ux_screenshots import _capture


OUTPUT_DIR = Path("docs/screenshots/issue_613_cuenta_corriente_filtro_fecha")

# (fecha, tipo, importe, descripcion) -> el saldo acumulado se calcula solo.
MOVIMIENTOS = [
    (date(2026, 1, 12), ClientAccountMovement.TYPE_LOAD_ORDER, 4_200_000.00, "Orden de carga enero"),
    (date(2026, 2, 8), ClientAccountMovement.TYPE_LOAD_ORDER, 2_850_000.00, "Orden de carga febrero"),
    (date(2026, 3, 5), ClientAccountMovement.TYPE_PAYMENT, -1_500_000.00, "Cobro parcial marzo"),
    (date(2026, 3, 28), ClientAccountMovement.TYPE_MANUAL_DEBIT, 310_250.50, "Debito manual marzo"),
    (date(2026, 4, 9), ClientAccountMovement.TYPE_LOAD_ORDER, 1_980_000.00, "Orden de carga abril"),
    (date(2026, 5, 14), ClientAccountMovement.TYPE_MANUAL_CREDIT, -420_000.00, "Bonificacion mayo"),
    (date(2026, 6, 3), ClientAccountMovement.TYPE_LOAD_ORDER, 3_600_000.00, "Orden de carga junio"),
]


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        PermissionService().seed_defaults()
        admin = AuthService().create_user("captura613", "secreto", "Administrador")
        luis = Salesperson.create(name="Luis", phone="5493743667526", email="luis@example.com")
        client = Client.create(
            name="Cliente Demo Filtro", cuit="30700000613", iva_condition="RI", salesperson=luis
        )
        for moment, movement_type, amount, description in MOVIMIENTOS:
            ClientAccountMovement.create(
                client=client,
                movement_type=movement_type,
                source_ref=f"OC-613-{moment:%Y%m%d}",
                description=description,
                total_amount=amount,
                movement_date=moment,
                due_date=moment if amount > 0 else None,
            )

        window = FemagDesktopWindow(user=admin, demo_mode=True)
        window.resize(1600, 950)
        window._navigate_to_route("customer_ledger")
        window.show()
        app.processEvents()
        page = window.stack.currentWidget()
        if not isinstance(page, CustomerLedgerPage):
            raise RuntimeError("No se pudo abrir la cuenta corriente.")

        page.salesperson_filter.setCurrentIndex(page.salesperson_filter.findData(luis.id))
        # Un click real en el combo emite "activated"; setCurrentIndex solo no lo hace.
        page.salesperson_filter.activated.emit(luis.id)
        app.processEvents()

        for row in range(page.clients_table.rowCount()):
            if page.clients_table.item(row, 0).data(256) == client.id:
                page.clients_table.setCurrentCell(row, 0)
                break
        app.processEvents()

        saldo_completo = page.detail_balance.text()
        _capture(window, OUTPUT_DIR / "customer_ledger_sin_filtro.png")

        # Filtro activo: solo el segundo trimestre.
        page.movement_date_from_enabled.setChecked(True)
        page.movement_date_from.setDate(QDate(2026, 4, 1))
        page.movement_date_to_enabled.setChecked(True)
        page.movement_date_to.setDate(QDate(2026, 6, 30))
        app.processEvents()

        # Lo unico que no puede pasar: el saldo del encabezado no se recalcula.
        if page.detail_balance.text() != saldo_completo:
            raise RuntimeError(
                f"El filtro movio el saldo del encabezado: {saldo_completo} -> "
                f"{page.detail_balance.text()}"
            )
        if page.movements_table.rowCount() != 3:
            raise RuntimeError(
                f"Se esperaban 3 movimientos del segundo trimestre, "
                f"hay {page.movements_table.rowCount()}"
            )
        _capture(window, OUTPUT_DIR / "customer_ledger_filtro_trimestre.png")

        window.close()
        return [
            OUTPUT_DIR / "customer_ledger_sin_filtro.png",
            OUTPUT_DIR / "customer_ledger_filtro_trimestre.png",
        ]
    finally:
        database.close()


if __name__ == "__main__":
    for path in generate():
        print(path)
