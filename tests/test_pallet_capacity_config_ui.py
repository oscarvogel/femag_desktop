from decimal import Decimal
from types import SimpleNamespace


def test_operator_can_configure_global_pallet_capacity_from_preparation(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QInputDialog

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    widget = PalletCompositionWidget(destinations=[])
    monkeypatch.setattr(
        QInputDialog,
        "getDouble",
        lambda *args, **kwargs: (1250.0, True),
    )

    widget.configure_pallet_capacity_button.click()
    app.processEvents()

    assert PalletCapacityService.pallet_max_kg() == Decimal("1250.000")
    assert "Maximo por pallet: 1.250 kg" in widget.capacity_summary_label.text()


def test_operator_can_configure_current_truck_capacity_from_preparation(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QInputDialog, QWidget

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])

    class FakeTruck:
        max_load_kg = None

        def save(self):
            return 1

    truck = FakeTruck()
    host = QWidget()
    host.order = SimpleNamespace(truck=truck)
    widget = PalletCompositionWidget(destinations=[], parent=host)
    monkeypatch.setattr(
        QInputDialog,
        "getDouble",
        lambda *args, **kwargs: (28000.0, True),
    )

    assert widget.configure_truck_capacity_button.isEnabled() is True
    widget.configure_truck_capacity_button.click()
    app.processEvents()

    assert truck.max_load_kg == Decimal("28000.000")
    assert widget._truck_max_load_kg == Decimal("28000.000")
    assert "Camion: 0 kg / 28.000 kg" in widget.capacity_summary_label.text()


def test_truck_capacity_action_is_disabled_without_order_truck(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    widget = PalletCompositionWidget(destinations=[])
    app.processEvents()

    assert widget.configure_truck_capacity_button.isEnabled() is False
