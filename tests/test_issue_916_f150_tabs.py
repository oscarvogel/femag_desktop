from datetime import date

import pytest
from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

from app.models.f150 import F150Batch
from app.ui.f150 import F150Page
from tests.test_f150_batch_service import _issued_remittance


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(db, tmp_path, qt_app):
    widget = F150Page(current_user="admin", output_dir=tmp_path)
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def _batch(number, *, process_date=date(2026, 11, 19), user="admin"):
    return F150Batch.create(
        batch_number=f"F150-{number:08d}", process_date=process_date,
        file_name=f"lote-{number}.txt", file_path=f"lote-{number}.txt",
        sha256="0" * 64, remittance_count=1, detail_count=1, created_by=user,
    )


def test_historial_tiene_pestana_y_altura_para_varios_lotes(page, qt_app):
    for number in range(1, 13):
        _batch(number)
    page.resize(1366, 650)
    page.show()
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "Remitos sin generar", "Historial",
    ]
    assert page.tabs.currentIndex() == 0
    page.tabs.setCurrentIndex(1)
    qt_app.processEvents()
    assert page.history.rowCount() == 12
    assert page.history.viewport().height() > 250
    assert not page.table.isVisible()
    assert page.recover_button.isVisible()


def test_filtros_de_pendientes_no_ocultan_historial(page):
    _batch(1, process_date=date(2020, 1, 1))
    _batch(2)
    page.date_from.setDate(QDate(2030, 1, 1))
    page.date_to.setDate(QDate(2030, 12, 31))
    page.number.setText("NO EXISTE")
    page.refresh()
    assert page.history.rowCount() == 0  # carga solo al abrir su pestaña
    page.tabs.setCurrentIndex(1)
    assert page.history.rowCount() == 2  # incluye también lotes antiguos


def test_historial_filtra_fecha_y_usuario_sin_cambiar_pendientes(page):
    _batch(1, process_date=date(2020, 1, 1), user="otro")
    _batch(2, user="otro")
    expected = _batch(3)
    page.tabs.setCurrentIndex(1)
    page.history_use_dates.setChecked(True)
    page.history_date_from.setDate(QDate(2026, 11, 1))
    page.history_date_to.setDate(QDate(2026, 11, 30))
    page.history_user.setCurrentIndex(page.history_user.findData("admin"))
    page._refresh_history()
    assert page.history.rowCount() == 1
    assert page.history.item(0, 0).data(Qt.UserRole) == expected.id
    page.history_user.setCurrentIndex(0)
    page._refresh_history()
    assert page.history.rowCount() == 2


def test_consultar_historial_conserva_remitos_marcados(page):
    _issued_remittance()
    page.date_from.setDate(QDate(2026, 1, 1))
    page.date_to.setDate(QDate(2026, 12, 31))
    page.refresh()
    page.table.item(0, 0).setCheckState(Qt.Checked)
    page.tabs.setCurrentIndex(1)
    page.tabs.setCurrentIndex(0)
    assert page.table.item(0, 0).checkState() == Qt.Checked


def test_generar_ver_en_historial_y_recuperar_mismos_bytes(
    page, tmp_path, monkeypatch,
):
    remittance = _issued_remittance()
    page.date_from.setDate(QDate(2026, 1, 1))
    page.date_to.setDate(QDate(2026, 12, 31))
    page.refresh()
    assert page.table.rowCount() == 1
    page.table.item(0, 0).setCheckState(Qt.Checked)
    original = tmp_path / "generado.txt"
    recovered = tmp_path / "recuperado.txt"
    paths = iter([original, recovered])
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(next(paths)), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: None)
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: errors.append(_a[2]))
    page._generate()
    assert errors == []
    assert page.table.rowCount() == 0
    page.tabs.setCurrentIndex(1)
    assert page.history.rowCount() == 1
    assert "0001-00001068" in page.history.item(0, 6).text()
    page.history.selectRow(0)
    page._recover_txt()
    assert errors == []
    assert recovered.read_bytes() == original.read_bytes()
    assert F150Batch.select().count() == 1
