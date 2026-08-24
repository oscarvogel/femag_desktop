import os
import subprocess
import sys
import textwrap


def test_pallet_grid_uses_available_width_and_height():
    code = textwrap.dedent(
        """
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        from PyQt5.QtWidgets import QApplication, QFrame, QScrollArea

        import app.ui
        from app.ui.pallet_composition import PalletCompositionWidget

        app = QApplication.instance() or QApplication([])
        widget = PalletCompositionWidget(destinations=[])
        widget.resize(1536, 768)
        widget.show()
        app.processEvents()

        widget.add_pallets(12)
        app.processEvents()

        scroll = widget.findChild(QScrollArea, "palletCardScroll")
        assert scroll.minimumHeight() >= 220
        assert scroll.maximumHeight() > 170

        total_frame = widget.findChild(QFrame, "loadOrderKgTotalFrame")
        assert total_frame.maximumHeight() <= 145

        layout = widget.card_grid
        columns = []
        for index in range(layout.count()):
            item = layout.itemAt(index)
            card = item.widget()
            if card is not None and card.objectName().startswith("palletCard"):
                _row, column, _row_span, _col_span = layout.getItemPosition(index)
                columns.append(column)

        assert columns
        visible_columns = max(columns) + 1
        assert 5 <= visible_columns <= 6

        first_card = widget._cards[1]
        assert first_card.minimumWidth() <= 128
        assert first_card.maximumWidth() <= 160

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
