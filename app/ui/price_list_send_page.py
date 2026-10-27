"""Pantalla "Envío de lista de precios" por WhatsApp (#705, Fase B, etapa 3).

Es la pantalla del spec §4.2, con los cuatro pasos:

1. **Preparar**: elegir la lista, cargar **su** PDF y **su** mensaje, el intervalo y el lote inicial.
2. **Calcular destinatarios**: contra la base real, con los contadores y una fila por cliente.
3. **Enviar**: con confirmación explícita de la cantidad de mensajes.
4. **Seguimiento**: tabla en vivo, progreso, ETA, pausa, cancelación, reintento de fallidos y
   export del log en CSV.

El envío **no bloquea la interfaz**: la cola corre en un ``QRunnable`` sobre el ``QThreadPool`` y la
pantalla se actualiza por señales. El operador puede seguir trabajando mientras se manda.

Antes de mandar, la pantalla muestra **siempre** el PDF que se va a enviar y el número exacto de
cada destinatario, y sólo van marcados los celulares sin ambigüedad: un número "posible" (un local
de 10 u 11 dígitos puede ser una línea fija o un móvil escrito sin el "15") se manda solo si el
operador lo tilda a mano.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.price_list_campaign_service import (
    LISTAS_VALIDAS,
    PriceListCampaignService,
)
from app.services.price_list_send_service import (
    INTERVALO_MAXIMO,
    INTERVALO_MINIMO,
    Pendiente,
    PriceListCampaignRunner,
    clave_campana,
    destinatarios_pendientes,
)
from app.services.whatsapp_api_client import WhatsAppApiError
from app.services.whatsapp_envio_service import WhatsAppEnvioService
from app.ui.form_feedback import FormFeedback

ESTADO_ENVIADO = "enviado"
ESTADO_FALLIDO = "falló"
ESTADO_OMITIDO = "omitido"
ESTADO_EN_COLA = "en cola"

ETIQUETA_ESTADO = {
    ESTADO_EN_COLA: "en cola",
    ESTADO_ENVIADO: "enviado",
    ESTADO_FALLIDO: "falló",
    ESTADO_OMITIDO: "omitido",
}


def texto_confirmacion_envio(seleccionados: int, disponibles: int) -> str:
    """El texto obligatorio del modal previo al envío (#793).

    Se separa de la pantalla para poder testear el texto exacto sin abrir un diálogo modal.
    """
    cantidad = int(seleccionados)
    total = int(disponibles)
    if cantidad == 1:
        destino = "1 cliente"
        seleccionado = "seleccionado"
        determinante = "este cliente"
    else:
        destino = f"{cantidad} clientes"
        seleccionado = "seleccionados"
        determinante = f"estos {cantidad} clientes"
    return (
        f"Estás por enviar la lista de precios a {destino} {seleccionado} "
        f"de {total} disponibles.\n\n"
        f"¿Confirmás el envío únicamente a {determinante}?"
    )


class PriceListSendSignals(QObject):
    """Señales del worker: la pantalla se actualiza desde el hilo."""

    evento = pyqtSignal(object)
    terminado = pyqtSignal(object)
    error = pyqtSignal(str)


class PriceListSendWorker(QRunnable):
    """Corre la cola de envíos en un hilo aparte."""

    def __init__(self, runner: PriceListCampaignRunner):
        super().__init__()
        self.runner = runner
        self.signals = PriceListSendSignals()
        self.runner.al_evento = self.signals.evento.emit

    def run(self) -> None:  # pragma: no cover - corre en otro hilo
        try:
            self.signals.terminado.emit(self.runner.run())
        except Exception as exc:  # noqa: BLE001 - va a la pantalla
            self.signals.error.emit(str(exc))


class PriceListSendPage(QWidget):
    """La pantalla del envío de la lista de precios."""

    def __init__(self, *, user=None, current_user: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("priceListSendPage")
        self.user = user
        self.current_user = current_user
        self.servicio = PriceListCampaignService
        self._envios = None
        self._envios_error = ""
        self.worker: PriceListSendWorker | None = None
        self.destinatarios = []
        self.destinatarios_por_id: dict[int, object] = {}
        self.destinatarios_visibles = []
        self.seleccionados: set[int] = set()
        self.pendientes = []
        self.pendientes_restantes = []
        self.fallidos = []
        self.estado_filas: dict[int, dict] = {}
        self.clave_campana_actual = ""
        self._pintando_tabla = False
        self._iniciando = False
        self._suprimir_invalidacion_pdf = False
        self._pdf_anterior = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        titulo = QLabel("Envío de lista de precios")
        titulo.setObjectName("heading")
        root.addWidget(titulo)

        self.subtitulo = QLabel("Elegí la lista, cargá su PDF y mandala a los clientes de esa lista.")
        self.subtitulo.setObjectName("subheading")
        root.addWidget(self.subtitulo)

        self.feedback = FormFeedback("priceListSendFeedback")
        root.addWidget(self.feedback)

        root.addWidget(self._bloque_preparar())
        root.addWidget(self._bloque_destinatarios())
        root.addWidget(self._bloque_enviar())
        root.addWidget(self._bloque_seguimiento())

        self._cargar_configuracion()

    # ------------------------------------------------------------- construccion

    def _bloque_preparar(self) -> QGroupBox:
        grupo = QGroupBox("1. Preparar")
        grupo.setObjectName("priceListSendPrepareGroup")
        layout = QVBoxLayout(grupo)

        form = QFormLayout()
        self.lista_combo = QComboBox()
        self.lista_combo.setObjectName("priceListSendListCombo")
        for lista in LISTAS_VALIDAS:
            self.lista_combo.addItem(f"Lista {lista}", lista)
        self.lista_combo.currentIndexChanged.connect(self._al_cambiar_lista)
        form.addRow("Lista de precios", self.lista_combo)

        self.pdf_input = QLineEdit()
        self.pdf_input.setObjectName("priceListSendPdfInput")
        self.pdf_input.setReadOnly(True)
        self.pdf_input.setPlaceholderText("Elegí el PDF de esta lista")
        self.pdf_input.textChanged.connect(self._al_cambiar_pdf)
        self.elegir_pdf_button = QPushButton("Seleccionar PDF")
        self.elegir_pdf_button.setObjectName("priceListSendPickPdfButton")
        self.elegir_pdf_button.clicked.connect(self._elegir_pdf)
        fila_pdf = QHBoxLayout()
        fila_pdf.addWidget(self.pdf_input, 1)
        fila_pdf.addWidget(self.elegir_pdf_button)
        contenedor_pdf = QWidget()
        contenedor_pdf.setLayout(fila_pdf)
        form.addRow("PDF", contenedor_pdf)

        self.mensaje_input = QTextEdit()
        self.mensaje_input.setObjectName("priceListSendMessageInput")
        self.mensaje_input.setMaximumHeight(90)
        self.mensaje_input.setPlaceholderText(
            "Hola {cliente}, adjuntamos la lista de precios {lista} de {empresa}. Quedamos a disposición."
        )
        form.addRow("Mensaje", self.mensaje_input)

        self.intervalo_spin = QSpinBox()
        self.intervalo_spin.setObjectName("priceListSendIntervalSpin")
        # El mínimo normal es 60 s; por debajo está el "modo prueba" de 10 s, que la pantalla
        # avisa en pantalla para que nadie mande la campaña entera a esa velocidad sin querer.
        self.intervalo_spin.setRange(10, int(INTERVALO_MAXIMO))
        self.intervalo_spin.setValue(180)
        self.intervalo_spin.setSuffix(" s")
        self.intervalo_spin.valueChanged.connect(self._al_cambiar_el_intervalo)
        self.modo_prueba_button = QPushButton("Usar 10 s (modo prueba)")
        self.modo_prueba_button.setObjectName("priceListSendTestSpeedButton")
        self.modo_prueba_button.clicked.connect(self._usar_velocidad_de_prueba)
        fila_intervalo = QHBoxLayout()
        fila_intervalo.addWidget(self.intervalo_spin)
        fila_intervalo.addWidget(self.modo_prueba_button)
        contenedor_intervalo = QWidget()
        contenedor_intervalo.setLayout(fila_intervalo)
        form.addRow("Intervalo entre envíos", contenedor_intervalo)

        self.lote_spin = QSpinBox()
        self.lote_spin.setObjectName("priceListSendBatchSpin")
        self.lote_spin.setRange(0, 500)
        self.lote_spin.setValue(20)
        form.addRow("Lote inicial", self.lote_spin)

        layout.addLayout(form)

        acciones = QHBoxLayout()
        self.guardar_button = QPushButton("Guardar configuración")
        self.guardar_button.setObjectName("priceListSendSaveConfigButton")
        self.guardar_button.clicked.connect(self._guardar_configuracion)
        acciones.addWidget(self.guardar_button)
        acciones.addStretch(1)
        layout.addLayout(acciones)
        return grupo

    def _bloque_destinatarios(self) -> QGroupBox:
        grupo = QGroupBox("2. Destinatarios")
        grupo.setObjectName("priceListSendRecipientsGroup")
        layout = QVBoxLayout(grupo)

        acciones = QHBoxLayout()
        self.calcular_button = QPushButton("Calcular destinatarios")
        self.calcular_button.setObjectName("priceListSendCalculateButton")
        self.calcular_button.clicked.connect(self._calcular_destinatarios)
        acciones.addWidget(self.calcular_button)
        self.contadores_label = QLabel("Todavía no calculaste los destinatarios.")
        self.contadores_label.setObjectName("priceListSendCountersLabel")
        acciones.addWidget(self.contadores_label, 1)
        layout.addLayout(acciones)

        filtros = QHBoxLayout()
        self.busqueda_input = QLineEdit()
        self.busqueda_input.setObjectName("priceListSendSearchInput")
        self.busqueda_input.setPlaceholderText(
            "Buscar por nombre, teléfono registrado o número de WhatsApp..."
        )
        self.busqueda_input.setClearButtonEnabled(True)
        self.busqueda_input.textChanged.connect(self._al_buscar)
        filtros.addWidget(self.busqueda_input, 1)
        self.seleccionar_todos_button = QPushButton("Seleccionar todos")
        self.seleccionar_todos_button.setObjectName("priceListSendSelectAllButton")
        self.seleccionar_todos_button.clicked.connect(self._seleccionar_todos)
        filtros.addWidget(self.seleccionar_todos_button)
        self.deseleccionar_todos_button = QPushButton("Deseleccionar todos")
        self.deseleccionar_todos_button.setObjectName("priceListSendDeselectAllButton")
        self.deseleccionar_todos_button.clicked.connect(self._deseleccionar_todos)
        filtros.addWidget(self.deseleccionar_todos_button)
        layout.addLayout(filtros)

        self.alcance_label = QLabel(
            "Seleccionar todos incluye solo a los clientes con un número válido para WhatsApp."
        )
        self.alcance_label.setObjectName("priceListSendScopeHint")
        self.alcance_label.setWordWrap(True)
        layout.addWidget(self.alcance_label)

        self.destinatarios_table = QTableWidget(0, 5)
        self.destinatarios_table.setObjectName("priceListSendRecipientsTable")
        self.destinatarios_table.setHorizontalHeaderLabels(
            ["Enviar", "Cliente", "Teléfono en la base", "Número a enviar", "Estado"]
        )
        self.destinatarios_table.verticalHeader().setVisible(False)
        self.destinatarios_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.destinatarios_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.destinatarios_table.itemChanged.connect(self._al_cambiar_un_destinatario)
        header = self.destinatarios_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for columna in (2, 3, 4):
            header.setSectionResizeMode(columna, QHeaderView.ResizeToContents)
        layout.addWidget(self.destinatarios_table)
        self._actualizar_controles_seleccion()
        return grupo

    def _bloque_enviar(self) -> QGroupBox:
        grupo = QGroupBox("3. Enviar")
        grupo.setObjectName("priceListSendStartGroup")
        layout = QVBoxLayout(grupo)

        self.aviso_texto = QLabel("")
        self.aviso_texto.setObjectName("priceListSendWarningLabel")
        self.aviso_texto.setWordWrap(True)
        layout.addWidget(self.aviso_texto)

        self.confirmacion_check = QCheckBox("Entiendo que sale desde mi línea de WhatsApp.")
        self.confirmacion_check.setObjectName("priceListSendConfirmCheck")
        self.confirmacion_check.toggled.connect(self._refrescar_boton_enviar)
        layout.addWidget(self.confirmacion_check)

        self.enviar_button = QPushButton("Iniciar envío")
        self.enviar_button.setObjectName("priceListSendStartButton")
        self.enviar_button.setEnabled(False)
        self.enviar_button.clicked.connect(self._iniciar_envio)
        layout.addWidget(self.enviar_button)
        return grupo

    def _bloque_seguimiento(self) -> QGroupBox:
        grupo = QGroupBox("4. Seguimiento")
        grupo.setObjectName("priceListSendProgressGroup")
        layout = QVBoxLayout(grupo)

        self.seguimiento_table = QTableWidget(0, 5)
        self.seguimiento_table.setObjectName("priceListSendProgressTable")
        self.seguimiento_table.setHorizontalHeaderLabels(
            ["Cliente", "Número", "Estado", "Detalle", "Hora"]
        )
        self.seguimiento_table.verticalHeader().setVisible(False)
        self.seguimiento_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.seguimiento_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for columna in (1, 2, 3, 4):
            header.setSectionResizeMode(columna, QHeaderView.ResizeToContents)
        layout.addWidget(self.seguimiento_table)

        self.progreso = QProgressBar()
        self.progreso.setObjectName("priceListSendProgressBar")
        self.progreso.setRange(0, 100)
        layout.addWidget(self.progreso)

        self.resumen_label = QLabel("Sin envíos.")
        self.resumen_label.setObjectName("priceListSendSummaryLabel")
        layout.addWidget(self.resumen_label)

        acciones = QHBoxLayout()
        self.pausar_button = QPushButton("Pausar")
        self.pausar_button.setObjectName("priceListSendPauseButton")
        self.pausar_button.setEnabled(False)
        self.pausar_button.clicked.connect(self._pausar)
        self.cancelar_button = QPushButton("Cancelar")
        self.cancelar_button.setObjectName("priceListSendCancelButton")
        self.cancelar_button.setEnabled(False)
        self.cancelar_button.clicked.connect(self._cancelar)
        self.reintentar_button = QPushButton("Reintentar fallidos")
        self.reintentar_button.setObjectName("priceListSendRetryButton")
        self.reintentar_button.setEnabled(False)
        self.reintentar_button.clicked.connect(self._reintentar_fallidos)
        self.exportar_button = QPushButton("Exportar log (CSV)")
        self.exportar_button.setObjectName("priceListSendExportButton")
        self.exportar_button.setEnabled(False)
        self.exportar_button.clicked.connect(self._exportar_csv)
        for boton in (
            self.pausar_button,
            self.cancelar_button,
            self.reintentar_button,
            self.exportar_button,
        ):
            acciones.addWidget(boton)
        acciones.addStretch(1)
        layout.addLayout(acciones)
        return grupo

    # ------------------------------------------------------------ configuracion

    def _cargar_configuracion(self) -> None:
        config = self.servicio.config(self.lista_combo.currentData())
        self._suprimir_invalidacion_pdf = True
        try:
            self.pdf_input.setText(config.pdf_path)
        finally:
            self._suprimir_invalidacion_pdf = False
        self._pdf_anterior = self.pdf_input.text().strip()
        self.mensaje_input.setPlainText(config.mensaje)

    def _limpiar_cola_pendiente(self) -> None:
        """Descarta restos de una campaña anterior (fallidos o lote pendiente)."""
        self.pendientes_restantes = []
        self.fallidos = []
        boton = getattr(self, "reintentar_button", None)
        if boton is not None:
            boton.setText("Reintentar fallidos")
            boton.setEnabled(False)

    def _al_cambiar_lista(self) -> None:
        tenia_seleccion = bool(self.seleccionados)
        self._cargar_configuracion()
        self.destinatarios = []
        self.destinatarios_por_id = {}
        self.destinatarios_visibles = []
        self.seleccionados = set()
        self._limpiar_cola_pendiente()
        self.destinatarios_table.setRowCount(0)
        if tenia_seleccion:
            self.feedback.show_warning(
                "Cambiaste la lista: se descartó la selección anterior. "
                "Volvé a calcular los destinatarios."
            )
        self._refrescar_contadores()
        self._refrescar_boton_enviar()

    def _al_cambiar_pdf(self) -> None:
        """Invalidar la selección si el operador cambia el PDF (#793).

        La selección pertenece a una lista y a un documento concretos. Mandar el PDF nuevo a
        una selección vieja sería un error silencioso, así que se descarta y se pide revisar.
        """
        texto = self.pdf_input.text().strip()
        if texto == self._pdf_anterior:
            return
        self._pdf_anterior = texto
        if self._suprimir_invalidacion_pdf:
            return
        habia_cola = bool(self.pendientes_restantes or self.fallidos)
        if habia_cola:
            self._limpiar_cola_pendiente()
        if not self.seleccionados:
            if habia_cola:
                self.feedback.show_warning(
                    "Cambiaste el PDF: se descartaron los envíos pendientes de reintento."
                )
            return
        self.seleccionados.clear()
        self._pintar_tabla_destinatarios()
        self.feedback.show_warning(
            "Cambiaste el PDF: se descartó la selección anterior. "
            "Revisá los destinatarios y volvé a seleccionar."
        )

    def _elegir_pdf(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Elegí el PDF de la lista de precios",
            "",
            "Documentos PDF (*.pdf)",
        )
        if not ruta:
            return
        tenia_seleccion = bool(self.seleccionados)
        self.pdf_input.setText(ruta)
        if tenia_seleccion:
            return
        self.feedback.show_info(f"Elegiste {Path(ruta).name}. Guardá la configuración para dejarlo asociado.")

    def _usar_velocidad_de_prueba(self) -> None:
        self.intervalo_spin.setValue(10)
        self.feedback.show_info(
            "Intervalo de 10 segundos entre mensajes (no limita la cantidad de destinatarios). "
            "Sirve para pruebas controladas, no para una campaña real."
        )

    def _al_cambiar_el_intervalo(self) -> None:
        if self.intervalo_spin.value() < INTERVALO_MINIMO:
            self.feedback.show_warning(
                "Intervalo de 10 segundos entre mensajes: es el modo prueba. "
                "No cambia a quién se le envía: la audiencia son los clientes seleccionados."
            )
        self._refrescar_contadores()

    def _guardar_configuracion(self) -> None:
        lista = self.lista_combo.currentData()
        try:
            config = self.servicio.guardar(
                lista,
                pdf_path=self.pdf_input.text().strip(),
                mensaje=self.mensaje_input.toPlainText().strip(),
            )
        except Exception as exc:  # noqa: BLE001 - va a la pantalla
            self.feedback.show_warning(str(exc))
            return
        self._suprimir_invalidacion_pdf = True
        try:
            self.pdf_input.setText(config.pdf_path)
        finally:
            self._suprimir_invalidacion_pdf = False
        self._pdf_anterior = self.pdf_input.text().strip()
        self.feedback.show_info(
            f"Guardado: PDF {Path(config.pdf_path).name if config.pdf_path else 'sin definir'}"
            f" para la lista {config.lista}."
        )
        self._refrescar_boton_enviar()

    # ------------------------------------------------------------- destinatarios

    def _calcular_destinatarios(self) -> None:
        lista = self.lista_combo.currentData()
        try:
            audiencia = self.servicio.calcular_audiencia(lista)
        except Exception as exc:  # noqa: BLE001 - va a la pantalla
            self.feedback.show_warning(str(exc))
            return

        self.destinatarios = list(audiencia.destinatarios)
        self.destinatarios_por_id = {d.client_id: d for d in self.destinatarios}
        self._limpiar_cola_pendiente()
        # Recalcular invalida la selección anterior: se vuelve a la selección sugerida
        # (solo celulares sin ambigüedad), nunca a un conjunto viejo.
        self.seleccionados = {
            d.client_id for d in self.destinatarios if d.marcado and d.enviable
        }
        self._pintar_tabla_destinatarios()
        self._refrescar_boton_enviar()

    def _texto_busqueda(self) -> str:
        return self.busqueda_input.text().strip().casefold()

    @staticmethod
    def _coincide_busqueda(destinatario, texto: str) -> bool:
        if not texto:
            return True
        campos = (
            destinatario.nombre,
            destinatario.telefono_original,
            destinatario.telefono_normalizado,
        )
        if any(texto in str(campo or "").casefold() for campo in campos):
            return True
        digitos_buscados = re.sub(r"\D", "", texto)
        if not digitos_buscados:
            return False
        digitos_destino = re.sub(r"\D", "", " ".join(str(campo or "") for campo in campos))
        return digitos_buscados in digitos_destino

    def _pintar_tabla_destinatarios(self) -> None:
        """Repinta la tabla aplicando el filtro, sin tocar la selección real.

        La fuente de verdad es ``self.seleccionados`` (IDs de cliente), no las filas visibles:
        así buscar no borra lo que ya estaba marcado.
        """
        texto = self._texto_busqueda()
        self.destinatarios_visibles = [
            destinatario
            for destinatario in self.destinatarios
            if self._coincide_busqueda(destinatario, texto)
        ]

        self._pintando_tabla = True
        try:
            self.destinatarios_table.setRowCount(len(self.destinatarios_visibles))
            for fila, destinatario in enumerate(self.destinatarios_visibles):
                item_marca = QTableWidgetItem("")
                if destinatario.enviable:
                    item_marca.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    item_marca.setCheckState(
                        Qt.Checked
                        if destinatario.client_id in self.seleccionados
                        else Qt.Unchecked
                    )
                else:
                    item_marca.setFlags(Qt.ItemIsEnabled)
                    item_marca.setCheckState(Qt.Unchecked)
                item_marca.setData(Qt.UserRole, destinatario.client_id)
                self.destinatarios_table.setItem(fila, 0, item_marca)
                self.destinatarios_table.setItem(fila, 1, QTableWidgetItem(destinatario.nombre))
                self.destinatarios_table.setItem(
                    fila, 2, QTableWidgetItem(destinatario.telefono_original)
                )
                self.destinatarios_table.setItem(
                    fila, 3, QTableWidgetItem(destinatario.telefono_normalizado)
                )
                detalle = destinatario.estado
                if destinatario.motivo:
                    detalle = f"{destinatario.estado} ({destinatario.motivo})"
                self.destinatarios_table.setItem(fila, 4, QTableWidgetItem(detalle))
        finally:
            self._pintando_tabla = False

        self._actualizar_etiquetas_alcance()
        self._refrescar_contadores()
        self._refrescar_boton_enviar()

    def _actualizar_etiquetas_alcance(self) -> None:
        if self._texto_busqueda():
            visibles = len(self.destinatarios_visibles)
            self.seleccionar_todos_button.setText(f"Seleccionar visibles ({visibles})")
            self.deseleccionar_todos_button.setText("Deseleccionar visibles")
            self.alcance_label.setText(
                "Hay un filtro activo: los botones de selección actúan solo sobre los "
                "resultados visibles. La selección anterior se conserva."
            )
        else:
            self.seleccionar_todos_button.setText("Seleccionar todos")
            self.deseleccionar_todos_button.setText("Deseleccionar todos")
            self.alcance_label.setText(
                "Seleccionar todos incluye solo a los clientes con un número válido para WhatsApp."
            )

    def _al_buscar(self) -> None:
        self._pintar_tabla_destinatarios()

    def _seleccionar_todos(self) -> None:
        if self.worker is not None:
            return
        for destinatario in self.destinatarios_visibles:
            if destinatario.enviable:
                self.seleccionados.add(destinatario.client_id)
        self._pintar_tabla_destinatarios()

    def _deseleccionar_todos(self) -> None:
        if self.worker is not None:
            return
        for destinatario in self.destinatarios_visibles:
            self.seleccionados.discard(destinatario.client_id)
        self._pintar_tabla_destinatarios()

    def _actualizar_controles_seleccion(self) -> None:
        activo = self.worker is None
        hay = bool(self.destinatarios)
        self.seleccionar_todos_button.setEnabled(activo and hay)
        self.deseleccionar_todos_button.setEnabled(activo and hay)

    def _al_cambiar_un_destinatario(self, item: QTableWidgetItem) -> None:
        if self._pintando_tabla or item.column() != 0 or self.worker is not None:
            return
        client_id = item.data(Qt.UserRole)
        destinatario = self.destinatarios_por_id.get(client_id)
        if destinatario is None or not destinatario.enviable:
            item.setCheckState(Qt.Unchecked)
            self.feedback.show_warning(
                "Ese cliente no tiene un número válido para WhatsApp: no se puede seleccionar."
            )
            return
        if item.checkState() == Qt.Checked:
            self.seleccionados.add(client_id)
        else:
            self.seleccionados.discard(client_id)
        self._refrescar_contadores()
        self._refrescar_boton_enviar()

    def _refrescar_contadores(self) -> None:
        totales = len(self.destinatarios)
        marcados = sum(
            1 for client_id in self.seleccionados if client_id in self.destinatarios_por_id
        )
        if not totales:
            self.contadores_label.setText("Todavía no calculaste los destinatarios.")
            self.aviso_texto.setText(
                "Primero calculá los destinatarios y elegí a qué clientes querés enviarles la lista."
            )
            self._actualizar_controles_seleccion()
            return

        contador = f"{marcados} seleccionados de {totales} disponibles"
        if self._texto_busqueda():
            contador += f" · {len(self.destinatarios_visibles)} visibles"
        self.contadores_label.setText(contador)

        if not marcados:
            self.aviso_texto.setText(
                "No hay clientes seleccionados. Marcá al menos uno para habilitar el envío."
            )
        else:
            self.aviso_texto.setText(
                f"Se van a mandar {marcados} mensajes desde tu instancia de WhatsApp. "
                "Revisá el PDF, la línea y los números antes de confirmar."
            )
        self._actualizar_controles_seleccion()

    def _refrescar_boton_enviar(self) -> None:
        if self.worker is not None:
            pausado = bool(getattr(self.worker.runner, "pausado", False))
            self.enviar_button.setText("Reanudar envío" if pausado else "Iniciar envío")
            self.enviar_button.setEnabled(pausado)
            return
        puede = (
            self.confirmacion_check.isChecked()
            and bool(self.seleccionados)
            and self.pdf_input.text().strip()
            and not self._iniciando
        )
        self.enviar_button.setText("Iniciar envío")
        self.enviar_button.setEnabled(bool(puede))

    # ------------------------------------------------------------------ envio

    @property
    def envios(self):
        """El servicio de envíos, o ``None`` si el WhatsApp está deshabilitado.

        El cliente del gateway lanza si la instalación no tiene el envío habilitado: eso no
        puede romper la pantalla (que también sirve para preparar la campaña y ver quién va a
        recibirla), así que se avisa recién cuando se intenta mandar.
        """
        if self._envios is None and not self._envios_error:
            try:
                self._envios = WhatsAppEnvioService()
            except Exception as exc:  # noqa: BLE001 - va a la pantalla
                self._envios_error = str(exc)
        return self._envios

    def _destinatarios_seleccionados(self):
        """Los destinatarios marcados, tomados de los IDs reales y no de las filas visibles.

        Recorre la audiencia calculada (no la tabla filtrada) para que un cliente seleccionado
        que quedó oculto por la búsqueda siga entrando en la cola. Deduplica por ``client_id``.
        """
        pendientes = []
        vistos: set[int] = set()
        for destinatario in self.destinatarios:
            if destinatario.client_id not in self.seleccionados:
                continue
            if destinatario.client_id in vistos or not destinatario.enviable:
                continue
            vistos.add(destinatario.client_id)
            pendientes.append(destinatario)
        return pendientes

    def _validar_destinatarios_antes_de_enviar(self, pendientes):
        """Revalida los seleccionados contra la base y devuelve (destinatarios, disponibles).

        Si la lista cambió (alta/baja, teléfono distinto, cliente inactivo), no se envía nada:
        se pide recalcular para que una selección vieja no mande mensajes a quien no corresponde.
        """
        lista = self.lista_combo.currentData()
        try:
            audiencia = self.servicio.calcular_audiencia(lista)
        except Exception as exc:  # noqa: BLE001 - va a la pantalla
            self.feedback.show_warning(str(exc))
            return None, 0

        actuales = {d.client_id: d for d in audiencia.destinatarios}
        if set(actuales) != set(self.destinatarios_por_id):
            self.feedback.show_warning(
                "Los destinatarios de la lista cambiaron desde que los calculaste. "
                "Volvé a calcularlos y revisá la selección antes de enviar."
            )
            return None, 0

        validados = []
        rechazados = []
        for pendiente in pendientes:
            actual = actuales.get(pendiente.client_id)
            if (
                actual is None
                or not actual.enviable
                or actual.telefono_normalizado != pendiente.telefono_normalizado
            ):
                rechazados.append(pendiente)
                continue
            validados.append(actual)

        if rechazados:
            self.feedback.show_warning(
                "Alguno de los clientes seleccionados ya no tiene un número válido para WhatsApp "
                "o cambió su teléfono. Recalculá los destinatarios y volvé a seleccionar."
            )
            return None, 0

        return validados, audiencia.total

    def _reiniciar_seguimiento(self) -> None:
        """Una campaña nueva no debe mezclar el seguimiento de una anterior."""
        self.estado_filas = {}
        self.fallidos = []
        self.pendientes_restantes = []
        self.reintentar_button.setText("Reintentar fallidos")
        self.reintentar_button.setEnabled(False)
        self.resumen_label.setText("Sin envíos.")
        self._pintar_seguimiento()

    def _pedir_confirmacion_envio(self, seleccionados: int, disponibles: int) -> bool:
        """Modal obligatorio con las cantidades reales (#793)."""
        caja = QMessageBox(self)
        caja.setObjectName("priceListSendConfirmationDialog")
        caja.setWindowTitle("Confirmar el envío")
        caja.setIcon(QMessageBox.Warning)
        caja.setText(texto_confirmacion_envio(seleccionados, disponibles))
        boton_cancelar = caja.addButton("Cancelar", QMessageBox.RejectRole)
        boton_confirmar = caja.addButton("Confirmar envío", QMessageBox.AcceptRole)
        caja.setDefaultButton(boton_cancelar)
        caja.exec_()
        return caja.clickedButton() is boton_confirmar

    def _iniciar_envio(self) -> None:
        if self.worker is not None:
            if self.worker.runner.pausado:
                self.worker.runner.reanudar()
                self.pausar_button.setEnabled(True)
                self._refrescar_boton_enviar()
            return
        if self._iniciando:
            return

        pendientes = self._destinatarios_seleccionados()
        if not pendientes:
            self.feedback.show_warning(
                "No hay clientes seleccionados. Marcá al menos uno para iniciar el envío."
            )
            return
        if not self.pdf_input.text().strip():
            self.feedback.show_warning("Elegí el PDF de la lista de precios.")
            return
        try:
            self.servicio.validar_pdf(self.pdf_input.text())
        except Exception as exc:  # noqa: BLE001 - va a la pantalla
            self.feedback.show_warning(str(exc))
            return
        if not self.confirmacion_check.isChecked():
            self.feedback.show_warning("Tildá la confirmación para enviar desde tu línea.")
            return

        self._iniciando = True
        try:
            instancia = self._resolver_instancia()
            if not instancia:
                return

            validados, disponibles = self._validar_destinatarios_antes_de_enviar(pendientes)
            if validados is None:
                return

            if not self._pedir_confirmacion_envio(len(validados), disponibles):
                # Cancelar no crea tareas ni modifica la campaña.
                return

            self.pendientes = validados
            self._reiniciar_seguimiento()
            self._iniciar_worker(validados, lote_inicial=self.lote_spin.value())
        finally:
            self._iniciando = False
            self._refrescar_boton_enviar()

    def _resolver_instancia(self) -> str:
        envios = self.envios
        if envios is None:
            self.feedback.show_warning(
                f"{self._envios_error} El envío por WhatsApp no está habilitado en esta instalación."
            )
            return ""
        try:
            return envios.resolve_instance_for_user(self.user)
        except Exception as exc:  # noqa: BLE001 - va a la pantalla
            self.feedback.show_warning(
                f"{exc} No se puede iniciar el envío sin una instancia de WhatsApp."
            )
            return ""

    def _iniciar_worker(self, pendientes, *, lote_inicial: int, excluir_enviados: bool = True) -> None:
        config = self.servicio.config(self.lista_combo.currentData())
        clave = clave_campana(config.lista, self.pdf_input.text().strip())
        self.clave_campana_actual = clave
        if excluir_enviados:
            # Reanudar no vuelve a mandar a quien ya tiene un envio terminal en la campaña.
            pendientes = destinatarios_pendientes(clave, pendientes)

        # Defensa final: la cola nunca puede tener dos veces al mismo cliente.
        unicos = []
        vistos: set[int] = set()
        for pendiente in pendientes:
            if pendiente.client_id in vistos:
                continue
            vistos.add(pendiente.client_id)
            unicos.append(pendiente)
        pendientes = unicos
        self.pendientes = list(pendientes)

        # El motor espera ``Pendiente`` (número efectivo + mensaje ya sustituido); la pantalla
        # trabaja con ``Destinatario``. La conversión ocurre acá, después de la idempotencia.
        a_enviar = [
            Pendiente(
                client_id=destinatario.client_id,
                nombre=destinatario.nombre,
                telefono=destinatario.telefono_normalizado,
                caption=config.mensaje_para(destinatario.nombre),
            )
            for destinatario in pendientes
        ]

        runner = PriceListCampaignRunner(
            clave=clave,
            pdf_path=self.pdf_input.text().strip(),
            pendientes=a_enviar,
            usuario=self.user,
            envios=self.envios,
            instance_id=self._resolver_instancia(),
            intervalo=float(self.intervalo_spin.value()),
            lote_inicial=lote_inicial,
        )
        self.worker = PriceListSendWorker(runner)
        self.worker.signals.evento.connect(self._al_evento)
        self.worker.signals.terminado.connect(self._al_terminar)
        self.worker.signals.error.connect(self._al_error)
        QThreadPool.globalInstance().start(self.worker)
        self.pausar_button.setEnabled(True)
        self.cancelar_button.setEnabled(True)
        self.exportar_button.setEnabled(True)
        self._set_seleccion_habilitada(False)
        self._refrescar_boton_enviar()

    def _set_seleccion_habilitada(self, habilitado: bool) -> None:
        """Bloquea la selección y la preparación mientras corre una cola (#793)."""
        self.destinatarios_table.setEnabled(habilitado)
        self.lista_combo.setEnabled(habilitado)
        self.elegir_pdf_button.setEnabled(habilitado)
        self.calcular_button.setEnabled(habilitado)
        self.guardar_button.setEnabled(habilitado)
        if not habilitado:
            self.seleccionar_todos_button.setEnabled(False)
            self.deseleccionar_todos_button.setEnabled(False)
            self.enviar_button.setText("Iniciar envío")
        else:
            self._actualizar_controles_seleccion()

    def _pausar(self) -> None:
        if self.worker is None:
            return
        self.worker.runner.pausar()
        self.pausar_button.setEnabled(False)
        self._refrescar_boton_enviar()
        self.resumen_label.setText("En pausa. Tocá \"Reanudar envío\" para seguir.")

    def _cancelar(self) -> None:
        if self.worker is None:
            return
        self.worker.runner.cancelar()
        self.cancelar_button.setEnabled(False)

    def _reintentar_fallidos(self) -> None:
        if self.worker is not None:
            return
        if self.pendientes_restantes:
            # El lote inicial se detuvo: se sigue con los que quedaron.
            pendientes = list(self.pendientes_restantes)
            self.pendientes_restantes = []
            self.reintentar_button.setText("Reintentar fallidos")
            self._iniciar_worker(pendientes, lote_inicial=0, excluir_enviados=False)
            return
        if not self.fallidos:
            self.feedback.show_warning("No hay fallidos para reintentar.")
            return
        fallidos = list(self.fallidos)
        self.fallidos = []
        # El reintento es una orden explicita del operador: ignora la idempotencia.
        self._iniciar_worker(fallidos, lote_inicial=0, excluir_enviados=False)

    def _al_evento(self, evento) -> None:
        fila = self.estado_filas.setdefault(
            evento.client_id,
            {"estado": ESTADO_EN_COLA, "detalle": "", "hora": ""},
        )
        if evento.tipo == "enviado":
            fila["estado"] = ESTADO_ENVIADO
            fila["detalle"] = evento.detalle
            fila["hora"] = datetime.now().strftime("%H:%M:%S")
        elif evento.tipo == "fallido":
            fila["estado"] = ESTADO_FALLIDO
            fila["detalle"] = evento.detalle
            fila["hora"] = datetime.now().strftime("%H:%M:%S")
            for destinatario in self.destinatarios:
                if destinatario.client_id == evento.client_id:
                    self.fallidos.append(destinatario)
                    break
        elif evento.tipo in {"tope", "detenido", "circuit_breaker"}:
            self.resumen_label.setText(evento.detalle)
        self._pintar_seguimiento()

    def _al_terminar(self, resultado) -> None:
        self.worker = None
        self.pausar_button.setEnabled(False)
        self.cancelar_button.setEnabled(False)
        self.reintentar_button.setEnabled(bool(self.fallidos))
        self.enviar_button.setText("Iniciar envío")
        self.resumen_label.setText(
            f"{resultado.enviados} enviados · {resultado.fallidos} fallidos · "
            f"{resultado.omitidos} omitidos. {resultado.motivo}".strip()
        )
        if resultado.detenido_por == "lote_inicial":
            # Solo se continúa con los seleccionados que efectivamente entraron a la cola.
            self.pendientes_restantes = [
                destinatario
                for destinatario in self.pendientes
                if destinatario.client_id not in self.estado_filas
            ]
            self.feedback.show_info(resultado.motivo)
            self.reintentar_button.setText("Continuar con los que quedan")
            self.reintentar_button.setEnabled(True)
        self._set_seleccion_habilitada(True)
        self._refrescar_boton_enviar()

    def _al_error(self, mensaje: str) -> None:
        self.worker = None
        self.enviar_button.setText("Iniciar envío")
        self.feedback.show_warning(f"No se pudo completar el envío: {mensaje}")
        self._set_seleccion_habilitada(True)
        self._refrescar_boton_enviar()

    def _pintar_seguimiento(self) -> None:
        self.seguimiento_table.setRowCount(0)
        for fila, (client_id, estado) in enumerate(self.estado_filas.items()):
            nombre = ""
            numero = ""
            for destinatario in self.destinatarios:
                if destinatario.client_id == client_id:
                    nombre = destinatario.nombre
                    numero = destinatario.telefono_normalizado
                    break
            self.seguimiento_table.insertRow(fila)
            self.seguimiento_table.setItem(fila, 0, QTableWidgetItem(nombre))
            self.seguimiento_table.setItem(fila, 1, QTableWidgetItem(numero))
            self.seguimiento_table.setItem(fila, 2, QTableWidgetItem(ETIQUETA_ESTADO.get(estado["estado"], estado["estado"])))
            self.seguimiento_table.setItem(fila, 3, QTableWidgetItem(estado["detalle"]))
            self.seguimiento_table.setItem(fila, 4, QTableWidgetItem(estado["hora"]))

    def _exportar_csv(self) -> None:
        if not self.estado_filas:
            self.feedback.show_warning("Todavía no hay envíos para exportar.")
            return
        destino, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar el log de la campaña",
            "log_lista_precios.csv",
            "CSV (*.csv)",
        )
        if not destino:
            return
        try:
            with open(destino, "w", newline="", encoding="utf-8") as archivo:
                escritor = csv.writer(archivo)
                escritor.writerow(["Cliente", "Número", "Estado", "Detalle", "Hora"])
                for client_id, estado in self.estado_filas.items():
                    nombre = ""
                    numero = ""
                    for destinatario in self.destinatarios:
                        if destinatario.client_id == client_id:
                            nombre = destinatario.nombre
                            numero = destinatario.telefono_normalizado
                            break
                    escritor.writerow(
                        [nombre, numero, estado["estado"], estado["detalle"], estado["hora"]]
                    )
        except OSError as exc:
            self.feedback.show_warning(f"No se pudo guardar el archivo: {exc}")
            return
        self.feedback.show_info(f"Log guardado en {destino}")
