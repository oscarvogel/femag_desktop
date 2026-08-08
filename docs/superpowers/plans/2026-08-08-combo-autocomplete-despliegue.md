# Despliegue claro de combos autocompletables — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer evidente el despliegue de la lista en todos los combos autocompletables: clic en el campo abre/cierra la lista completa, y la flecha del dropdown se percibe como botón con estado hover.

**Architecture:** Un event filter sobre `combo.lineEdit()` centralizado en `app/ui/combo_autocomplete.py` decide `showPopup()`/`hidePopup()` al hacer clic, sin tocar ninguno de los call sites. La pista visual se agrega como tooltip en el line edit y el estado hover del botón flecha se agrega en el QSS global (`STYLES`).

**Tech Stack:** PyQt5 (QComboBox, QCompleter, QEvent, QObject), pytest, QT_QPA_PLATFORM=offscreen.

---

### Task 1: Event filter para abrir/cerrar el popup con clic

**Files:**
- Modify: `app/ui/combo_autocomplete.py`
- Modify: `tests/test_combo_autocomplete.py`

Contexto: `enable_combo_autocomplete` (líneas 10-30 de `app/ui/combo_autocomplete.py`) ya configura editable + completer. El event filter se instala sobre `combo.lineEdit()` y se guarda como hijo del combo para que no lo reclame el GC. La guarda `AUTOCOMPLETE_PROPERTY` evita instalar dos veces.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_combo_autocomplete.py` (los imports actuales de `QApplication, QComboBox` y `Qt` ya están; hay que agregar `QTest`):

```python
from PyQt5.QtTest import QTest
```

```python
def _show(combo):
    combo.show()
    _application().processEvents()
    return combo


def test_combo_click_on_field_opens_popup() -> None:
    combo = _show(_combo())
    QTest.mouseClick(combo.lineEdit(), Qt.LeftButton)
    _application().processEvents()
    assert combo.view().isVisible()


def test_combo_click_again_closes_popup() -> None:
    combo = _show(_combo())
    QTest.mouseClick(combo.lineEdit(), Qt.LeftButton)
    _application().processEvents()
    assert combo.view().isVisible()
    QTest.mouseClick(combo.lineEdit(), Qt.LeftButton)
    _application().processEvents()
    assert not combo.view().isVisible()


def test_combo_sets_deploy_hint_tooltip() -> None:
    combo = _combo()
    assert combo.lineEdit().toolTip() == "Clic para ver la lista, escribí para filtrar"


def test_combo_accepts_custom_hint() -> None:
    _application()
    combo = QComboBox()
    combo.addItem("A", 1)
    enable_combo_autocomplete(combo, hint="Toque para desplegar")
    assert combo.lineEdit().toolTip() == "Toque para desplegar"


def test_combo_filters_after_opening_via_click() -> None:
    combo = _show(_combo())
    QTest.mouseClick(combo.lineEdit(), Qt.LeftButton)
    _application().processEvents()
    combo.completer().setCompletionPrefix("SUR")
    assert combo.completer().completionModel().rowCount() == 1
    assert combo.completer().completionModel().index(0, 0).data() == "Distribuidora del Sur"
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_combo_autocomplete.py -v`
Expected: FAIL — `enable_combo_autocomplete() got an unexpected keyword argument 'hint'` y los tests de popup fallan porque todavía no hay event filter.

- [ ] **Step 3: Implementar el event filter**

Reemplazar el contenido completo de `app/ui/combo_autocomplete.py` por:

```python
from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import QComboBox, QCompleter


AUTOCOMPLETE_PROPERTY = "femagAutocompleteEnabled"
DEFAULT_HINT = "Clic para ver la lista, escribí para filtrar"


class _PopupToggleFilter(QObject):
    """Open or close the combo popup when the editable field is clicked."""

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self._combo = combo

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.MouseButtonPress and watched is self._combo.lineEdit():
            if self._popup_is_visible():
                self._close_popup()
            else:
                self._open_filtered_popup()
        return False

    def _popup_is_visible(self) -> bool:
        if self._combo.view().isVisible():
            return True
        completer = self._combo.completer()
        return completer is not None and completer.popup().isVisible()

    def _close_popup(self) -> None:
        completer = self._combo.completer()
        if completer is not None and completer.popup().isVisible():
            completer.popup().hide()
        self._combo.hidePopup()

    def _open_filtered_popup(self) -> None:
        text = self._combo.lineEdit().text()
        completer = self._combo.completer()
        if text and completer is not None:
            completer.setCompletionPrefix(text)
            completer.complete()
        else:
            self._combo.showPopup()


def enable_combo_autocomplete(
    combo: QComboBox,
    *,
    placeholder: str = "Buscar...",
    hint: str = DEFAULT_HINT,
) -> QComboBox:
    """Make a combo searchable without allowing arbitrary values to be stored."""
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.setMaxVisibleItems(12)

    line_edit = combo.lineEdit()
    if line_edit is not None:
        line_edit.setClearButtonEnabled(True)
        line_edit.setPlaceholderText(placeholder)
        if hint:
            line_edit.setToolTip(hint)

    completer = QCompleter(combo.model(), combo)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    completer.setCompletionMode(QCompleter.PopupCompletion)
    combo.setCompleter(completer)

    if not combo.property(AUTOCOMPLETE_PROPERTY) and line_edit is not None:
        line_edit.installEventFilter(_PopupToggleFilter(combo))
        line_edit.editingFinished.connect(lambda current=combo: commit_combo_text(current))
        combo.setProperty(AUTOCOMPLETE_PROPERTY, True)
    return combo


def matching_combo_index(combo: QComboBox, text: str) -> int:
    normalized = text.strip().casefold()
    for index in range(combo.count()):
        if combo.itemText(index).strip().casefold() == normalized:
            return index
    return -1


def commit_combo_text(combo: QComboBox) -> None:
    """Commit an exact label or clear text that is not one of the available items."""
    index = matching_combo_index(combo, combo.currentText())
    if index >= 0:
        combo.setCurrentIndex(index)
        return
    combo.setCurrentIndex(-1)
    combo.clearEditText()


def combo_current_data(combo: QComboBox):
    """Return data only when the visible text identifies an actual combo item."""
    index = matching_combo_index(combo, combo.currentText())
    return combo.itemData(index) if index >= 0 else None
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_combo_autocomplete.py -v`
Expected: PASS (5 tests nuevos + 3 existentes).

Nota: si en el backend offscreen `combo.view().isVisible()` no refleja el estado del popup, usar en su lugar `combo.view().window().isVisible()` en el assert de los tests de popup. Documentar el cambio en el PR.

- [ ] **Step 5: Commit**

```bash
git add app/ui/combo_autocomplete.py tests/test_combo_autocomplete.py
git commit -m "feat(combos): abrir lista completa con clic en el campo buscable"
```

---

### Task 2: Estado hover del botón flecha en el QSS global

**Files:**
- Modify: `app/ui/desktop_app.py` (bloque `STYLES`, reglas `QComboBox::drop-down`/`QComboBox::down-arrow`, líneas ~3143-3156)
- Modify: `tests/test_ui_smoke.py` (test `test_global_styles_include_polished_combo_controls`, líneas 148-155)

- [ ] **Step 1: Escribir el test que falla**

En `tests/test_ui_smoke.py`, dentro de `test_global_styles_include_polished_combo_controls`, agregar el assert:

```python
    assert "QComboBox::drop-down:hover" in STYLES
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_ui_smoke.py::test_global_styles_include_polished_combo_controls -v`
Expected: FAIL — AssertionError, el `:hover` no existe todavía en STYLES.

- [ ] **Step 3: Agregar la regla hover al QSS**

En `app/ui/desktop_app.py`, inmediatamente después de la regla `QComboBox::down-arrow, QDateEdit::down-arrow { ... }` (que cierra en la línea ~3156), insertar:

```python
QComboBox::drop-down:hover, QDateEdit::drop-down:hover { background: #eef2f7; }
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `python -m pytest tests/test_ui_smoke.py::test_global_styles_include_polished_combo_controls -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ui/desktop_app.py tests/test_ui_smoke.py
git commit -m "ux(combos): resaltar boton flecha del combo al pasar el mouse"
```

---

### Task 3: Regenerar evidencia visual y validaciones finales

**Files:**
- Create: `scripts/generate_combo_deploy_screenshot.py`
- Create: `docs/screenshots/issue_combo_deploy/README.md`

Objetivo: dejar evidencia visual de que el clic despliega la lista completa, siguiendo el patrón de `scripts/generate_issue_218_autocomplete_screenshots.py`.

- [ ] **Step 1: Crear el script de captura**

```python
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5.QtCore import QTimer
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
```

- [ ] **Step 2: Ejecutar el script y verificar que genera la imagen**

Run: `python scripts/generate_combo_deploy_screenshot.py`
Expected: imprime la ruta `docs/screenshots/issue_combo_deploy/combo_desplegado_con_click.png` y el archivo existe.

- [ ] **Step 3: Crear README de evidencia**

```markdown
# Evidencia: despliegue claro de combos autocompletables

Captura generada con PyQt5 en modo `QT_QPA_PLATFORM=offscreen` desde
`scripts/generate_combo_deploy_screenshot.py`.

La captura muestra el combo con el popup abierto (equivalente a hacer clic en el campo),
evidenciando que el despliegue ahora es descubrible: clic en cualquier parte del campo abre
la lista completa y al tipear se filtra en vivo.

Limitación conocida: en modo offscreen el texto puede renderizarse como bloques; el
comportamiento funcional queda cubierto por `tests/test_combo_autocomplete.py`.
```

- [ ] **Step 4: Correr la suite completa de validaciones**

Run:
```bash
python -m pytest
python -m compileall app
```
Expected: todos los tests pasan y `compileall` no reporta errores.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_combo_deploy_screenshot.py docs/screenshots/issue_combo_deploy
git commit -m "docs(combos): evidencia visual del despliegue con clic"
```
