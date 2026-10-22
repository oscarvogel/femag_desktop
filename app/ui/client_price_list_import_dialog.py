"""Diálogo de importación de la lista de precios desde Excel (#705).

El operador elige el Excel, mira **la vista previa** (qué lista cambia, qué teléfono se
completa, qué conflictos hay) y recién ahí aplica. Nada se escribe antes de la
confirmación, y antes de aplicar se guarda un respaldo del estado actual.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.client_price_list_import_service import (
    ClientPriceListImporter,
    ImportPriceListError,
    VistaPrevia,
)
from app.ui.form_feedback import FormFeedback


class ClientPriceListImportDialog(QDialog):
    """Importa lista de precios y teléfono desde un Excel, con vista previa."""

    def __init__(self, *, current_user: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar lista de precios desde Excel")
        self.setObjectName("clientPriceListImportDialog")
        self.resize(940, 620)
        self.setMinimumSize(760, 480)

        self.current_user = current_user
        self.importer = ClientPriceListImporter(current_user=current_user)
        self.vista_previa: VistaPrevia | None = None

        root = QVBoxLayout(self)

        archivo_row = QHBoxLayout()
        self.archivo_label = QLabel("Ningún archivo seleccionado")
        self.archivo_label.setObjectName("priceListImportFileLabel")
        self.archivo_label.setWordWrap(True)
        self.seleccionar_btn = QPushButton("Seleccionar Excel...")
        self.seleccionar_btn.setObjectName("priceListImportSelectFileButton")
        self.calcular_btn = QPushButton("Calcular")
        self.calcular_btn.setObjectName("priceListImportCalculateButton")
        self.calcular_btn.setEnabled(False)
        archivo_row.addWidget(self.seleccionar_btn)
        archivo_row.addWidget(self.archivo_label, 1)
        archivo_row.addWidget(self.calcular_btn)
        root.addLayout(archivo_row)

        self.resumen_label = QLabel(
            "Elegí el Excel de clientes (el que exporta la app) y presioná Calcular para "
            "ver qué se va a modificar. No se escribe nada hasta que apliques."
        )
        self.resumen_label.setObjectName("priceListImportSummaryLabel")
        self.resumen_label.setWordWrap(True)
        root.addWidget(self.resumen_label)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("priceListImportTabs")
        self.tab_lista = self._crear_tabla("priceListImportListaTable", "Lista a cambiar")
        self.tab_telefono = self._crear_tabla("priceListImportTelefonoTable", "Teléfonos a completar")
        self.tab_conflictos = self._crear_tabla("priceListImportConflictosTable", "Conflictos")
        self.tab_no_encontrados = self._crear_tabla("priceListImportNoEncontradosTable", "No encontrados")
        self.tab_diferencias = self._crear_tabla("priceListImportDiferenciasTable", "Diferencias informadas")
        for widget, etiqueta in (
            (self.tab_lista, "Lista a cambiar"),
            (self.tab_telefono, "Teléfonos"),
            (self.tab_conflictos, "Conflictos"),
            (self.tab_no_encontrados, "No encontrados"),
            (self.tab_diferencias, "Diferencias"),
        ):
            contenedor = QWidget()
            layout = QVBoxLayout(contenedor)
            layout.setContentsMargins(6, 6, 6, 6)
            layout.addWidget(widget)
            self.tabs.addTab(contenedor, etiqueta)
        root.addWidget(self.tabs, 1)

        self.feedback = FormFeedback("priceListImportFeedback")
        root.addWidget(self.feedback)

        acciones = QHBoxLayout()
        acciones.addStretch(1)
        self.cancelar_btn = QPushButton("Cerrar")
        self.cancelar_btn.setObjectName("priceListImportCancelButton")
        self.aplicar_btn = QPushButton("Aplicar")
        self.aplicar_btn.setObjectName("priceListImportApplyButton")
        self.aplicar_btn.setEnabled(False)
        acciones.addWidget(self.cancelar_btn)
        acciones.addWidget(self.aplicar_btn)
        root.addLayout(acciones)

        self.seleccionar_btn.clicked.connect(self._seleccionar_archivo)
        self.calcular_btn.clicked.connect(self._calcular)
        self.aplicar_btn.clicked.connect(self._aplicar)
        self.cancelar_btn.clicked.connect(self.reject)

    # ------------------------------------------------------------------ UI

    @staticmethod
    def _crear_tabla(object_name: str, titulo: str) -> QTableWidget:
        tabla = QTableWidget(0, 4)
        tabla.setObjectName(object_name)
        tabla.setHorizontalHeaderLabels(["Cliente", "CUIT", titulo, "Fila"])
        # El detalle es lo que el operador tiene que leer: no puede quedar cortado.
        encabezado = tabla.horizontalHeader()
        encabezado.setSectionResizeMode(0, QHeaderView.Stretch)
        encabezado.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        encabezado.setSectionResizeMode(2, QHeaderView.Stretch)
        encabezado.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        tabla.verticalHeader().setVisible(False)
        tabla.setSelectionBehavior(QTableWidget.SelectRows)
        tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        return tabla

    @staticmethod
    def _llenar(tabla: QTableWidget, filas: list[tuple]) -> None:
        tabla.setRowCount(len(filas))
        for indice, fila in enumerate(filas):
            for columna, valor in enumerate(fila):
                item = QTableWidgetItem("" if valor is None else str(valor))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                tabla.setItem(indice, columna, item)

    def _seleccionar_archivo(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar Excel de clientes",
            str(Path.home()),
            "Excel (*.xlsx)",
        )
        if not ruta:
            return
        self.archivo_label.setText(ruta)
        self.calcular_btn.setEnabled(True)
        self.aplicar_btn.setEnabled(False)
        self.vista_previa = None
        self.feedback.show_info("Presioná Calcular para ver qué se va a modificar.")

    def _calcular(self) -> None:
        ruta = self.archivo_label.text()
        if not ruta or ruta == "Ningún archivo seleccionado":
            self.feedback.show_warning("Primero elegí el archivo de Excel.")
            return
        try:
            vista = self.importer.construir_vista_previa(ruta)
        except ImportPriceListError as exc:
            self.vista_previa = None
            self.aplicar_btn.setEnabled(False)
            self.feedback.show_error(str(exc))
            return
        except Exception as exc:  # pragma: no cover - red de seguridad
            self.vista_previa = None
            self.aplicar_btn.setEnabled(False)
            self.feedback.show_error(f"No se pudo leer el archivo: {exc}")
            return

        self.vista_previa = vista
        self._llenar(
            self.tab_lista,
            [
                (cambio.nombre, cambio.cuit, f"{cambio.lista_anterior} → {cambio.lista_nueva}", cambio.fila)
                for cambio in vista.cambios_lista
            ],
        )
        self._llenar(
            self.tab_telefono,
            [
                (cambio.nombre, cambio.cuit, cambio.telefono_nuevo, cambio.fila)
                for cambio in vista.cambios_telefono
            ],
        )
        self._llenar(
            self.tab_conflictos,
            [
                (
                    ", ".join(conflicto.nombres),
                    conflicto.cuit,
                    conflicto.detalle,
                    ", ".join(str(f) for f in conflicto.filas),
                )
                for conflicto in vista.conflictos
            ],
        )
        self._llenar(
            self.tab_no_encontrados,
            [
                (fila.nombre, fila.cuit, fila.motivo, fila.fila)
                for fila in vista.no_encontrados + vista.invalidos
            ],
        )
        self._llenar(
            self.tab_diferencias,
            [
                (diferencia.nombre, diferencia.cuit, f"{diferencia.campo}: {diferencia.valor_base} ≠ {diferencia.valor_archivo}", diferencia.fila)
                for diferencia in vista.diferencias
            ],
        )

        resumen = vista.resumen()
        self.resumen_label.setText(
            f"{resumen['filas']} filas · "
            f"{resumen['cambios_lista']} listas a cambiar · "
            f"{resumen['cambios_telefono']} teléfonos a completar · "
            f"{resumen['sin_cambio']} sin cambio · "
            f"{resumen['conflictos']} conflictos · "
            f"{resumen['no_encontrados'] + resumen['invalidos']} filas sin aplicar"
        )
        hay_cambios = bool(vista.cambios)
        self.aplicar_btn.setEnabled(hay_cambios)
        if vista.conflictos:
            self.feedback.show_warning(
                f"{len(vista.conflictos)} conflictos: no se aplican. Revisá la pestaña "
                "Conflictos y corregí el Excel."
            )
        elif hay_cambios:
            self.feedback.show_info("Revisá la vista previa y presioná Aplicar.")
        else:
            self.feedback.show_info("Con este archivo no hay nada que cambiar.")

    def _aplicar(self) -> None:
        if self.vista_previa is None:
            self.feedback.show_warning("Primero calculá la vista previa.")
            return
        resumen = self.vista_previa.resumen()
        confirmacion = QMessageBox.question(
            self,
            "Aplicar importación",
            f"Se van a cambiar {resumen['cambios_lista']} listas de precios y completar "
            f"{resumen['cambios_telefono']} teléfonos.\n\n"
            "Antes se guarda un respaldo del estado actual.\n\n"
            "¿Seguís?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmacion != QMessageBox.Yes:
            return

        resultado = self.importer.aplicar(self.vista_previa)
        if resultado.errores:
            self.feedback.show_error("; ".join(resultado.errores))
            return
        self.feedback.show_success(
            f"Listas actualizadas: {resultado.cambios_lista} · "
            f"Teléfonos completados: {resultado.cambios_telefono}. "
            f"Respaldo: {resultado.respaldo}"
        )
        self.accept()
