"""Configuracion de la carpeta central de documentos fiscales (#871)."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.audit_service import AuditService
from app.services.client_fiscal_service import default_docs_dir
from app.services.fiscal_configuration_service import (
    FiscalConfigurationError,
    FiscalConfigurationService,
)
from app.services.permission_service import PermissionService


class FiscalConfigurationPage(QWidget):
    def __init__(self, *, user, current_user: str, parent=None):
        super().__init__(parent)
        self.setObjectName("fiscalConfigurationPage")
        self.user = user
        self.current_user = current_user

        title = QLabel("Documentos fiscales")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Carpeta central donde se guardan los certificados PDF de exclusion de "
            "Rentas e IVA. La comparten todos los puestos y debe estar respaldada."
        )
        subtitle.setWordWrap(True)

        self.status = QLabel()
        self.status.setObjectName("fiscalConfigurationStatus")
        self.status.setWordWrap(True)

        self.path_input = QLineEdit()
        self.path_input.setObjectName("fiscalDocsDirInput")
        self.path_input.setPlaceholderText("D:\\FEMAG\\documentos\\fiscales")
        self.path_input.returnPressed.connect(self._save)

        choose_button = QPushButton("Elegir carpeta...")
        choose_button.setObjectName("fiscalDocsDirChooseButton")
        choose_button.clicked.connect(self._choose)
        self.save_button = QPushButton("Guardar carpeta")
        self.save_button.setObjectName("fiscalDocsDirSaveButton")
        self.save_button.clicked.connect(self._save)
        self.clear_button = QPushButton("Usar carpeta por defecto")
        self.clear_button.setObjectName("fiscalDocsDirClearButton")
        self.clear_button.clicked.connect(self._clear)

        card = QFrame()
        card.setObjectName("fiscalConfigurationCard")
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(self.status)
        card_layout.addWidget(QLabel("Carpeta:"))
        row = QHBoxLayout()
        row.addWidget(self.path_input, 1)
        row.addWidget(choose_button)
        card_layout.addLayout(row)
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        card_layout.addLayout(buttons)

        help_text = QLabel(
            "Los certificados se guardan en subcarpetas por cliente. Use una ruta "
            "absoluta local o de red con permisos de escritura para el usuario de "
            "FEMAG. Si no se configura una carpeta, se usa la carpeta local por "
            "defecto del puesto."
        )
        help_text.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addWidget(card)
        layout.addWidget(help_text)
        layout.addStretch(1)

        self.refresh()

    def _allowed(self) -> bool:
        return PermissionService().has_permission(
            self.user, "Sistema", "configurar", "Parámetros"
        )

    def refresh(self) -> None:
        allowed = self._allowed()
        self.path_input.setEnabled(allowed)
        self.save_button.setEnabled(allowed)
        self.clear_button.setEnabled(allowed)
        if not allowed:
            self.save_button.setToolTip(
                "No tiene permiso para configurar la carpeta fiscal."
            )

        configured = FiscalConfigurationService.docs_dir()
        fallback = default_docs_dir()
        self.path_input.setText(configured)
        if configured:
            self.status.setText(
                f"Carpeta configurada: {configured}. Los certificados nuevos se "
                "guardan ahi."
            )
        else:
            self.status.setText(
                f"Sin carpeta configurada. Se usa la carpeta local por defecto: "
                f"{fallback}."
            )

    def _choose(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Seleccionar carpeta de documentos fiscales"
        )
        if path:
            self.path_input.setText(path)

    def _save(self) -> None:
        if not self._allowed():
            QMessageBox.warning(
                self, "Documentos fiscales", "No tiene permiso para esta accion."
            )
            return
        previous = FiscalConfigurationService.docs_dir()
        try:
            saved = FiscalConfigurationService.save_docs_dir(self.path_input.text())
        except FiscalConfigurationError as exc:
            QMessageBox.warning(self, "Documentos fiscales", str(exc))
            return
        AuditService().record(
            user=self.current_user,
            module="Sistema",
            action="configurar",
            record_ref="documentos fiscales",
            old_value={"docs_dir": previous or None},
            new_value={"docs_dir": saved},
            observation="Carpeta de certificados fiscales configurada.",
        )
        self.refresh()
        QMessageBox.information(
            self,
            "Documentos fiscales",
            "La carpeta se guardo. Los certificados nuevos se guardan ahi.",
        )

    def _clear(self) -> None:
        if not self._allowed():
            QMessageBox.warning(
                self, "Documentos fiscales", "No tiene permiso para esta accion."
            )
            return
        previous = FiscalConfigurationService.docs_dir()
        if not previous:
            self.refresh()
            return
        answer = QMessageBox.question(
            self,
            "Documentos fiscales",
            "Se vuelve a la carpeta local por defecto. Los certificados ya cargados "
            "no se mueven. ¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        FiscalConfigurationService.clear_docs_dir()
        AuditService().record(
            user=self.current_user,
            module="Sistema",
            action="configurar",
            record_ref="documentos fiscales",
            old_value={"docs_dir": previous},
            new_value={"docs_dir": None},
            observation="Se quito la carpeta central de certificados fiscales.",
        )
        self.refresh()
        QMessageBox.information(
            self,
            "Documentos fiscales",
            "Se restablecio la carpeta local por defecto.",
        )


__all__ = ["FiscalConfigurationPage"]
