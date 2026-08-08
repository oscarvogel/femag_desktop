import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication, QComboBox, QLabel, QVBoxLayout, QWidget

from app.ui.combo_autocomplete import enable_combo_autocomplete


OUTPUT_DIR = Path("docs/screenshots/issue_combo_deploy")


def _capture_deployed_list(combo: QComboBox, title: str, output: Path) -> None:
    preview = QWidget()
    preview.setObjectName("comboDeployEvidence")
    preview.setStyleSheet(
        "#comboDeployEvidence { background: #f8fafc; } QLabel { color: #0f172a; font-weight: 700; }"
    )
    layout = QVBoxLayout(preview)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.addWidget(QLabel(title))

    preview_combo = QComboBox()
    for index in range(combo.count()):
        preview_combo.addItem(combo.itemText(index), combo.itemData(index))
    enable_combo_autocomplete(preview_combo, placeholder=combo.lineEdit().placeholderText())
    layout.addWidget(preview_combo)
    preview.resize(560, 200)
    preview.show()
    preview_combo.showPopup()
    QApplication.processEvents()
    image = preview.grab().toImage().convertToFormat(QImage.Format_RGB32)
    if not image.save(str(output), "PNG"):
        raise RuntimeError(f"No se pudo guardar {output}")
    preview.close()


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    combo = QComboBox()
    for name in ("Autoservicio Norte", "Distribuidora del Sur", "Mercado Central"):
        combo.addItem(name, None)
    enable_combo_autocomplete(combo, placeholder="Buscar cliente...")
    output = OUTPUT_DIR / "combo_desplegado_con_click.png"
    _capture_deployed_list(combo, "Combo desplegado con clic en el campo", output)
    app.quit()
    return [output]


if __name__ == "__main__":
    for path in generate():
        print(path)
