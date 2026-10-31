from __future__ import annotations

import os
import tempfile
from datetime import date, datetime
from pathlib import Path

from PyQt5.QtCore import QDate, QThreadPool, QUrl, Qt
from PyQt5.QtGui import QColor, QDesktopServices, QPainter, QPainterPath
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config.database import database_proxy
from app.models.masters import Client, Product, Salesperson
from app.reports.managerial_dashboard import ManagerialDashboardService, ReportPeriod
from app.reports.managerial_repurchase_pdf import export_repurchase_pdf
from app.services.permission_service import PermissionService
from app.services.repurchase_followup_service import (
    build_followup_message_for_row,
    period_phrase,
)
from app.services.whatsapp_envio_service import WhatsAppEnvioService
from app.ui.whatsapp_send import WhatsAppTextDialog, WhatsAppTextWorker


def _fmt_tn(value: float) -> str:
    return f"{value:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct(value: float | None, current_kilos: float = 0.0) -> str:
    if value is None:
        return "Nuevo" if current_kilos else "—"
    return f"{value:+.1f}%".replace(".", ",")


STATUS_LABELS = {
    "sin_recompra": "Sin recompra ⚠",
    "compro_menos": "Compró menos",
    "igual": "Sin cambios",
    "compro_mas": "Compró más",
    "nuevo": "Nuevo en el período",
}

STATUS_OPTIONS = (
    ("Todas", ""),
    ("Sin recompra", "sin_recompra"),
    ("Compró menos", "compro_menos"),
    ("Sin cambios", "igual"),
    ("Compró más", "compro_mas"),
    ("Nuevo en el período", "nuevo"),
)

ORDER_OPTIONS = (
    ("Sin recompra primero", "default"),
    ("Mayor TN actual", "current_tonnes"),
    ("Mayor TN anterior", "previous_tonnes"),
    ("Mayor variación", "variation"),
    ("Cliente A–Z", "client"),
)

STATUS_RANK = {
    "sin_recompra": 0,
    "compro_menos": 1,
    "igual": 2,
    "compro_mas": 3,
    "nuevo": 4,
}

WHATSAPP_STATUS_LABELS = {
    "queued": "encolado",
    "processing": "procesando",
    "accepted": "aceptado por WhatsApp",
    "delivered": "entregado",
    "read": "leído",
    "failed": "fallido",
}

# Columnas que se abren ordenadas de mayor a menor al hacer clic: fechas y
# números. "Dif. TN" ascendente muestra primero al que más dejó de comprar.
_DESCENDING_BY_DEFAULT = frozenset({2, 3, 4, 5, 6, 7})


def _fmt_money(value: float) -> str:
    return f"$ {value:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


class _SortableItem(QTableWidgetItem):
    """Celda con texto formateado y clave de orden real.

    El texto visible usa separadores de miles y comas decimales, así que
    ordenar por texto daría un resultado incorrecto (por ejemplo 99.000 antes
    que 8.500). Cada celda guarda la clave numérica/fecha con la que debe
    compararse y desempata por cliente para que el orden sea estable.
    """

    def __init__(self, text: str, sort_key: object, tie_breaker: str = ""):
        super().__init__(text)
        self._sort_key = sort_key
        self._tie_breaker = tie_breaker

    def __lt__(self, other: object) -> bool:  # noqa: D105 - comparación Qt
        if not isinstance(other, _SortableItem):
            return super().__lt__(other)
        return (self._sort_key, self._tie_breaker) < (other._sort_key, other._tie_breaker)


class RepurchaseBarChart(QWidget):
    """Gráfico simple de dos barras (TN anterior vs actual), sin dependencias.

    Respeta la paleta del tema activo en lugar de forzar modo oscuro.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("repurchaseChart")
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.prev_tn = 0.0
        self.cur_tn = 0.0
        self.prev_label = ""
        self.cur_label = ""

    def set_values(self, prev_tn: float, cur_tn: float, prev_label: str = "", cur_label: str = "") -> None:
        self.prev_tn = max(float(prev_tn or 0), 0.0)
        self.cur_tn = max(float(cur_tn or 0), 0.0)
        self.prev_label = prev_label
        self.cur_label = cur_label
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - firma Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = self.palette()
        text_color = palette.windowText().color()
        grid_color = QColor(text_color)
        grid_color.setAlpha(45)
        bar_color = QColor("#2e5fa3")
        bar_down = QColor("#c43b47") if self.cur_tn < self.prev_tn else QColor("#11875d")

        width, height = self.width(), self.height()
        left, right, top, bottom = 52, 12, 12, 30
        plot_w = max(width - left - right, 10)
        plot_h = max(height - top - bottom, 10)
        maximum = max(self.prev_tn, self.cur_tn, 1.0)
        # Escala "linda": redondea hacia arriba a 20/40/80...
        for step in (10, 20, 40, 80, 160, 320, 640):
            if maximum <= step:
                maximum = float(step)
                break
        else:
            maximum = float(maximum * 1.1)
        painter.setPen(grid_color)
        for frac, label in ((0.0, "0 tn"), (0.25, f"{maximum*0.25:.0f} tn"), (0.5, f"{maximum*0.5:.0f} tn"),
                            (0.75, f"{maximum*0.75:.0f} tn"), (1.0, f"{maximum:.0f} tn")):
            y = int(top + plot_h * (1 - frac))
            painter.drawLine(left, y, width - right, y)
            painter.setPen(text_color)
            painter.drawText(0, y - 8, left - 6, 16, Qt.AlignRight | Qt.AlignVCenter, label)
            painter.setPen(grid_color)
        slot = plot_w / 2.0
        bar_w = min(slot * 0.52, 120.0)
        for index, (value, label) in enumerate(((self.prev_tn, self.prev_label), (self.cur_tn, self.cur_label))):
            frac = (value / maximum) if maximum else 0.0
            bar_h = plot_h * frac
            x = left + slot * index + (slot - bar_w) / 2.0
            y = top + plot_h - bar_h
            path = QPainterPath()
            radius = 7.0
            path.addRoundedRect(x, y, bar_w, max(bar_h, 1.0), radius, radius)
            painter.fillPath(path, bar_color if index == 0 else bar_down)
            painter.setPen(text_color)
            painter.drawText(int(x) - 20, int(top + plot_h + 4), int(bar_w) + 40, 20,
                             Qt.AlignHCenter | Qt.AlignTop, label)
            painter.drawText(int(x) - 20, max(int(y - 20), 0), int(bar_w) + 40, 18,
                             Qt.AlignHCenter | Qt.AlignTop, f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        painter.end()

    def to_image(self, width: int = 640, height: int = 360):
        from PyQt5.QtGui import QImage

        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(Qt.white)
        previous_size = self.size()
        self.resize(width, height)
        painter = QPainter(image)
        self.render(painter)
        painter.end()
        self.resize(previous_size)
        return image


class VariationBar(QWidget):
    """Barra de variación: porción coloreada = actual/anterior (como la captura)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("repurchaseVariationBar")
        self.setMinimumHeight(12)
        self.setMaximumHeight(12)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.ratio = 1.0
        self.negative = False

    def set_ratio(self, previous: float, current: float) -> None:
        previous = float(previous or 0)
        current = float(current or 0)
        self.negative = current < previous
        self.ratio = min(current / previous, 1.0) if previous > 0 else (1.0 if current > 0 else 0.0)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - firma Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = QColor(self.palette().mid().color())
        fill = QColor("#c43b47") if self.negative else QColor("#11875d")
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 6, 6)
        painter.setBrush(fill)
        painter.drawRoundedRect(0, 0, int(self.width() * max(min(self.ratio, 1.0), 0.0)), self.height(), 6, 6)
        painter.end()


class ManagerialRepurchaseDialog(QDialog):
    """Análisis de recompra por producto (períodos equivalentes).

    Criterio principal: kilos/toneladas. La facturación solo se muestra
    como contexto para no distorsionar por precios. "Sin recompra" es una
    alerta comercial (no volvió a comprar en el corte), no una pérdida
    confirmada del cliente.
    """

    def __init__(
        self,
        *,
        service: ManagerialDashboardService | None = None,
        current: ReportPeriod | None = None,
        parent=None,
        initial_product_id: int | None = None,
        initial_client_query: str | None = None,
        initial_order_by: str | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("managerialRepurchaseDialog")
        self.setWindowTitle("Análisis de recompra por producto (períodos equivalentes)")
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint
        )
        self.setSizeGripEnabled(True)
        self.resize(1240, 820)
        self.setMinimumSize(900, 600)
        self.service = service or ManagerialDashboardService()
        self._whatsapp_workers: set[WhatsAppTextWorker] = set()
        current = current or ReportPeriod.preset("este mes")
        previous = current.previous_equivalent()

        root = QVBoxLayout(self)
        info = QLabel(
            "Compara el período actual contra su equivalente calendario (ej. 01–12/10 vs 01–12/09). "
            "El criterio es kilos/toneladas, no facturación. "
            "El vendedor mostrado es la asignación actual del cliente (proxy operativo, sin histórico por operación)."
        )
        info.setWordWrap(True)
        info.setObjectName("repurchaseInfoLabel")
        root.addWidget(info)

        filters = QHBoxLayout()
        self.current_from = QDateEdit(QDate(current.start.year, current.start.month, current.start.day))
        self.current_from.setCalendarPopup(True)
        self.current_from.setDisplayFormat("dd/MM/yyyy")
        self.current_to = QDateEdit(QDate(current.end.year, current.end.month, current.end.day))
        self.current_to.setCalendarPopup(True)
        self.current_to.setDisplayFormat("dd/MM/yyyy")
        self.previous_from = QDateEdit(QDate(previous.start.year, previous.start.month, previous.start.day))
        self.previous_from.setCalendarPopup(True)
        self.previous_from.setDisplayFormat("dd/MM/yyyy")
        self.previous_to = QDateEdit(QDate(previous.end.year, previous.end.month, previous.end.day))
        self.previous_to.setCalendarPopup(True)
        self.previous_to.setDisplayFormat("dd/MM/yyyy")
        self.product_combo = QComboBox()
        self.product_combo.setObjectName("repurchaseProductCombo")
        self._load_products()
        self.salesperson_combo = QComboBox()
        self.salesperson_combo.setObjectName("repurchaseSalespersonCombo")
        self.salesperson_combo.setToolTip(
            "Filtra por el vendedor asignado actualmente al cliente (proxy operativo)."
        )
        self._load_salespersons()
        self.salesperson_combo.currentIndexChanged.connect(self.refresh)
        filters.addWidget(QLabel("Actual:"))
        filters.addWidget(self.current_from)
        filters.addWidget(self.current_to)
        filters.addWidget(QLabel("Anterior:"))
        filters.addWidget(self.previous_from)
        filters.addWidget(self.previous_to)
        filters.addWidget(QLabel("Producto:"))
        filters.addWidget(self.product_combo, 1)
        filters.addWidget(QLabel("Vendedor:"))
        filters.addWidget(self.salesperson_combo, 1)
        root.addLayout(filters)

        second = QHBoxLayout()
        self.status_combo = QComboBox()
        self.status_combo.setObjectName("repurchaseStatusCombo")
        for label, key in STATUS_OPTIONS:
            self.status_combo.addItem(label, key)
        self.order_combo = QComboBox()
        self.order_combo.setObjectName("repurchaseOrderCombo")
        for label, key in ORDER_OPTIONS:
            self.order_combo.addItem(label, key)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("repurchaseSearchInput")
        self.search_input.setPlaceholderText("Buscar cliente…")
        self.search_input.textChanged.connect(self.refresh)
        self.status_combo.currentIndexChanged.connect(self.refresh)
        self.order_combo.currentIndexChanged.connect(self._on_order_changed)
        second.addWidget(QLabel("Situación:"))
        second.addWidget(self.status_combo)
        second.addWidget(QLabel("Orden:"))
        second.addWidget(self.order_combo, 1)
        second.addWidget(QLabel("Cliente:"))
        second.addWidget(self.search_input, 1)
        compare = QPushButton("Comparar")
        compare.setObjectName("repurchaseCompareButton")
        compare.clicked.connect(self.refresh)
        second.addWidget(compare)
        export = QPushButton("Exportar Excel")
        export.setObjectName("repurchaseExportButton")
        export.clicked.connect(self.export_excel)
        second.addWidget(export)
        export_html = QPushButton("Abrir informe web")
        export_html.setObjectName("repurchaseExportHtmlButton")
        export_html.setToolTip("Genera el informe en una carpeta temporal y lo abre en el navegador")
        export_html.clicked.connect(self.export_html)
        second.addWidget(export_html)
        root.addLayout(second)

        kpi_row = QHBoxLayout()
        self.prev_kpi = QLabel("")
        self.prev_kpi.setObjectName("repurchasePrevKpi")
        self.cur_kpi = QLabel("")
        self.cur_kpi.setObjectName("repurchaseCurKpi")
        for widget in (self.prev_kpi, self.cur_kpi):
            widget.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            widget.setWordWrap(True)
        kpi_row.addWidget(self.prev_kpi, 1)
        kpi_row.addWidget(self.cur_kpi, 1)
        root.addLayout(kpi_row)

        self.variation_label = QLabel("")
        self.variation_label.setObjectName("repurchaseVariationLabel")
        self.variation_label.setWordWrap(True)
        root.addWidget(self.variation_label)
        self.variation_bar = VariationBar()
        root.addWidget(self.variation_bar)

        self.chart = RepurchaseBarChart()
        self.chart_caption = QLabel("")
        self.chart_caption.setObjectName("repurchaseChartCaption")
        self.chart_caption.setWordWrap(True)
        root.addWidget(self.chart)
        root.addWidget(self.chart_caption)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("repurchaseSummaryLabel")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.table = QTableWidget(0, 9)
        self.table.setObjectName("repurchaseTable")
        self.table.setHorizontalHeaderLabels(
            ("Cliente", "Vendedor", "Últ. compra ant.", "TN ant.", "TN actual", "Dif. TN", "Var. %", "Val. actual", "Situación")
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, header.Stretch)
        for column in range(1, self.table.columnCount()):
            header.setSectionResizeMode(column, header.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(80)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.setToolTip("Clic en una columna para ordenar; otro clic invierte el sentido.")
        header.sectionClicked.connect(self._on_header_clicked)
        self._sort_column: int | None = None
        self._sort_order = Qt.DescendingOrder
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.itemSelectionChanged.connect(self._update_whatsapp_button)
        root.addWidget(self.table, 1)

        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        self.whatsapp_button = QPushButton("WhatsApp")
        self.whatsapp_button.setObjectName("repurchaseWhatsappButton")
        self.whatsapp_button.setEnabled(False)
        self.whatsapp_button.setToolTip(
            "Seleccioná un cliente en la tabla para enviarle un WhatsApp de seguimiento."
        )
        self.whatsapp_button.clicked.connect(self.send_whatsapp)
        self.print_button = QPushButton("Imprimir (PDF)")
        self.print_button.setObjectName("repurchasePrintButton")
        self.print_button.setToolTip("Genera el PDF del informe y lo abre para imprimir o guardar.")
        self.print_button.clicked.connect(self.print_report)
        self.whatsapp_status_label = QLabel("")
        self.whatsapp_status_label.setObjectName("repurchaseWhatsappStatusLabel")
        self.whatsapp_status_label.setWordWrap(True)
        footer.addWidget(self.whatsapp_button)
        footer.addWidget(self.print_button)
        footer.addWidget(self.whatsapp_status_label, 1)
        footer.addWidget(close)
        root.addLayout(footer)
        self._apply_initial_filters(
            product_id=initial_product_id,
            client_query=initial_client_query,
            order_by=initial_order_by,
        )
        self.refresh()

    def _apply_initial_filters(
        self,
        *,
        product_id: int | None,
        client_query: str | None,
        order_by: str | None,
    ) -> None:
        """Preselección para el drill-down desde el dashboard gerencial.

        Se aplica con señales bloqueadas para hacer un único refresh al final
        del __init__: el producto queda visible en el combo, el cliente en el
        buscador y el orden en su combo, todo editable por el usuario.
        """
        if product_id is not None:
            index = self.product_combo.findData(product_id)
            if index >= 0:
                self.product_combo.blockSignals(True)
                self.product_combo.setCurrentIndex(index)
                self.product_combo.blockSignals(False)
        if order_by:
            index = self.order_combo.findData(order_by)
            if index >= 0:
                self.order_combo.blockSignals(True)
                self.order_combo.setCurrentIndex(index)
                self.order_combo.blockSignals(False)
        if client_query:
            self.search_input.blockSignals(True)
            self.search_input.setText(client_query)
            self.search_input.blockSignals(False)

    def _load_products(self) -> None:
        self.product_combo.addItem("Todos los artículos", None)
        if database_proxy.obj is None:
            return
        for row in Product.select(Product.id, Product.codigo, Product.name).order_by(Product.name).dicts():
            label = row["name"]
            if row.get("codigo"):
                label = f"{row['codigo']} · {label}"
            self.product_combo.addItem(label, int(row["id"]))

    def _load_salespersons(self) -> None:
        self.salesperson_combo.addItem("Todos los vendedores", None)
        if database_proxy.obj is None:
            return
        for row in Salesperson.select(Salesperson.id, Salesperson.name).order_by(Salesperson.name).dicts():
            self.salesperson_combo.addItem(row["name"], int(row["id"]))

    @staticmethod
    def _qdate(widget: QDateEdit) -> date:
        value = widget.date()
        return date(value.year(), value.month(), value.day())

    def _current_periods(self) -> tuple[ReportPeriod, ReportPeriod]:
        current = ReportPeriod(self._qdate(self.current_from), self._qdate(self.current_to), "Actual")
        previous = ReportPeriod(self._qdate(self.previous_from), self._qdate(self.previous_to), "Anterior")
        return current, previous

    def refresh(self) -> None:
        current, previous = self._current_periods()
        product_id = self.product_combo.currentData()
        salesperson_id = self.salesperson_combo.currentData()
        status_filter = self.status_combo.currentData()
        rows = self.service.product_client_repurchase(
            current,
            previous,
            product_id=product_id,
            salesperson_id=salesperson_id,
            client_query=self.search_input.text(),
            order_by=self.order_combo.currentData() or "default",
        )
        if status_filter:
            rows = [r for r in rows if r["status"] == status_filter]
        summary = self.service.product_repurchase_summary(
            current, previous, product_id=product_id, salesperson_id=salesperson_id
        )
        prev_short = f"{previous.start.day}–{previous.end.day} {previous.start:%b}".replace(" 0", " ")
        cur_short = f"{current.start.day}–{current.end.day} {current.start:%b}".replace(" 0", " ")
        var_pct = summary["variation_percent"]
        var_text = "—" if var_pct is None else f"{var_pct:+.2f}%".replace(".", ",")
        self.prev_kpi.setText(
            f"{previous.start.day}–{previous.end.day} {previous.start:%B}\n"
            f"{_fmt_tn(summary['previous_tonnes'])} tn\n{_fmt_money(summary['previous_total'])}"
        )
        self.cur_kpi.setText(
            f"{current.start.day}–{current.end.day} {current.start:%B}\n"
            f"{_fmt_tn(summary['current_tonnes'])} tn\n{_fmt_money(summary['current_total'])}"
        )
        days = current.days
        self.variation_label.setText(
            f"Variación en toneladas    {var_text}\n"
            f"Se despacharon {_fmt_tn(abs(summary['diff_tonnes']))} toneladas "
            f"{'menos' if summary['diff_tonnes'] < 0 else 'más'} en los mismos {days} días."
        )
        self.variation_bar.set_ratio(summary["previous_tonnes"], summary["current_tonnes"])
        self.chart.set_values(summary["previous_tonnes"], summary["current_tonnes"], prev_short, cur_short)
        product_caption = self.product_combo.currentText() if product_id else "todos los artículos"
        self.chart_caption.setText(f"Volumen despachado de {product_caption}, en toneladas.")
        self.summary_label.setText(
            f"Anterior {previous.describe_range()} vs actual {current.describe_range()}: "
            f"{summary['previous_tonnes']:,.3f} → {summary['current_tonnes']:,.3f} TN "
            f"({summary['diff_tonnes']:+,.3f} TN). "
            f"{summary['count_sin_recompra']} sin recompra ({_fmt_tn(summary['lost_tonnes'])} TN de referencia ⚠ alerta comercial, no pérdida confirmada), "
            f"{summary['count_redujeron']} compraron menos, "
            f"{summary['count_aumentaron']} compraron más, "
            f"{summary['count_nuevos']} nuevos en el período. "
            f"Conciliación: {summary['reconciled_diff_tonnes']:+,.3f} TN "
            f"({'cuadra' if summary['reconciliation_ok'] else 'NO cuadra'})."
        )
        self.table.setRowCount(len(rows))
        alert_bg, alert_fg = self._alert_colors()
        for i, row in enumerate(rows):
            values = (
                row["client_name"],
                row.get("salesperson_name") or "—",
                self._fmt_date(row.get("previous_last_date")),
                _fmt_tn(row["previous_tonnes"]),
                _fmt_tn(row["current_tonnes"]),
                _fmt_tn(row["diff_tonnes"]),
                _fmt_pct(row["variation_kilos_percent"], row["current_kilos"]),
                f"$ {row['current_total']:,.2f}",
                STATUS_LABELS.get(row["status"], row["status"]),
            )
            sort_keys = (
                row["client_name"] or "",
                row.get("salesperson_name") or "",
                row.get("previous_last_date") or "",
                float(row["previous_tonnes"]),
                float(row["current_tonnes"]),
                float(row["diff_tonnes"]),
                float(row["variation_kilos_percent"])
                if row["variation_kilos_percent"] is not None
                else 0.0,
                float(row["current_total"]),
                STATUS_RANK.get(row["status"], 9),
            )
            for j, (value, sort_key) in enumerate(zip(values, sort_keys)):
                item = _SortableItem(str(value), sort_key, row["client_name"] or "")
                if j == 0:
                    item.setData(Qt.UserRole, row)
                if j in (3, 4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if row["status"] == "sin_recompra":
                    # Fondo y texto explícitos: el fondo claro fijo con el texto
                    # claro del tema oscuro quedaba ilegible. Se eligen según el
                    # tema activo para mantener contraste en modo claro y oscuro.
                    item.setBackground(alert_bg)
                    item.setForeground(alert_fg)
                self.table.setItem(i, j, item)
        self._update_whatsapp_button()
        self._apply_sort()

    def _on_header_clicked(self, column: int) -> None:
        """Ordena la tabla por la columna clickeada; segundo clic invierte."""
        if column == self._sort_column:
            self._sort_order = (
                Qt.AscendingOrder
                if self._sort_order == Qt.DescendingOrder
                else Qt.DescendingOrder
            )
        else:
            self._sort_column = column
            self._sort_order = (
                Qt.DescendingOrder if column in _DESCENDING_BY_DEFAULT else Qt.AscendingOrder
            )
        self._apply_sort()

    def _apply_sort(self) -> None:
        if self._sort_column is None:
            return
        header = self.table.horizontalHeader()
        self.table.sortItems(self._sort_column, self._sort_order)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(self._sort_column, self._sort_order)

    def _on_order_changed(self) -> None:
        """El combo define un orden nuevo: se descarta el orden manual previo."""
        self._sort_column = None
        self.table.horizontalHeader().setSortIndicatorShown(False)
        self.refresh()

    # --------------------------------------------------------------- WhatsApp

    def _selected_row(self) -> dict | None:
        row_index = self.table.currentRow()
        if row_index < 0:
            return None
        item = self.table.item(row_index, 0)
        data = item.data(Qt.UserRole) if item is not None else None
        return data if isinstance(data, dict) else None

    def _update_whatsapp_button(self) -> None:
        has_selection = self._selected_row() is not None
        self.whatsapp_button.setEnabled(has_selection)
        if has_selection:
            self.whatsapp_button.setToolTip(
                "Envía un WhatsApp de seguimiento al cliente seleccionado."
            )
        else:
            self.whatsapp_button.setToolTip(
                "Seleccioná un cliente en la tabla para enviarle un WhatsApp de seguimiento."
            )

    def _current_user(self):
        """Usuario logueado, aunque el padre directo no lo exponga.

        El dashboard gerencial se arma como página dentro de la ventana
        principal; la página no guarda ``user``. Para que WhatsApp resuelva la
        instancia configurada hay que subir por la cadena de padres hasta la
        ventana que sí tiene el usuario de la sesión.
        """
        widget = self.parent()
        while widget is not None:
            user = getattr(widget, "user", None)
            if user is not None:
                return user
            widget = widget.parent()
        return None

    @staticmethod
    def _row_unit(row: dict) -> str:
        try:
            return Product.get_by_id(int(row["product_id"])).unit or "unidad"
        except Exception:
            return "unidad"

    def _followup_message_for_row(self, row: dict, *, client_name: str = "") -> str:
        current, previous = self._current_periods()
        return build_followup_message_for_row(
            row,
            self._row_unit(row),
            client_name=client_name,
            current_period=period_phrase(current.start, current.end),
            previous_period=period_phrase(previous.start, previous.end),
        )

    @staticmethod
    def _whatsapp_document_id(client_id: int, row: dict, period: ReportPeriod) -> str:
        product = row.get("product_id") or "todos"
        return (
            f"recompra:{client_id}:{product}:"
            f"{period.start:%Y%m%d}:{period.end:%Y%m%d}"
        )

    def send_whatsapp(self) -> None:
        row = self._selected_row()
        if row is None:
            QMessageBox.information(
                self, "WhatsApp", "Seleccioná un cliente en la tabla."
            )
            return
        try:
            client = Client.get_by_id(int(row["client_id"]))
        except Exception as exc:  # noqa: BLE001 - mostrar error amable en UI
            QMessageBox.warning(
                self, "WhatsApp", f"No se pudo leer el cliente:\n{exc}"
            )
            return

        greeting_name = (client.contact or client.name or "").strip()
        current, _ = self._current_periods()
        dialog = WhatsAppTextDialog(
            recipient_name=client.name,
            phone=client.phone or "",
            default_message=self._followup_message_for_row(
                row, client_name=greeting_name
            ),
            window_title="Enviar WhatsApp de seguimiento",
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        message = dialog.message()
        try:
            service = WhatsAppEnvioService()
            envio = service.create_text_attempt(
                tipo_documento="seguimiento_recompra",
                documento_id=self._whatsapp_document_id(client.id, row, current),
                destinatario=dialog.phone(),
                message=message,
                usuario=self._current_user(),
            )
        except Exception as exc:  # noqa: BLE001 - mostrar error amable en UI
            QMessageBox.warning(self, "WhatsApp", str(exc))
            return

        self.whatsapp_status_label.setText("WhatsApp: enviando...")
        worker = WhatsAppTextWorker(
            envio_id=envio.id,
            message=message,
            service=service,
        )
        self._whatsapp_workers.add(worker)
        worker.signals.succeeded.connect(self._whatsapp_succeeded)
        worker.signals.failed.connect(self._whatsapp_failed)
        worker.signals.finished.connect(
            lambda current_worker=worker: self._whatsapp_workers.discard(current_worker)
        )
        QThreadPool.globalInstance().start(worker)

    def _whatsapp_succeeded(self, envio) -> None:
        status = WHATSAPP_STATUS_LABELS.get(envio.estado, envio.estado)
        message_id = f" (ID {envio.message_id})" if envio.message_id else ""
        self.whatsapp_status_label.setText(f"WhatsApp: {status}{message_id}")

    def _whatsapp_failed(self, message: str) -> None:
        self.whatsapp_status_label.setText(f"WhatsApp: error - {message}")
        QMessageBox.warning(
            self, "WhatsApp", f"No se pudo completar el envío:\n{message}"
        )

    # -------------------------------------------------------------- Impresión

    def _displayed_table_rows(self) -> list[list[str]]:
        rows: list[list[str]] = []
        for row_index in range(self.table.rowCount()):
            values = []
            for column in range(self.table.columnCount()):
                item = self.table.item(row_index, column)
                values.append(item.text() if item is not None else "")
            rows.append(values)
        return rows

    def _filters_note(self) -> str:
        parts: list[str] = []
        if self.salesperson_combo.currentData() is not None:
            parts.append(f"Vendedor: {self.salesperson_combo.currentText()}")
        if self.status_combo.currentData():
            parts.append(f"Situación: {self.status_combo.currentText()}")
        client_query = self.search_input.text().strip()
        if client_query:
            parts.append(f"Cliente: {client_query}")
        if self._sort_column is not None:
            header = self.table.horizontalHeaderItem(self._sort_column)
            order = "descendente" if self._sort_order == Qt.DescendingOrder else "ascendente"
            parts.append(f"Orden: {header.text() if header else ''} {order}")
        elif self.order_combo.currentData() not in (None, "default"):
            parts.append(f"Orden: {self.order_combo.currentText()}")
        return " · ".join(parts)

    def export_report_pdf(self, path: str | Path) -> Path:
        """Genera el PDF con lo que muestra la tabla y el resumen en pantalla."""
        chart_png = self._chart_temp_png()
        try:
            return export_repurchase_pdf(
                path,
                title=f"A quién se le vendió: {self.product_combo.currentText()}",
                previous_kpi=self.prev_kpi.text(),
                current_kpi=self.cur_kpi.text(),
                variation_text=self.variation_label.text(),
                summary_text=self.summary_label.text(),
                chart_caption=self.chart_caption.text(),
                chart_image=chart_png,
                headers=[
                    (self.table.horizontalHeaderItem(column).text()
                     if self.table.horizontalHeaderItem(column) is not None else "")
                    for column in range(self.table.columnCount())
                ],
                rows=self._displayed_table_rows(),
                filters_note=self._filters_note(),
                generated_at=datetime.now(),
            )
        finally:
            if chart_png:
                try:
                    os.unlink(chart_png)
                except OSError:
                    pass

    def print_report(self) -> None:
        target_handle, target_name = tempfile.mkstemp(
            prefix="femag_recompra_", suffix=".pdf"
        )
        os.close(target_handle)
        try:
            out = self.export_report_pdf(target_name)
        except Exception as exc:  # noqa: BLE001 - mostrar error amable en UI
            try:
                os.unlink(target_name)
            except OSError:
                pass
            QMessageBox.warning(
                self, "Imprimir recompra", f"No se pudo generar el PDF:\n{exc}"
            )
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(out.resolve()))):
            QMessageBox.information(
                self,
                "Imprimir recompra",
                f"El PDF se generó correctamente en:\n{out}",
            )

    def _alert_colors(self, *, dark: bool | None = None) -> tuple[QColor, QColor]:
        """Fondo y texto de la fila 'sin recompra' con contraste en ambos temas.

        El tema FEMAG es por stylesheet (no por paleta), así que se consulta la
        preferencia guardada; la luminosidad de la paleta queda como respaldo.
        """
        if dark is None:
            try:
                from app.ui.theme import Theme, load_theme

                dark = load_theme() is Theme.DARK
            except Exception:
                dark = self.palette().window().color().lightness() < 128
        if dark:
            return QColor("#5a2326"), QColor("#ffd9d4")
        return QColor("#fdf0ef"), QColor("#8a1f24")

    @staticmethod
    def _fmt_date(value: str | None) -> str:
        if not value:
            return "—"
        try:
            year, month, day = value.split("-")
            return f"{day}/{month}/{year}"
        except ValueError:
            return str(value)

    def export_excel(self) -> None:
        from app.reports.managerial_repurchase_export import export_repurchase_xlsx

        current, previous = self._current_periods()
        product_id = self.product_combo.currentData()
        salesperson_id = self.salesperson_combo.currentData()
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar recompra", "recompra_por_producto.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            user = self._current_user()
            if user is not None and not PermissionService().can_view_managerial_dashboard(user):
                raise PermissionError("No tiene permiso gerencial para exportar.")
            chart_png = self._chart_temp_png()
            out = export_repurchase_xlsx(
                self.service, current, path, previous=previous, product_id=product_id,
                salesperson_id=salesperson_id, chart_image=chart_png,
            )
        except PermissionError as exc:
            QMessageBox.warning(self, "Exportar recompra", str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - mostrar error amable en UI
            QMessageBox.warning(self, "Exportar recompra", f"No se pudo exportar:\n{exc}")
            return
        QMessageBox.information(self, "Exportar recompra", f"Exportado:\n{out}")

    def export_html(self) -> None:
        from app.reports.managerial_repurchase_export import ManagerialRepurchaseHtmlReport

        current, previous = self._current_periods()
        product_id = self.product_combo.currentData()
        salesperson_id = self.salesperson_combo.currentData()
        try:
            report = ManagerialRepurchaseHtmlReport(
                service=self.service,
                current=current,
                previous=previous,
                product_id=product_id,
                salesperson_id=salesperson_id,
                product_label=self.product_combo.currentText(),
                salesperson_label=(
                    self.salesperson_combo.currentText()
                    if salesperson_id is not None
                    else ""
                ),
            )
            out = report.open()
        except Exception as exc:  # noqa: BLE001 - mostrar error amable en UI
            QMessageBox.warning(self, "Informe web de recompra", f"No se pudo generar:\n{exc}")
            return
        QMessageBox.information(
            self, "Informe web de recompra", f"Informe abierto en el navegador:\n{out}"
        )

    def _chart_temp_png(self) -> str | None:
        try:
            import tempfile

            image = self.chart.to_image()
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            image.save(tmp.name, "PNG")
            return tmp.name
        except Exception:
            return None
