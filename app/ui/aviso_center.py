from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QPushButton, QHeaderView
from PyQt5.QtCore import Qt
from app.services.aviso_service import AvisoService


class AvisoCenterPage(QWidget):
    def __init__(self, *, user, on_navigate, parent=None):
        super().__init__(parent)
        self.user = user
        self.on_navigate = on_navigate
        self.service = AvisoService()
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Centro de Avisos"))
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("avisoCenterTable")
        self.table.setHorizontalHeaderLabels(["Prioridad", "Tipo", "Mensaje", "Fecha", "Acción"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.table)
        self.refresh()
        self.table.cellClicked.connect(self._on_click)

    def refresh(self):
        avisos = self.service.get_for_user(self.user)
        self.table.setRowCount(len(avisos))
        for i, av in enumerate(avisos):
            self.table.setItem(i, 0, QTableWidgetItem(av.prioridad))
            self.table.setItem(i, 1, QTableWidgetItem(av.tipo))
            self.table.setItem(i, 2, QTableWidgetItem(f"{av.titulo} - {av.descripcion}"))
            self.table.setItem(i, 3, QTableWidgetItem(av.created_at.strftime("%d/%m")))
            btn = QPushButton("Ver")
            btn.clicked.connect(lambda _, av=av: self._navigate(av))
            self.table.setCellWidget(i, 4, btn)

    def _on_click(self, row, col):
        avisos = self.service.get_for_user(self.user)
        if 0 <= row < len(avisos):
            self._navigate(avisos[row])

    def _navigate(self, aviso):
        self.service.mark_read(self.user, aviso.tipo, aviso.referencia_id)
        self.on_navigate(aviso.route_key)
