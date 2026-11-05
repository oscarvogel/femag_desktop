"""Pantalla unica de parametros del sistema.

Reune las configuraciones que antes vivian como items separados del menu.
Cada seccion nueva se agrega como un tab mas sin tocar el menu lateral.
"""

from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from app.ui.fiscal_configuration import FiscalConfigurationPage
from app.ui.remittances import RemittanceSeriesPage
from app.ui.webapp_configuration import WebappConfigurationPage
from app.ui.whatsapp_configuration import WhatsAppConfigurationPage


class ParametersPage(QWidget):
    def __init__(self, *, user, current_user: str, parent=None):
        super().__init__(parent)
        self.setObjectName("parametersPage")

        layout = QVBoxLayout(self)
        title = QLabel("Parámetros")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Configuraciones centrales del sistema. Los cambios impactan en todos "
            "los puestos de trabajo."
        )
        subtitle.setWordWrap(True)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("parametersTabs")
        self.pages = [
            RemittanceSeriesPage(current_user=current_user, parent=self),
            WhatsAppConfigurationPage(user=user, current_user=current_user, parent=self),
            WebappConfigurationPage(user=user, current_user=current_user, parent=self),
            FiscalConfigurationPage(user=user, current_user=current_user, parent=self),
        ]
        self.tabs.addTab(self.pages[0], "Numeración")
        self.tabs.addTab(self.pages[1], "WhatsApp")
        self.tabs.addTab(self.pages[2], "Servidor web")
        self.tabs.addTab(self.pages[3], "Documentos fiscales")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(self.tabs, 1)

    def refresh(self) -> None:
        for page in self.pages:
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()


__all__ = ["ParametersPage"]
