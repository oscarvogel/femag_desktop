"""El Excel de Ventas por producto se abre solo despues de generarse."""

import os
import types
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from app.ui import operational_product_sales as module

_APP = QApplication.instance() or QApplication([])


class _FakeService:
    def export_xlsx(self, result, destination):
        return Path(destination)


def _dialog_with_result():
    dialog = module.OperationalProductSalesDialog.__new__(
        module.OperationalProductSalesDialog
    )
    dialog.service = _FakeService()
    dialog._last_result = types.SimpleNamespace(
        filters=types.SimpleNamespace(
            start=date(2026, 11, 1),
            end=date(2026, 11, 30),
        )
    )
    return dialog


def _patch_save_dialog(monkeypatch, target: Path) -> None:
    monkeypatch.setattr(
        module.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "")),
    )


def _patch_messages(monkeypatch) -> list:
    messages: list = []
    monkeypatch.setattr(
        module.QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: messages.append(args)),
    )
    return messages


def test_export_excel_opens_the_generated_file(monkeypatch, tmp_path):
    target = tmp_path / "ventas.xlsx"
    target.write_bytes(b"xlsx")
    dialog = _dialog_with_result()
    _patch_save_dialog(monkeypatch, target)
    messages = _patch_messages(monkeypatch)
    opened: list = []

    import app.reports.client_list_export as client_export

    monkeypatch.setattr(
        client_export,
        "open_generated_file",
        lambda path: opened.append(path) or True,
    )

    dialog.export_excel()

    assert opened == [target]
    assert "Se abrió automáticamente." in messages[-1][2]


def test_export_excel_still_reports_when_opening_fails(monkeypatch, tmp_path):
    target = tmp_path / "ventas.xlsx"
    target.write_bytes(b"xlsx")
    dialog = _dialog_with_result()
    _patch_save_dialog(monkeypatch, target)
    messages = _patch_messages(monkeypatch)

    import app.reports.client_list_export as client_export

    monkeypatch.setattr(client_export, "open_generated_file", lambda path: False)

    dialog.export_excel()

    assert "Se abrió automáticamente." not in messages[-1][2]
