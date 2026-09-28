from datetime import date

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QDateEdit, QGridLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.reports.product_profitability import ProductProfitabilityService
from app.services.permission_service import PermissionService


def _money(value):
    return "-" if value is None else f"$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class ProductProfitabilityPage(QWidget):
    def __init__(self, *, user, service=None, parent=None):
        super().__init__(parent)
        PermissionService().require_administrator(user)
        self.service = service or ProductProfitabilityService()
        self.setObjectName("productProfitabilityPage")
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Rentabilidad por producto")
        title.setObjectName("pageTitle")
        header.addWidget(title, 1)
        today = date.today()
        self.date_from = QDateEdit(QDate(today.year, today.month, 1))
        self.date_from.setCalendarPopup(True); self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_to = QDateEdit(QDate(today.year, today.month, today.day))
        self.date_to.setCalendarPopup(True); self.date_to.setDisplayFormat("dd/MM/yyyy")
        refresh = QPushButton("Actualizar"); refresh.clicked.connect(self.refresh)
        header.addWidget(QLabel("Desde")); header.addWidget(self.date_from)
        header.addWidget(QLabel("Hasta")); header.addWidget(self.date_to); header.addWidget(refresh)
        root.addLayout(header)
        self.coverage = QLabel(); self.coverage.setObjectName("profitabilityCoverageLabel"); root.addWidget(self.coverage)
        cards = QGridLayout()
        self.sales = QLabel("-"); self.cost = QLabel("-"); self.profit = QLabel("-"); self.margin = QLabel("-")
        for col,(label,widget) in enumerate((("Ventas",self.sales),("Costo conocido",self.cost),("Utilidad bruta",self.profit),("Margen bruto",self.margin))):
            box=QVBoxLayout(); box.addWidget(QLabel(label)); box.addWidget(widget); cards.addLayout(box,0,col)
        root.addLayout(cards)
        summary_title = QLabel("Resumen por producto")
        summary_title.setObjectName("sectionTitle")
        root.addWidget(summary_title)
        summary_headers=("Producto","Cantidad","Venta neta","Costo conocido","Utilidad bruta","Margen","Cobertura")
        self.summary_table=QTableWidget(0,len(summary_headers))
        self.summary_table.setObjectName("profitabilitySummaryTable")
        self.summary_table.setHorizontalHeaderLabels(summary_headers)
        self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.setMaximumHeight(230)
        root.addWidget(self.summary_table)

        detail_title = QLabel("Detalle por operación")
        detail_title.setObjectName("sectionTitle")
        root.addWidget(detail_title)
        headers=("Fecha","Orden","Cliente","Producto","Cantidad","Precio venta","Costo aplicado","Venta","Costo total","Utilidad","Margen")
        self.table=QTableWidget(0,len(headers)); self.table.setObjectName("profitabilityDetailTable"); self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.setAlternatingRowColors(True); self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.table,1)
        self.refresh()

    def refresh(self):
        a=self.date_from.date(); b=self.date_to.date()
        snap=self.service.snapshot(date(a.year(),a.month(),a.day()),date(b.year(),b.month(),b.day()))
        self.sales.setText(_money(snap.sales)); self.cost.setText(_money(snap.cost)); self.profit.setText(_money(snap.gross_profit))
        self.margin.setText("-" if snap.margin_percent is None else f"{snap.margin_percent:.2f}%")
        self.coverage.setText(f"Cobertura de costos: {snap.cost_coverage_percent:.2f}% de las ventas. Los costos no informados no se consideran costo cero.")
        self.summary_table.setRowCount(len(snap.products))
        for r,row in enumerate(snap.products):
            vals=(row.product,f"{row.quantity:g} {row.unit}",_money(row.sales),_money(row.cost),_money(row.gross_profit),"-" if row.margin_percent is None else f"{row.margin_percent:.2f}%",f"{row.cost_coverage_percent:.2f}%")
            for col,val in enumerate(vals): self.summary_table.setItem(r,col,QTableWidgetItem(val))
        self.summary_table.resizeColumnsToContents()
        self.table.setRowCount(len(snap.lines))
        for r,row in enumerate(snap.lines):
            vals=(row.date.strftime("%d/%m/%Y"),str(row.order_number),row.client,row.product,f"{row.quantity:g} {row.unit}",_money(row.sale_unit_price),_money(row.applied_unit_cost),_money(row.sale_amount),_money(row.cost_amount),_money(row.gross_profit),"-" if row.margin_percent is None else f"{row.margin_percent:.2f}%")
            for col,val in enumerate(vals): self.table.setItem(r,col,QTableWidgetItem(val))
        self.table.resizeColumnsToContents()
