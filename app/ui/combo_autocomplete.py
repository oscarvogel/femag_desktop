from __future__ import annotations

import unicodedata

from PyQt5.QtCore import QEvent, QObject, QSignalBlocker, Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


AUTOCOMPLETE_PROPERTY = "femagAutocompleteEnabled"
DEFAULT_HINT = "Clic para ver la lista, escribí para filtrar"
SEARCH_HINT = f"{DEFAULT_HINT}. F2 busca en una ventana."
SEARCH_COLUMNS_ROLE = Qt.UserRole + 10


def _normalize_search_text(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


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
        completer = self._combo.completer()
        return completer is not None and completer.popup().isVisible()

    def _close_popup(self) -> None:
        completer = self._combo.completer()
        if completer is not None:
            completer.popup().hide()

    def _open_filtered_popup(self) -> None:
        text = self._combo.lineEdit().text()
        completer = self._combo.completer()
        if completer is not None:
            completer.setCompletionPrefix(text)
            completer.complete()


class ComboSearchDialog(QDialog):
    """Búsqueda alfabética de las opciones de un combo (F2)."""

    def __init__(self, combo: "SearchableComboBox", parent=None) -> None:
        super().__init__(parent)
        self.combo = combo
        self.selected_index: int | None = None
        self._rows: list[tuple[tuple[str, ...], int]] = []
        headers = combo.search_headers
        subject = (combo.placeholder or "registro").strip()
        if subject.casefold().startswith("buscar "):
            subject = subject[7:].strip()
        self.setWindowTitle(f"Buscar {subject}" if subject else "Buscar registro")
        self.resize(720, 430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("comboSearchInput")
        self.search_input.setPlaceholderText("Escribir para filtrar...")
        self.search_input.setClearButtonEnabled(True)
        layout.addWidget(self.search_input)
        self.table = QTableWidget(0, len(headers))
        self.table.setObjectName("comboSearchTable")
        self.table.setHorizontalHeaderLabels(list(headers))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.installEventFilter(self)
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search_input.textChanged.connect(self._render_rows)
        self.search_input.returnPressed.connect(self._accept_current)
        self.table.cellDoubleClicked.connect(lambda _row, _column: self._accept_current())
        self._collect_rows()
        self.search_input.setFocus(Qt.OtherFocusReason)

    def _collect_rows(self) -> None:
        rows = []
        for index in range(self.combo.count()):
            label = self.combo.itemText(index)
            if not label.strip():
                continue
            rows.append((self.combo.search_columns_for(index), index))
        rows.sort(key=lambda row: _normalize_search_text(row[0][0] if row[0] else ""))
        self._rows = rows
        self._render_rows()

    def _render_rows(self) -> None:
        query = _normalize_search_text(self.search_input.text())
        visible = []
        for columns, index in self._rows:
            haystack = _normalize_search_text(" ".join(columns))
            if not query or query in haystack:
                visible.append((columns, index))
        self.table.setRowCount(len(visible))
        for row, (columns, index) in enumerate(visible):
            for column, value in enumerate(columns):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, index)
                self.table.setItem(row, column, item)
        if visible:
            self.table.selectRow(0)

    def _accept_current(self) -> None:
        row = self.table.currentRow()
        if row < 0 and self.table.rowCount():
            row = 0
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        self.selected_index = item.data(Qt.UserRole)
        self.accept()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.table
            and event.type() == QEvent.KeyPress
            and event.key() in (Qt.Key_Return, Qt.Key_Enter)
        ):
            self._accept_current()
            return True
        return super().eventFilter(watched, event)


class SearchableComboBox(QComboBox):
    """Combo editable con búsqueda inmediata, F2 y texto/ID desacoplados."""

    def __init__(
        self,
        parent=None,
        *,
        placeholder: str = "Buscar...",
        hint: str = SEARCH_HINT,
        search_headers: tuple[str, ...] | list[str] | None = None,
        preserve_unmatched: bool = False,
    ) -> None:
        super().__init__(parent)
        self.placeholder = placeholder
        self._search_headers = tuple(search_headers or ("Nombre",))
        self._preserve_unmatched = preserve_unmatched
        self._committed_index = -1
        self._f2_open = False
        enable_combo_autocomplete(self, placeholder=placeholder, hint=hint)
        line_edit = self.lineEdit()
        if line_edit is not None:
            try:
                line_edit.editingFinished.disconnect()
            except (TypeError, RuntimeError):
                pass
            line_edit.editingFinished.connect(self.commit_search_text)
            line_edit.installEventFilter(self)
        self.installEventFilter(self)
        self.currentIndexChanged.connect(self._remember_selection)

    @property
    def search_headers(self) -> tuple[str, ...]:
        return self._search_headers

    def search_columns_for(self, index: int) -> tuple[str, ...]:
        extra = self.itemData(index, SEARCH_COLUMNS_ROLE)
        if isinstance(extra, (tuple, list)) and extra:
            columns = [str(value) for value in extra]
        else:
            columns = [self.itemText(index)]
        if len(columns) < len(self._search_headers):
            columns.extend([""] * (len(self._search_headers) - len(columns)))
        return tuple(columns)

    def currentData(self, role: int = Qt.UserRole):
        index = self.currentIndex()
        if index < 0 or index >= self.count():
            return None
        if _normalize_search_text(self.currentText()) != _normalize_search_text(self.itemText(index)):
            return None
        return self.itemData(index, role)

    def clear(self) -> None:
        super().clear()
        self._committed_index = -1

    def setCurrentIndex(self, index: int) -> None:
        super().setCurrentIndex(index)
        if index < 0 or index >= self.count():
            self._committed_index = -1
            return
        if _normalize_search_text(self.currentText()) == _normalize_search_text(self.itemText(index)):
            self._committed_index = index

    def _remember_selection(self, index: int) -> None:
        if self._f2_open or index < 0 or index >= self.count():
            return
        if _normalize_search_text(self.currentText()) == _normalize_search_text(self.itemText(index)):
            self._committed_index = index

    def commit_search_text(self) -> None:
        if self._f2_open:
            return
        text = self.currentText().strip()
        if text:
            index = matching_combo_index(self, text)
            if index >= 0:
                if index != self.currentIndex():
                    super().setCurrentIndex(index)
                self._committed_index = index
                return
        if self._preserve_unmatched:
            return
        self._restore_committed()

    def _restore_committed(self) -> None:
        index = self._committed_index
        with QSignalBlocker(self):
            if 0 <= index < self.count():
                super().setCurrentIndex(index)
                self.setEditText(self.itemText(index))
            else:
                super().setCurrentIndex(-1)
                self.setEditText("")

    def _select_existing_text(self) -> None:
        line_edit = self.lineEdit()
        if line_edit is not None and line_edit.text():
            line_edit.selectAll()

    def open_search_dialog(self) -> None:
        if self._f2_open or self.count() == 0:
            return
        self._f2_open = True
        dialog = ComboSearchDialog(self, self.window())
        result = dialog.exec_()
        self._f2_open = False
        if result == QDialog.Accepted and dialog.selected_index is not None:
            self.setCurrentIndex(dialog.selected_index)
        else:
            self._restore_committed()
        self.setFocus(Qt.OtherFocusReason)
        self._select_existing_text()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        line_edit = self.lineEdit()
        if watched is line_edit:
            if event.type() == QEvent.FocusIn:
                QTimer.singleShot(0, self._select_existing_text)
            elif event.type() == QEvent.MouseButtonPress:
                QTimer.singleShot(0, self._select_existing_text)
        if (
            event.type() == QEvent.KeyPress
            and event.key() == Qt.Key_F2
            and (watched is self or watched is line_edit)
        ):
            self.open_search_dialog()
            return True
        return super().eventFilter(watched, event)


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


def combo_current_data(combo: QComboBox):
    """Return data only when the visible text identifies an actual combo item."""
    if isinstance(combo, SearchableComboBox):
        return combo.currentData()
    index = matching_combo_index(combo, combo.currentText())
    return combo.itemData(index) if index >= 0 else None


def commit_combo_text(combo: QComboBox) -> None:
    """Commit an exact label or clear text that is not one of the available items."""
    if isinstance(combo, SearchableComboBox):
        combo.commit_search_text()
        return
    index = matching_combo_index(combo, combo.currentText())
    if index >= 0:
        combo.setCurrentIndex(index)
        return
    combo.setCurrentIndex(-1)
    combo.clearEditText()
