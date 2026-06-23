from app.config.database import initialize_runtime_database
from app.models import ALL_MODELS
from app.models.security import User, UserProfile
from app.services.migration_service import MigrationRunner
from app.services.permission_service import PermissionService
from app.ui.menu import MenuItemView, build_sidebar_tree_spec


def run_desktop_app() -> int:
    db = initialize_runtime_database()
    db.connect(reuse_if_open=True)
    db.create_tables(ALL_MODELS, safe=True)
    MigrationRunner(db).run_pending()
    PermissionService().seed_defaults()
    user = _get_session_user()
    return _run_pyqt_app(user)


def _get_session_user() -> User:
    user = User.get_or_none(User.active == True)  # noqa: E712
    if user:
        return user
    profile, _ = UserProfile.get_or_create(name="Administrador")
    return User(username="admin_local", password_hash="", profile=profile)


def _run_pyqt_app(user: User) -> int:
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import (
            QApplication,
            QLabel,
            QMainWindow,
            QMessageBox,
            QSplitter,
            QTreeWidget,
            QTreeWidgetItem,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as exc:
        raise RuntimeError("PyQt5 no esta instalado. Ejecuta scripts\\iniciar_dev.ps1 para instalar dependencias.") from exc

    class FemagWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("FEMAG Desktop")
            self.resize(1100, 720)
            self.tree = QTreeWidget()
            self.tree.setHeaderHidden(True)
            self.tree.itemClicked.connect(self._handle_item_click)
            self.content = QLabel("Seleccione una opcion del menu.")
            self.content.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            self.content.setWordWrap(True)

            content_container = QWidget()
            content_layout = QVBoxLayout(content_container)
            content_layout.addWidget(self.content)

            splitter = QSplitter()
            splitter.addWidget(self.tree)
            splitter.addWidget(content_container)
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            self.setCentralWidget(splitter)
            self._load_menu()

        def _load_menu(self) -> None:
            spec = build_sidebar_tree_spec(user)
            for section in spec.sections:
                section_item = QTreeWidgetItem([section.title])
                section_item.setExpanded(True)
                self.tree.addTopLevelItem(section_item)
                for item in section.items:
                    self._add_menu_item(section_item, item)

        def _add_menu_item(self, parent: QTreeWidgetItem, menu_item: MenuItemView) -> None:
            tree_item = QTreeWidgetItem([menu_item.title])
            tree_item.setData(0, Qt.UserRole, menu_item)
            parent.addChild(tree_item)
            for child in menu_item.children or []:
                self._add_menu_item(tree_item, child)

        def _handle_item_click(self, item: QTreeWidgetItem) -> None:
            menu_item = item.data(0, Qt.UserRole)
            if not menu_item:
                return
            if menu_item.placeholder:
                QMessageBox.information(self, "FEMAG Desktop", "Funcionalidad prevista para una proxima entrega.")
                return
            route = menu_item.route_key or menu_item.action_key or menu_item.title
            self.content.setText(f"{menu_item.title}\n\nModulo: {route}")

    app = QApplication.instance() or QApplication([])
    window = FemagWindow()
    window.show()
    return app.exec_()
