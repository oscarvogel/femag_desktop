import os
import subprocess
import sys
import textwrap


def test_guided_selector_shows_twenty_pallets_without_stale_empty_state():
    code = textwrap.dedent(
        """
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        from PyQt5.QtWidgets import QApplication, QLabel, QScrollArea

        import app.ui
        from app.ui.pallet_composition import PalletCompositionWidget

        app = QApplication.instance() or QApplication([])
        widget = PalletCompositionWidget(destinations=[])
        widget.resize(1536, 768)
        widget.show()
        app.processEvents()

        widget.guided_total_pallets_input.setValue(20)
        widget._guided_create_to_total()
        app.processEvents()

        scroll = widget.findChild(QScrollArea, "guidedPalletSelectorScroll")
        assert scroll is not None
        assert scroll.minimumHeight() >= 76
        assert scroll.maximumHeight() <= 84
        assert len(widget._guided_pallet_buttons) == 20

        layout = widget.guided_pallet_selector_grid
        positions = []
        for index in range(layout.count()):
            item = layout.itemAt(index)
            button = item.widget()
            if button is not None and button.objectName().startswith(
                "guidedPalletSelectorButton_"
            ):
                row, column, _row_span, _column_span = layout.getItemPosition(index)
                positions.append((row, column))

        assert len(positions) == 20
        rows = sorted({row for row, _column in positions})
        assert len(rows) == 2
        assert [
            sum(row == current for row, _column in positions) for current in rows
        ] == [10, 10]

        empty_state = [
            label
            for label in widget.findChildren(QLabel)
            if "todavia no hay pallets" in label.text().lower()
        ]
        assert not any(label.isVisible() for label in empty_state)

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
