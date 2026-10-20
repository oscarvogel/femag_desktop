"""Capturas de UX del issue #734: el presupuesto manual y su aviso de stock.

Base en memoria con datos sinteticos: ningun dato real entra en la evidencia.
La plataforma es `windows` en vez de `offscreen` para que el texto se dibuje
(#652).
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Client, Product
from app.models.stock import StockMovement
from app.services.stock_service import StockService
from app.ui.load_order_stock_shortfall_dialog import LoadOrderStockShortfallDialog
from app.ui.manual_budget_dialog import ManualBudgetDialog
from scripts.generate_ux_screenshots import _capture

OUTPUT_DIR = Path("docs/screenshots/issue_734_presupuesto_manual_stock")


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        bolsa = Product.create(
            name="BOLSAS ALMIDON DE MAIZ X 25 KG", unit="unidad",
            peso_unitario_kg=Decimal("25.000"), product_kind="producto",
            stock_role="terminado", active=True,
        )
        servicio = Product.create(
            name="FLETE", unit="UN", product_kind="servicio",
            stock_role="terminado", active=True,
        )
        cliente = Client.create(
            name="CLIENTE DEMO", cuit="30730000009", iva_condition="RI",
            dias_plazo_pago=0, lista_precios=1,
        )
        # Stock real: 3.000 kg de la bolsa.
        StockService.register(
            product=bolsa, movement_type=StockMovement.TYPE_INITIAL_INVENTORY,
            quantity_kg=Decimal("3000.000"), source_ref="stock_count:1",
            description="Inventario inicial", created_by="operador1",
        )

        # 1) El dialogo del presupuesto manual, con la nota de que no todo
        #    descuenta stock.
        dialogo = ManualBudgetDialog(client=cliente, current_user="operador1")
        dialogo.resize(920, 620)
        indice = dialogo.product_combo.findData(bolsa.id)
        dialogo.product_combo.setCurrentIndex(indice)
        dialogo.quantity_input.setValue(100)
        dialogo.unit_price_input.setValue(4500.0)
        dialogo._add_item()
        indice_servicio = dialogo.product_combo.findData(servicio.id)
        dialogo.product_combo.setCurrentIndex(indice_servicio)
        dialogo.quantity_input.setValue(1)
        dialogo.unit_price_input.setValue(15000.0)
        dialogo._add_item()
        dialogo.show()
        app.processEvents()
        destino_dialogo = OUTPUT_DIR / "presupuesto_manual_stock.png"
        _capture(dialogo, destino_dialogo)
        dialogo.close()

        # 2) El aviso de faltante, el mismo que en el despacho (#732).
        from app.services.stock_shortfall import StockShortfall

        faltantes = [
            StockShortfall(
                product=bolsa, available_kg=Decimal("3000.000"),
                requested_kg=Decimal("25000.000"),
            ),
        ]
        aviso = LoadOrderStockShortfallDialog(
            None,
            faltantes,
            titulo="Stock insuficiente - Nuevo presupuesto",
            subtitulo="El presupuesto pide más mercadería de la que hay en stock",
            texto_ayuda=(
                "Podés crearlo igual, pero el motivo queda registrado en la "
                "auditoría y en los movimientos de stock: es la traza de por "
                "qué se despachó sin stock."
            ),
            headers=(
                "Producto",
                "Stock en el libro (kg)",
                "Pide el presupuesto (kg)",
                "Falta (kg)",
            ),
        )
        aviso.resize(760, 480)
        aviso.show()
        app.processEvents()
        destino_aviso = OUTPUT_DIR / "aviso_stock_insuficiente_presupuesto.png"
        _capture(aviso, destino_aviso)
        aviso.close()

        return [destino_dialogo, destino_aviso]
    finally:
        database.close()


if __name__ == "__main__":
    for ruta in generate():
        print(ruta)
