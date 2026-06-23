from __future__ import annotations

from pathlib import Path

from peewee import SqliteDatabase
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config.database import bind_database
from app.models.masters import Client, Driver, Product
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService
from app.ui.dashboard import DashboardService, future_module_message
from app.ui.load_orders import build_load_order_form_spec
from app.ui.main_window import MainWindow as ShellBuilder
from scripts.seed_demo_data import DEMO_DB_PATH, seed_demo_data


def run_desktop_app(*, demo_mode: bool = False) -> int:
    if demo_mode:
        seed_demo_data()
        database = SqliteDatabase(DEMO_DB_PATH)
        bind_database(database)
        database.connect(reuse_if_open=True)
    PermissionService().seed_defaults()
    user = _demo_user()
    app = QApplication.instance() or QApplication([])
    window = FemagDesktopWindow(user=user, demo_mode=demo_mode)
    window.show()
    result = app.exec_()
    if demo_mode:
        database.close()
    return result


class FemagDesktopWindow(QMainWindow):
    def __init__(self, *, user, demo_mode: bool):
        super().__init__()
        self.shell = ShellBuilder(user=user, demo_mode=demo_mode).shell_spec
        self.setWindowTitle("FEMAG Desktop")
        self.resize(1280, 820)
        self.setStyleSheet(STYLES)
        self.stack = QStackedWidget()
        self.nav = QListWidget()
        self._route_indexes: dict[str, int] = {}
        self._build()

    def _build(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._topbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._sidebar(), 0)
        body.addWidget(self.stack, 1)
        layout.addLayout(body, 1)
        layout.addWidget(self._statusbar())

        self.setCentralWidget(root)
        self._add_page("dashboard", self._dashboard_page())
        self._add_page("clients", self._table_page("Clientes", ["Nombre", "CUIT", "Estado"], _client_rows()))
        self._add_page("products", self._table_page("Productos", ["Producto", "Unidad", "Estado"], _product_rows()))
        self._add_page("drivers", self._table_page("Choferes", ["Nombre", "Teléfono", "Disponible"], _driver_rows()))
        self._add_page("load_orders", self._load_order_page())
        self._add_page("placeholder", self._placeholder_page())
        self.nav.currentRowChanged.connect(self._navigate)
        self.nav.setCurrentRow(1)

    def _topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        layout = QHBoxLayout(bar)
        title = QLabel(self.shell.app_name)
        title.setObjectName("appTitle")
        subtitle = QLabel(self.shell.subtitle)
        user = QLabel(f"{self.shell.username} · {self.shell.profile} · {self.shell.connection_state}")
        user.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        layout.addWidget(user)
        return bar

    def _sidebar(self) -> QListWidget:
        self.nav.setObjectName("sidebar")
        self.nav.setFixedWidth(260)
        for section in self.shell.sidebar.sections if self.shell.sidebar else []:
            header = QListWidgetItem(section.title)
            header.setFlags(Qt.NoItemFlags)
            self.nav.addItem(header)
            for item in section.items:
                row = QListWidgetItem(f"  {item.title}")
                route = item.route_key or "placeholder"
                row.setData(Qt.UserRole, route)
                if item.placeholder:
                    row.setForeground(Qt.gray)
                    row.setToolTip(item.disabled_reason or future_module_message())
                self.nav.addItem(row)
        return self.nav

    def _statusbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("statusbar")
        layout = QHBoxLayout(bar)
        layout.addWidget(
            QLabel(
                f"{self.shell.status_bar.version} · {self.shell.status_bar.state} · "
                f"Último backup {self.shell.status_bar.last_backup}"
            )
        )
        return bar

    def _add_page(self, route: str, widget: QWidget) -> None:
        self._route_indexes[route] = self.stack.addWidget(widget)

    def _navigate(self, row: int) -> None:
        item = self.nav.item(row)
        if not item:
            return
        route = item.data(Qt.UserRole)
        if route in self._route_indexes:
            self.stack.setCurrentIndex(self._route_indexes[route])

    def _dashboard_page(self) -> QWidget:
        spec = DashboardService().view_spec(demo_mode=True)
        page = _page(spec.title)
        layout = page.layout()
        actions = QHBoxLayout()
        for action in spec.quick_actions:
            button = QPushButton(action.title)
            button.setEnabled(action.enabled)
            button.setMinimumHeight(52)
            actions.addWidget(button)
        layout.addLayout(actions)
        cards = QGridLayout()
        for index, (title, value) in enumerate(spec.summary_cards.items()):
            cards.addWidget(_card(title, str(value)), index // 3, index % 3)
        layout.addLayout(cards)
        layout.addWidget(QLabel("Pendientes y alertas"))
        for alert in spec.alerts:
            layout.addWidget(QLabel(f"• {alert}"))
        layout.addStretch(1)
        return page

    def _table_page(self, title: str, columns: list[str], rows: list[list[str]]) -> QWidget:
        page = _page(title)
        layout = page.layout()
        layout.addWidget(QLabel(f"Buscar en {title.lower()}..."))
        table = QTableWidget(len(rows), len(columns))
        table.setHorizontalHeaderLabels(columns)
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(value))
        layout.addWidget(table)
        layout.addStretch(1)
        return page

    def _load_order_page(self) -> QWidget:
        spec = build_load_order_form_spec()
        page = _page(spec.title)
        layout = page.layout()
        for section in spec.sections:
            layout.addWidget(QLabel(section.title))
            layout.addWidget(QLabel(" · ".join(section.fields)))
        layout.addWidget(QLabel(spec.driver_status_messages["blocked"]))
        table = QTableWidget(3, len(spec.detail_columns))
        table.setHorizontalHeaderLabels(spec.detail_columns)
        for r, name in enumerate(["CANTERO FLAVIA", "GALEANO", "TRIGOS DEL OESTE"]):
            table.setItem(r, 0, QTableWidgetItem(name))
            table.setItem(r, 2, QTableWidgetItem("Fécula de mandioca"))
            table.setItem(r, 7, QTableWidgetItem("L-2606"))
        layout.addWidget(table)
        actions = QHBoxLayout()
        for action in spec.primary_actions:
            actions.addWidget(QPushButton(action))
        layout.addLayout(actions)
        return page

    def _placeholder_page(self) -> QWidget:
        page = _page("Módulo futuro")
        page.layout().addWidget(QLabel(future_module_message()))
        page.layout().addStretch(1)
        return page


def _page(title: str) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 24, 28, 24)
    heading = QLabel(title)
    heading.setObjectName("heading")
    layout.addWidget(heading)
    return page


def _card(title: str, value: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.addWidget(QLabel(title))
    value_label = QLabel(value)
    value_label.setObjectName("cardValue")
    layout.addWidget(value_label)
    return frame


def _demo_user():
    service = AuthService()
    user = service.authenticate("demo_visual", "demo")
    if user:
        return user
    return service.create_user("demo_visual", "demo", "Administrador")


def _client_rows() -> list[list[str]]:
    return [[client.name, client.cuit, "Activo" if client.active else "Inactivo"] for client in Client.select().limit(20)]


def _product_rows() -> list[list[str]]:
    return [[product.name, product.unit, "Activo" if product.active else "Inactivo"] for product in Product.select().limit(20)]


def _driver_rows() -> list[list[str]]:
    return [
        [driver.name, driver.phone or "", "Disponible" if driver.available else "Ocupado"]
        for driver in Driver.select().limit(20)
    ]


STYLES = """
QWidget { background: #f4f7fb; color: #111827; font-family: Arial; font-size: 14px; }
#topbar { background: #ffffff; border-bottom: 1px solid #e2e8f0; }
#appTitle { font-size: 24px; font-weight: 700; }
#sidebar { background: #f8fafc; border-right: 1px solid #e2e8f0; padding: 8px; }
#statusbar { background: #111827; color: #e5e7eb; }
#heading { font-size: 26px; font-weight: 700; margin-bottom: 12px; }
#card { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; min-height: 88px; }
#cardValue { font-size: 28px; font-weight: 700; }
QPushButton { background: #1d4ed8; color: #ffffff; border: 0; border-radius: 6px; padding: 10px 14px; }
QPushButton:disabled { background: #e2e8f0; color: #64748b; }
QTableWidget { background: #ffffff; gridline-color: #e2e8f0; border: 1px solid #cbd5e1; }
"""
