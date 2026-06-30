"""Issue #131 visual smoke: captura el dialogo en su alto minimo.

Se corre como test para garantizar PyQt5 + imports del proyecto disponibles.
"""
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest


@pytest.mark.smoke
def test_load_order_dialog_visual_smoke_at_minimum_height(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.models.load_orders import LoadOrder
    from app.models.masters import (
        Carrier,
        Client,
        ClientAddress,
        Driver,
        Product,
        Truck,
    )
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    out_dir = ROOT / "docs" / "prints" / "issue_131_load_order_footer_cutoff"
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])

    carrier = Carrier.create(name="Smoke 131 Carrier")
    Driver.create(name="Smoke 131 Driver", carrier=carrier)
    Truck.create(domain="SMK131", carrier=carrier)
    client = Client.create(
        name="Smoke 131 Client", cuit="30713131313", iva_condition="RI"
    )
    ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta smoke",
    )
    Product.create(name="Smoke 131 Product", unit="kg")

    dialog = LoadOrderEntryDialog(
        LoadOrderService(current_user="smoke_issue131"), "smoke_issue131"
    )
    dialog.resize(1100, dialog.minimumHeight())
    dialog.show()
    app.processEvents()

    save_btn = dialog.findChild(QPushButton, "saveLoadOrderButton")
    cancel_btn = dialog.findChild(QPushButton, "cancelLoadOrderButton")
    assert save_btn is not None
    assert cancel_btn is not None

    dialog_height = dialog.height()
    save_bottom = save_btn.mapToParent(save_btn.rect().bottomLeft()).y()
    cancel_bottom = cancel_btn.mapToParent(cancel_btn.rect().bottomLeft()).y()
    assert save_bottom <= dialog_height, (
        f"Guardar fuera: bottom={save_bottom}, dialog_height={dialog_height}"
    )
    assert cancel_bottom <= dialog_height, (
        f"Cancelar fuera: bottom={cancel_bottom}, dialog_height={dialog_height}"
    )

    out_png = out_dir / "load_order_footer_at_min_height.png"
    pixmap = dialog.grab()
    pixmap.save(str(out_png), "PNG")
    assert out_png.exists()
    assert out_png.stat().st_size > 1000

    LoadOrder.delete().execute()