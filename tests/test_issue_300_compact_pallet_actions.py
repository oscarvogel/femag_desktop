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

        action_buttons = (
            widget.add_pallet_button,
            widget.propose_distribution_button,
            widget.reorganize_pending_button,
            widget.recalculate_all_button,
            widget.configure_pallet_capacity_button,
            widget.configure_truck_capacity_button,
            widget.clear_assignments_button,
        )
        assert {position(button)[0] for button in action_buttons} == {0}

        assert widget.propose_distribution_button.text() == "Proponer distribucion"
        assert widget.configure_pallet_capacity_button.text() == "Kg/pallet"
        assert widget.configure_truck_capacity_button.text() == "Cap. camion"
        assert widget.clear_assignments_button.text() == "Quitar asignaciones"

        for button in action_buttons:
            assert button.maximumHeight() <= 36

        widget.resize(1536, 768)
        widget.show()
        app.processEvents()
        assert frame.width() > 0
        assert widget.clear_assignments_button.y() == widget.configure_pallet_capacity_button.y()
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
