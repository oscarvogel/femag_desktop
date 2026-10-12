from __future__ import annotations

from datetime import date

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath
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
from app.models.masters import Product
from app.reports.managerial_dashboard import ManagerialDashboardService, ReportPeriod
from app.services.permission_service import PermissionService


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
    ("Mayor TN anterior", "previous_tonnes"),
    ("Mayor variación", "variation"),
    ("Cliente A–Z", "client"),
)


def _fmt_money(value: float) -> str:
    return f"$ {value:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


class RepurchaseBarChart(QWidget):
    """Gráfico simple de dos barras (TN anterior vs actual), sin dependencias.

    Respeta la paleta del tema activo en lugar de forzar modo oscuro.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("repurchaseChart")
        self.setMinimumHeight(190)
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
    ):
        super().__init__(parent)
        self.setObjectName("managerialRepurchaseDialog")
        self.setWindowTitle("Análisis de recompra por producto (períodos equivalentes)")
        self.resize(1100, 660)
        self.service = service or ManagerialDashboardService()
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
        filters.addWidget(QLabel("Actual:"))
        filters.addWidget(self.current_from)
        filters.addWidget(self.current_to)
        filters.addWidget(QLabel("Anterior:"))
        filters.addWidget(self.previous_from)
        filters.addWidget(self.previous_to)
        filters.addWidget(QLabel("Producto:"))
        filters.addWidget(self.product_combo, 1)
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
        self.order_combo.currentIndexChanged.connect(self.refresh)
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
        export_html = QPushButton("Exportar HTML")
        export_html.setObjectName("repurchaseExportHtmlButton")
        export_html.setToolTip("Genera un informe HTML con gráficos y tablas, listo para compartir")
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
            ("Cliente", "Vendedor", "Últ. compra ant.", "TN ant.", "TN actual", "Dif. TN", "Var. kilos %", "Valorizado actual", "Situación")
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close)
        root.addLayout(footer)
        self.refresh()

    def _load_products(self) -> None:
        self.product_combo.addItem("Todos los artículos", None)
        if database_proxy.obj is None:
            return
        for row in Product.select(Product.id, Product.codigo, Product.name).order_by(Product.name).dicts():
            label = row["name"]
            if row.get("codigo"):
                label = f"{row['codigo']} · {label}"
            self.product_combo.addItem(label, int(row["id"]))

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
        status_filter = self.status_combo.currentData()
        rows = self.service.product_client_repurchase(
            current,
            previous,
            product_id=product_id,
            client_query=self.search_input.text(),
            order_by=self.order_combo.currentData() or "default",
        )
        if status_filter:
            rows = [r for r in rows if r["status"] == status_filter]
        summary = self.service.product_repurchase_summary(current, previous, product_id=product_id)
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
            for j, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if j in (3, 4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if row["status"] == "sin_recompra":
                    item.setBackground(QColor("#fdf0ef"))
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()

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
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar recompra", "recompra_por_producto.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            user = getattr(self.parent(), "user", None) if self.parent() is not None else None
            if user is not None and not PermissionService().can_view_managerial_dashboard(user):
                raise PermissionError("No tiene permiso gerencial para exportar.")
            chart_png = self._chart_temp_png()
            out = export_repurchase_xlsx(
                self.service, current, path, previous=previous, product_id=product_id,
                chart_image=chart_png,
            )
        except PermissionError as exc:
            QMessageBox.warning(self, "Exportar recompra", str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - mostrar error amable en UI
            QMessageBox.warning(self, "Exportar recompra", f"No se pudo exportar:\n{exc}")
            return
        QMessageBox.information(self, "Exportar recompra", f"Exportado:\n{out}")

    def export_html(self) -> None:
        from app.reports.managerial_repurchase_export import export_repurchase_html

        current, previous = self._current_periods()
        product_id = self.product_combo.currentData()
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar recompra HTML", "recompra_por_producto.html", "HTML (*.html)"
        )
        if not path:
            return
        try:
            out = export_repurchase_html(
                self.service, current, path, previous=previous, product_id=product_id,
                product_label=self.product_combo.currentText(),
            )
        except Exception as exc:  # noqa: BLE001 - mostrar error amable en UI
            QMessageBox.warning(self, "Exportar recompra", f"No se pudo exportar:\n{exc}")
            return
        QMessageBox.information(self, "Exportar recompra", f"Exportado:\n{out}")

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
