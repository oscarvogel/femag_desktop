import os
import subprocess
import sys
import textwrap


def test_pallet_actions_are_compact_and_destructive_action_is_separated():
    code = textwrap.dedent(
        """
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        from PyQt5.QtWidgets import QApplication, QFrame

        import app.ui  # instala las extensiones productivas
        from app.ui.pallet_composition import PalletCompositionWidget

        app = QApplication.instance() or QApplication([])
        widget = PalletCompositionWidget(destinations=[])
        frame = widget.findChild(QFrame, "palletBatchActions")
        layout = frame.layout()

        def position(target):
            for index in range(layout.count()):
                item = layout.itemAt(index)
                if item.widget() is target:
                    return layout.getItemPosition(index)
            raise AssertionError(f"No se encontro {target.objectName()}")

        assert position(widget.propose_distribution_button) == (3, 0, 1, 2)
        assert position(widget.reorganize_pending_button) == (4, 0, 1, 1)
        assert position(widget.recalculate_all_button) == (4, 1, 1, 1)
        assert position(widget.configure_pallet_capacity_button) == (5, 0, 1, 1)
        assert position(widget.configure_truck_capacity_button) == (5, 1, 1, 1)
        assert position(widget.clear_assignments_button) == (7, 0, 1, 2)

        assert widget.configure_pallet_capacity_button.text() == "Configurar kg/pallet"
        assert widget.configure_truck_capacity_button.text() == "Capacidad camion"
        assert layout.rowMinimumHeight(6) >= 8

        for button in (
            widget.reorganize_pending_button,
            widget.recalculate_all_button,
            widget.configure_pallet_capacity_button,
            widget.configure_truck_capacity_button,
        ):
            assert button.maximumHeight() <= 36

        widget.resize(1536, 768)
        widget.show()
        app.processEvents()
        assert frame.width() > 0
        assert widget.clear_assignments_button.y() > widget.configure_pallet_capacity_button.y()
        widget.close()
        """
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout
