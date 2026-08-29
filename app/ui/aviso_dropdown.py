from PyQt5.QtWidgets import QFrame, QVBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem
from PyQt5.QtCore import Qt
from app.services.aviso_service import AvisoService


class AvisoDropdown(QFrame):
    def __init__(self, *, user, on_navigate, parent=None):
        super().__init__(parent)
        self.setObjectName("avisoDropdown")
        self.user = user
        self.on_navigate = on_navigate
        self.service = AvisoService()
        self.setWindowFlags(Qt.Popup)
        layout = QVBoxLayout(self)
        self.title = QLabel("Avisos")
        self.title.setObjectName("avisoDropdownTitle")
        layout.addWidget(self.title)
        self.list = QListWidget()
        self.list.setObjectName("avisoList")
        layout.addWidget(self.list)
        self.mark_all = QPushButton("Marcar todo leído")
        self.mark_all.setObjectName("avisoMarkAllButton")
        self.view_all = QPushButton("Ver todos")
        self.view_all.setObjectName("avisoViewAllButton")
        layout.addWidget(self.mark_all)
        layout.addWidget(self.view_all)
        self.list.itemClicked.connect(self._on_click)
        self.mark_all.clicked.connect(self._mark_all)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for aviso in self.service.get_for_user(self.user):
            item = QListWidgetItem(f"[{aviso.prioridad}] {aviso.titulo}: {aviso.descripcion}")
            item.setData(Qt.UserRole, aviso)
            self.list.addItem(item)
        if self.list.count() == 0:
            self.list.addItem("Sin avisos")

    def _on_click(self, item):
        aviso = item.data(Qt.UserRole)
        if aviso and hasattr(aviso, "route_key"):
            self.service.mark_read(self.user, aviso.tipo, aviso.referencia_id)
            self.on_navigate(aviso.route_key)
            self.hide()

    def _mark_all(self):
        self.service.mark_all_read(self.user)
        self.refresh()
