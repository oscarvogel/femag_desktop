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
        self.pendientes = []
        self.pendientes_restantes = []
        self.fallidos = []
        self.estado_filas: dict[int, dict] = {}
        self.clave_campana_actual = ""

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
        elegir_pdf = QPushButton("Seleccionar PDF")
        elegir_pdf.setObjectName("priceListSendPickPdfButton")
        elegir_pdf.clicked.connect(self._elegir_pdf)
        fila_pdf = QHBoxLayout()
        fila_pdf.addWidget(self.pdf_input, 1)
        fila_pdf.addWidget(elegir_pdf)
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
        modo_prueba = QPushButton("Usar 10 s (modo prueba)")
        modo_prueba.setObjectName("priceListSendTestSpeedButton")
        modo_prueba.clicked.connect(self._usar_velocidad_de_prueba)
        fila_intervalo = QHBoxLayout()
        fila_intervalo.addWidget(self.intervalo_spin)
        fila_intervalo.addWidget(modo_prueba)
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
        calcular = QPushButton("Calcular destinatarios")
        calcular.setObjectName("priceListSendCalculateButton")
        calcular.clicked.connect(self._calcular_destinatarios)
        acciones.addWidget(calcular)
        self.contadores_label = QLabel("Todavía no calculaste los destinatarios.")
        self.contadores_label.setObjectName("priceListSendCountersLabel")
        acciones.addWidget(self.contadores_label, 1)
        layout.addLayout(acciones)

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
        self.pdf_input.setText(config.pdf_path)
        self.mensaje_input.setPlainText(config.mensaje)

    def _al_cambiar_lista(self) -> None:
        self._cargar_configuracion()
        self.destinatarios = []
        self.destinatarios_table.setRowCount(0)
        self._refrescar_contadores()
        self._refrescar_boton_enviar()

    def _elegir_pdf(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Elegí el PDF de la lista de precios",
            "",
            "Documentos PDF (*.pdf)",
        )
        if not ruta:
            return
        self.pdf_input.setText(ruta)
        self.feedback.show_info(f"Elegiste {Path(ruta).name}. Guardá la configuración para dejarlo asociado.")

    def _usar_velocidad_de_prueba(self) -> None:
        self.intervalo_spin.setValue(10)
        self.feedback.show_info("Intervalo de 10 segundos. Sirve para pruebas, no para una campaña real.")

    def _al_cambiar_el_intervalo(self) -> None:
        if self.intervalo_spin.value() < INTERVALO_MINIMO:
            self.feedback.show_warning(
                "Intervalo de 10 segundos: es el modo prueba. "
                "Sirve para sacar 3 o 4 mensajes de prueba, no para una campaña real."
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
        self.pdf_input.setText(config.pdf_path)
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
        self.destinatarios_table.setRowCount(len(self.destinatarios))
        for fila, destinatario in enumerate(self.destinatarios):
            item_marca = QTableWidgetItem("")
            item_marca.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item_marca.setCheckState(Qt.Checked if destinatario.marcado else Qt.Unchecked)
            item_marca.setData(Qt.UserRole, destinatario.client_id)
            self.destinatarios_table.setItem(fila, 0, item_marca)
            self.destinatarios_table.setItem(fila, 1, QTableWidgetItem(destinatario.nombre))
            self.destinatarios_table.setItem(fila, 2, QTableWidgetItem(destinatario.telefono_original))
            self.destinatarios_table.setItem(fila, 3, QTableWidgetItem(destinatario.telefono_normalizado))
            detalle = destinatario.estado
            if destinatario.motivo:
                detalle = f"{destinatario.estado} ({destinatario.motivo})"
            self.destinatarios_table.setItem(fila, 4, QTableWidgetItem(detalle))

        self._refrescar_contadores()
        self._refrescar_boton_enviar()

    def _al_cambiar_un_destinatario(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        self._refrescar_contadores()
        self._refrescar_boton_enviar()

    def _refrescar_contadores(self) -> None:
        marcados = sum(1 for fila in range(self.destinatarios_table.rowCount())
                       if self.destinatarios_table.item(fila, 0)
                       and self.destinatarios_table.item(fila, 0).checkState() == Qt.Checked)
        totales = len(self.destinatarios)
        if not totales:
            self.contadores_label.setText("Todavía no calculaste los destinatarios.")
            return
        self.contadores_label.setText(
            f"{totales} clientes de la lista · {marcados} marcados para enviar"
        )
        self.aviso_texto.setText(
            f"Se van a mandar {marcados} mensajes desde tu instancia de WhatsApp. "
            "Revisá el PDF y los números antes de confirmar."
        )

    def _refrescar_boton_enviar(self) -> None:
        puede = (
            self.confirmacion_check.isChecked()
            and self._pendientes_marcados()
            and self.pdf_input.text().strip()
            and not self.worker
        )
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

    def _pendientes_marcados(self):
        pendientes = []
        for fila in range(self.destinatarios_table.rowCount()):
            item = self.destinatarios_table.item(fila, 0)
            if item is None or item.checkState() != Qt.Checked:
                continue
            client_id = item.data(Qt.UserRole)
            for destinatario in self.destinatarios:
                if destinatario.client_id == client_id:
                    pendientes.append(destinatario)
                    break
        return pendientes

    def _iniciar_envio(self) -> None:
        pendientes = self._pendientes_marcados()
        if not pendientes:
            self.feedback.show_warning("No hay destinatarios marcados.")
            return
        if not self.pdf_input.text().strip():
            self.feedback.show_warning("Elegí el PDF de la lista de precios.")
            return
        if not self.confirmacion_check.isChecked():
            self.feedback.show_warning("Tildá la confirmación para enviar desde tu línea.")
            return

        instancia = self._resolver_instancia()
        if not instancia:
            return

        respuesta = QMessageBox.question(
            self,
            "Confirmar el envío",
            f"Se enviarán {len(pendientes)} mensajes desde tu instancia de WhatsApp.\n\n"
            f"PDF: {Path(self.pdf_input.text()).name}\n\n"
            "¿Seguís?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if respuesta != QMessageBox.Yes:
            return

        self.pendientes = pendientes
        self._iniciar_worker(pendientes, lote_inicial=self.lote_spin.value())

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

        runner = PriceListCampaignRunner(
            clave=clave,
            pdf_path=self.pdf_input.text().strip(),
            pendientes=pendientes,
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
        self._refrescar_boton_enviar()

    def _pausar(self) -> None:
        if self.worker is None:
            return
        self.worker.runner.pausar()
        self.pausar_button.setEnabled(False)
        self.resumen_label.setText("En pausa. Volvé a tocar \"Iniciar envío\" para seguir.")

    def _cancelar(self) -> None:
        if self.worker is None:
            return
        self.worker.runner.cancelar()
        self.cancelar_button.setEnabled(False)

    def _reintentar_fallidos(self) -> None:
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
        self.resumen_label.setText(
            f"{resultado.enviados} enviados · {resultado.fallidos} fallidos · "
            f"{resultado.omitidos} omitidos. {resultado.motivo}".strip()
        )
        if resultado.detenido_por == "lote_inicial":
            # Quedan los que no se tocaron: el operador decide si sigue.
            self.pendientes_restantes = [
                destinatario
                for destinatario in self.destinatarios
                if destinatario.client_id not in self.estado_filas
            ]
            self.feedback.show_info(resultado.motivo)
            self.reintentar_button.setText("Continuar con los que quedan")
            self.reintentar_button.setEnabled(True)
        self._refrescar_boton_enviar()

    def _al_error(self, mensaje: str) -> None:
        self.worker = None
        self.feedback.show_warning(f"No se pudo completar el envío: {mensaje}")
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
