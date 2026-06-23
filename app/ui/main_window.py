from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck
from app.services.driver_availability_service import DriverAvailabilityService
from app.services.load_order_print_service import LoadOrderPrintService
from app.services.load_order_service import LoadOrderService
from app.ui.dashboard import DashboardService, future_module_message
from app.ui.menu import build_menu


FIELD_LABELS = {
    "name": "Nombre",
    "cuit": "CUIT",
    "iva_condition": "IVA",
    "phone": "Teléfono",
    "email": "Email",
    "contact": "Contacto",
    "active": "Activo",
    "unit": "Unidad",
    "document": "Documento",
    "available": "Disponible",
    "type": "Tipo",
    "measure": "Medida",
    "weight": "Peso",
    "domain": "Dominio",
}


class MainWindow(QMainWindow):
    def __init__(self, user=None, export_dir: str | Path = "docs/screenshots/entrega2_ui_review/exports"):
        super().__init__()
        self.user = user
        self.export_dir = Path(export_dir)
        self.setWindowTitle("FEMAG Desktop - Panel operativo")
        self.resize(1280, 820)
        self.pages = QStackedWidget()
        self.menu = QListWidget()
        self.menu.setObjectName("sideMenu")
        self.menu.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.status_message = QLabel("")
        self.status_message.setObjectName("statusMessage")
        self._build_shell()
        self._apply_style()
        self.open_dashboard()

    def _build_shell(self) -> None:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        side_layout = QVBoxLayout(sidebar)
        brand = QLabel("FEMAG")
        brand.setObjectName("brand")
        profile = QLabel(f"Usuario: {self.user.username if self.user else 'demo'}")
        profile.setObjectName("profile")
        side_layout.addWidget(brand)
        side_layout.addWidget(profile)
        side_layout.addWidget(self.menu, 1)

        for section in build_menu(self.user):
            if not section.items:
                continue
            header = QListWidgetItem(section.title.upper())
            header.setFlags(Qt.NoItemFlags)
            header.setData(Qt.UserRole, None)
            self.menu.addItem(header)
            for item in section.items:
                row = QListWidgetItem(("Próx. - " if item.placeholder else "") + item.title)
                row.setData(Qt.UserRole, item.title)
                row.setData(Qt.UserRole + 1, item.placeholder)
                self.menu.addItem(row)
        self.menu.currentItemChanged.connect(self._menu_changed)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(22, 18, 22, 18)
        content_layout.addWidget(self.status_message)
        content_layout.addWidget(self.pages, 1)

        layout.addWidget(sidebar, 0)
        layout.addWidget(content, 1)
        self.setCentralWidget(root)

    def _menu_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if not current:
            return
        title = current.data(Qt.UserRole)
        if not title:
            return
        if current.data(Qt.UserRole + 1):
            self._set_page(self._placeholder_page(title))
            return
        handlers = {
            "Dashboard": self.open_dashboard,
            "Accesos rápidos": self.open_dashboard,
            "Pendientes": self.open_dashboard,
            "Clientes": lambda: self._set_page(
                self._table_page("Clientes", Client, ["name", "cuit", "iva_condition", "phone", "email"])
            ),
            "Domicilios": self.open_addresses,
            "Productos": lambda: self._set_page(self._table_page("Productos", Product, ["name", "unit", "active"])),
            "Choferes": lambda: self._set_page(self._table_page("Choferes", Driver, ["name", "document", "phone", "available"])),
            "Transportistas": lambda: self._set_page(self._table_page("Transportistas", Carrier, ["name", "cuit", "phone", "active"])),
            "Camiones": self.open_trucks,
            "Pallets / tipos de pallet": lambda: self._set_page(self._table_page("Tipos de pallets", PalletType, ["type", "measure", "weight", "active"])),
            "Órdenes de carga": self.open_load_orders,
            "Backups": lambda: self._set_page(self._placeholder_page("Backups")),
            "Auditoría": lambda: self._set_page(self._placeholder_page("Auditoría")),
            "Usuarios": lambda: self._set_page(self._placeholder_page("Usuarios")),
            "Perfiles": lambda: self._set_page(self._placeholder_page("Perfiles")),
            "Permisos por menú": lambda: self._set_page(self._placeholder_page("Permisos por menú")),
            "Parámetros": lambda: self._set_page(self._placeholder_page("Parámetros")),
        }
        handlers.get(title, lambda: self._set_page(self._placeholder_page(title)))()

    def open_dashboard(self) -> None:
        summary = DashboardService().summary()
        page = self._page("Dashboard operativo", "Indicadores de despacho y accesos rápidos para secretaría.")
        grid = QGridLayout()
        labels = [
            ("Clientes", summary["clientes"]),
            ("Productos", summary["productos"]),
            ("Choferes", summary["choferes"]),
            ("Transportistas", summary["transportistas"]),
            ("Órdenes hoy", summary["ordenes_hoy"]),
            ("Pendientes", summary["ordenes_pendientes"]),
            ("Choferes bloqueados", summary["choferes_bloqueados"]),
            ("Último backup", summary["ultimo_backup"] or "Sin registro"),
        ]
        for index, (label, value) in enumerate(labels):
            grid.addWidget(self._metric_card(label, str(value)), index // 4, index % 4)
        page.layout().addLayout(grid)

        actions = QHBoxLayout()
        new_order = QPushButton("Nueva orden de carga")
        new_order.setObjectName("largePrimaryButton")
        new_order.clicked.connect(self.open_load_orders)
        actions.addWidget(new_order)
        actions.addStretch()
        page.layout().addLayout(actions)
        self._set_page(page)

    def open_addresses(self) -> None:
        rows = [
            [address.client.name, address.address_type, address.city, address.address, "Sí" if address.is_primary else "No"]
            for address in ClientAddress.select().join(Client).order_by(Client.name, ClientAddress.address_type)
        ]
        self._set_page(self._static_table_page("Domicilios", ["Cliente", "Tipo", "Ciudad", "Domicilio", "Principal"], rows))

    def open_trucks(self) -> None:
        rows = [
            [truck.domain, truck.carrier.name if truck.carrier else "", "Sí" if truck.active else "No"]
            for truck in Truck.select().order_by(Truck.domain)
        ]
        self._set_page(self._static_table_page("Camiones", ["Dominio", "Transportista", "Activo"], rows))

    def open_load_orders(self) -> None:
        page = self._page("Órdenes de carga", "Carga operativa con productos, pallets, bloqueo de chofer e impresión.")
        top = QHBoxLayout()
        top.addWidget(self._orders_table(), 2)
        top.addWidget(self._order_form(), 1)
        page.layout().addLayout(top)
        self._set_page(page)

    def _order_form(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        title = QLabel("Nueva orden")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.client_combo = self._combo(Client.select().order_by(Client.name), lambda c: c.name)
        self.address_combo = self._combo(ClientAddress.select().order_by(ClientAddress.address), lambda a: f"{a.client.name} - {a.address}")
        self.carrier_combo = self._combo(Carrier.select().order_by(Carrier.name), lambda c: c.name)
        self.driver_combo = self._combo(Driver.select().order_by(Driver.name), lambda d: f"{d.name} ({'libre' if d.available else 'bloqueado'})")
        self.truck_combo = self._combo(Truck.select().order_by(Truck.domain), lambda t: t.domain)
        self.product_combo = self._combo(Product.select().order_by(Product.name), lambda p: p.name)
        self.product_qty = QSpinBox()
        self.product_qty.setRange(1, 999999)
        self.product_qty.setValue(500)
        self.second_product_combo = self._combo(Product.select().order_by(Product.name), lambda p: p.name)
        self.second_product_qty = QSpinBox()
        self.second_product_qty.setRange(1, 999999)
        self.second_product_qty.setValue(250)
        self.pallet_combo = self._combo(PalletType.select().order_by(PalletType.type), lambda p: f"{p.type} - {p.measure}")
        self.pallet_qty = QSpinBox()
        self.pallet_qty.setRange(0, 999)
        self.pallet_qty.setValue(8)
        self.observations = QTextEdit("Carga demo generada desde revisión visual.")
        self.observations.setFixedHeight(70)

        form = QFormLayout()
        form.addRow("Cliente", self.client_combo)
        form.addRow("Domicilio entrega", self.address_combo)
        form.addRow("Transportista", self.carrier_combo)
        form.addRow("Chofer", self.driver_combo)
        form.addRow("Camión", self.truck_combo)
        form.addRow("Producto 1", self.product_combo)
        form.addRow("Cantidad 1", self.product_qty)
        form.addRow("Producto 2", self.second_product_combo)
        form.addRow("Cantidad 2", self.second_product_qty)
        form.addRow("Pallet", self.pallet_combo)
        form.addRow("Cantidad pallets", self.pallet_qty)
        form.addRow("Observaciones", self.observations)
        layout.addLayout(form)

        save = QPushButton("Guardar orden")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_order)
        blocked = QPushButton("Probar chofer bloqueado")
        blocked.clicked.connect(self.try_blocked_driver)
        print_button = QPushButton("Exportar orden y hoja resumen")
        print_button.clicked.connect(self.export_latest_order)
        layout.addWidget(save)
        layout.addWidget(blocked)
        layout.addWidget(print_button)
        return panel

    def save_order(self) -> None:
        try:
            order = LoadOrderService(current_user=self.user.username if self.user else "demo").create_order(
                client=self.client_combo.currentData(),
                delivery_address=self.address_combo.currentData(),
                carrier=self.carrier_combo.currentData(),
                driver=self.driver_combo.currentData(),
                truck=self.truck_combo.currentData(),
                products=[
                    {"product": self.product_combo.currentData(), "quantity": self.product_qty.value()},
                    {"product": self.second_product_combo.currentData(), "quantity": self.second_product_qty.value()},
                ],
                pallets=[
                    {"pallet_type": self.pallet_combo.currentData(), "quantity": self.pallet_qty.value()},
                ],
                observations=self.observations.toPlainText(),
            )
        except ValueError as exc:
            self._show_warning(str(exc))
            return
        self._show_info(f"Orden {order.order_number} guardada. El chofer quedó bloqueado por carga activa.")
        self.open_load_orders()

    def try_blocked_driver(self) -> None:
        blocked = Driver.select().where(Driver.available == False).first()  # noqa: E712
        if not blocked:
            self._show_info("No hay choferes bloqueados en este momento.")
            return
        try:
            DriverAvailabilityService().ensure_available(blocked)
        except ValueError as exc:
            self._show_warning(str(exc))
            return
        self._show_info("El chofer seleccionado está disponible.")

    def export_latest_order(self) -> None:
        order = LoadOrder.select().order_by(LoadOrder.order_number.desc()).first()
        if not order:
            self._show_warning("No hay órdenes para imprimir.")
            return
        service = LoadOrderPrintService(current_user=self.user.username if self.user else "demo")
        order_path = service.export_order(order, self.export_dir, reprint=True)
        summary_path = service.export_summary(order, self.export_dir, reprint=True)
        service.export_combined(order, self.export_dir, reprint=True)
        self._show_info(f"Archivos generados:\n{order_path}\n{summary_path}")

    def _orders_table(self) -> QTableWidget:
        rows = []
        for order in LoadOrder.select().order_by(LoadOrder.order_number.desc()):
            rows.append(
                [
                    order.order_number,
                    order.date.strftime("%d/%m/%Y"),
                    order.client.name,
                    order.driver.name,
                    order.truck.domain,
                    order.status,
                ]
            )
        return self._table(["Nro.", "Fecha", "Cliente", "Chofer", "Camión", "Estado"], rows)

    def _table_page(self, title: str, model, fields: list[str]) -> QWidget:
        rows = [[self._value(getattr(row, field)) for field in fields] for row in model.select()]
        return self._static_table_page(title, fields, rows)

    def _static_table_page(self, title: str, headers: list[str], rows: list[list]) -> QWidget:
        page = self._page(title, "Vista de consulta para revisar datos maestros de FEMAG.")
        toolbar = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Buscar...")
        toolbar.addWidget(search)
        toolbar.addWidget(QPushButton("Actualizar"))
        page.layout().addLayout(toolbar)
        page.layout().addWidget(self._table(headers, rows), 1)
        return page

    def _placeholder_page(self, title: str) -> QWidget:
        page = self._page(title, future_module_message())
        notice = QLabel("Módulo planificado para una próxima entrega. No es una función rota.")
        notice.setObjectName("placeholder")
        notice.setAlignment(Qt.AlignCenter)
        page.layout().addWidget(notice, 1)
        return page

    def _page(self, title: str, subtitle: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        subheading = QLabel(subtitle)
        subheading.setObjectName("pageSubtitle")
        subheading.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(subheading)
        return page

    def _set_page(self, page: QWidget) -> None:
        self.pages.addWidget(page)
        self.pages.setCurrentWidget(page)
        self.status_message.setText("")

    def _metric_card(self, title: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        layout.addWidget(value_label)
        layout.addWidget(title_label)
        return card

    def _table(self, headers: list[str], rows: list[list]) -> QTableWidget:
        table = QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels([FIELD_LABELS.get(header, header) for header in headers])
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setWordWrap(False)
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                table.setItem(row_index, col_index, QTableWidgetItem(self._value(value)))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        return table

    def _combo(self, rows, labeler):
        combo = QComboBox()
        for row in rows:
            combo.addItem(labeler(row), row)
        return combo

    def _show_warning(self, text: str) -> None:
        self.status_message.setText(text)
        QMessageBox.warning(self, "FEMAG", text)

    def _show_info(self, text: str) -> None:
        self.status_message.setText(text)
        QMessageBox.information(self, "FEMAG", text)

    def _value(self, value) -> str:
        if isinstance(value, bool):
            return "Sí" if value else "No"
        return "" if value is None else str(value)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f6f7f9; color: #1f2933; font-size: 13px; }
            QWidget#sidebar { background: #263445; min-width: 250px; max-width: 250px; }
            QLabel#brand { color: white; font-size: 24px; font-weight: 700; padding: 18px 16px 2px; }
            QLabel#profile { color: #cbd5e1; padding: 0 16px 12px; }
            QListWidget#sideMenu { background: #263445; color: #edf2f7; border: 0; padding: 8px; }
            QListWidget#sideMenu::item { padding: 8px 10px; border-radius: 4px; }
            QListWidget#sideMenu::item:selected { background: #1f6feb; color: white; }
            QLabel#pageTitle { font-size: 24px; font-weight: 700; }
            QLabel#pageSubtitle { color: #52606d; margin-bottom: 12px; }
            QLabel#sectionTitle { font-size: 17px; font-weight: 700; }
            QLabel#placeholder { color: #52606d; font-size: 18px; border: 1px dashed #9aa4b2; border-radius: 6px; padding: 40px; }
            QLabel#statusMessage { color: #8a4b00; font-weight: 600; min-height: 22px; }
            QFrame#metricCard, QFrame#panel { background: white; border: 1px solid #d6dbe3; border-radius: 6px; }
            QLabel#metricValue { font-size: 24px; font-weight: 700; color: #1f6feb; }
            QLabel#metricTitle { color: #52606d; }
            QTableWidget { background: white; gridline-color: #d6dbe3; alternate-background-color: #f0f3f7; }
            QHeaderView::section { background: #e8edf3; padding: 6px; border: 0; font-weight: 600; }
            QLineEdit, QComboBox, QSpinBox, QTextEdit { background: white; border: 1px solid #b8c0cc; border-radius: 4px; padding: 6px; }
            QPushButton { background: #ffffff; border: 1px solid #9aa4b2; border-radius: 4px; padding: 8px 12px; }
            QPushButton#primaryButton, QPushButton#largePrimaryButton { background: #1f6feb; color: white; border-color: #1f6feb; font-weight: 600; }
            QPushButton#largePrimaryButton { font-size: 18px; padding: 16px 22px; }
            """
        )
