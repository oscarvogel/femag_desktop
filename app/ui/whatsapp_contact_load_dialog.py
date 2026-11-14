"""Carga masiva de los numeros de WhatsApp que faltan (#923).

Esta pantalla es una herramienta de **carga de datos**, no de envio: lista los
clientes que todavia no tienen un numero de WhatsApp cargado y deja que el
operador se lo cargue de a uno. Por eso no depende del flag
``FEMAG_WHATSAPP_DEDICADO``: cargar los numeros no manda ningun mensaje.

El numero se guarda en la base recien cuando el operador lo confirma en el
dialogo del cliente (``ClientWhatsappEditDialog``), que lo normaliza y lo
audita. Esta pantalla no guarda el texto crudo del campo de edicion: el valor
que queda en la base es el normalizado, sin el "+".
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.masters import Client
from app.services.whatsapp_contact_service import (
    ClientePendiente,
    WhatsAppContactService,
)
from app.services.whatsapp_phone_classifier import ESTADO_VACIO, clasificar_telefono
from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog
from app.ui.whatsapp_phone_edit_widgets import ESTILOS_CLASIFICACION

#: Columnas de la grilla. La ultima es la del boton de carga.
COLUMNA_CLIENTE = 0
COLUMNA_VENDEDOR = 1
COLUMNA_TELEFONO = 2
COLUMNA_ESTADO = 3
COLUMNA_WHATSAPP = 4
COLUMNA_ACCION = 5

#: Las columnas de datos que muestra la grilla.
COLUMNAS = ("Cliente", "Vendedor", "Telefono", "Estado", "WhatsApp")

#: Alto maximo del dialogo: tiene que entrar en 1366x768.
ALTO_MAXIMO = 720

#: Tamano por defecto. La pantalla del cliente es 1638x969 y la de referencia
#: 1366x768: con el minimo (980x520) la columna "Cliente" queda angosta y los
#: nombres largos se eliden. Este tamano aprovecha la pantalla del cliente y
#: todavia entra en la pantalla chica.
TAMANO_POR_DEFECTO = (1320, 680)


class WhatsAppContactLoadDialog(QDialog):
    """Lista los clientes pendientes de WhatsApp y deja cargar sus numeros."""

    def __init__(self, *, current_user: str, parent=None):
        super().__init__(parent)
        self.setObjectName("whatsappContactLoadDialog")
        self.setWindowTitle("Cargar WhatsApp de clientes")
        self.current_user = current_user
        self.service = WhatsAppContactService(current_user)

        self.setMinimumSize(980, 520)
        self.setMaximumSize(1600, ALTO_MAXIMO)
        self.resize(*TAMANO_POR_DEFECTO)

        self.intro_label = QLabel(
            "Carga masiva de numeros de WhatsApp: se listan los clientes que todavia "
            "no tienen numero cargado. Cada numero queda guardado en la base apenas el "
            "operador lo confirma en el dialogo del cliente. El telefono general del "
            "cliente no se toca."
        )
        self.intro_label.setObjectName("whatsappLoadIntro")
        self.intro_label.setWordWrap(True)

        self.only_with_order = QCheckBox("Solo con orden emitida")
        self.only_with_order.setObjectName("whatsappLoadOnlyWithOrderCheck")
        self.only_with_order.setToolTip(
            "Muestra solo los clientes con una orden que salio (emitida o cerrada). "
            "Las ordenes en borrador todavia no salieron y no cuentan."
        )
        self.only_with_order.setChecked(True)
        self.only_with_order.toggled.connect(self._recargar)

        self.refresh_button = QPushButton("Recargar")
        self.refresh_button.setObjectName("whatsappLoadRefreshButton")
        self.refresh_button.clicked.connect(self._recargar)

        self.table = QTableWidget(0, len(COLUMNAS) + 1)
        self.table.setObjectName("whatsappLoadTable")
        self.table.setHorizontalHeaderLabels([*COLUMNAS, ""])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        encabezado = self.table.horizontalHeader()
        encabezado.setSectionResizeMode(COLUMNA_CLIENTE, QHeaderView.Stretch)
        # Los anchos van fijos: el boton de carga tiene que quedar siempre
        # visible, sin barra horizontal.
        for columna, ancho in (
            (COLUMNA_VENDEDOR, 150),
            (COLUMNA_TELEFONO, 170),
            (COLUMNA_ESTADO, 110),
            (COLUMNA_WHATSAPP, 150),
        ):
            encabezado.setSectionResizeMode(columna, QHeaderView.Interactive)
            self.table.setColumnWidth(columna, ancho)
        encabezado.setSectionResizeMode(COLUMNA_ACCION, QHeaderView.ResizeToContents)

        # La tabla va con scroll: el dialogo no crece con la cantidad de filas.
        self.scroll = QScrollArea()
        self.scroll.setObjectName("whatsappLoadScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.table)

        self.status_label = QLabel()
        self.status_label.setObjectName("whatsappLoadStatus")

        self.close_button = QPushButton("Cerrar")
        self.close_button.setObjectName("whatsappLoadCloseButton")
        self.close_button.setToolTip(
            "Cierra la pantalla. Los numeros ya cargados quedaron guardados."
        )
        self.close_button.clicked.connect(self._cerrar)

        filtros = QHBoxLayout()
        filtros.addWidget(self.only_with_order)
        filtros.addStretch(1)
        filtros.addWidget(self.refresh_button)

        acciones = QHBoxLayout()
        acciones.addWidget(self.status_label, 1)
        acciones.addStretch(1)
        acciones.addWidget(self.close_button)

        root = QVBoxLayout(self)
        root.addWidget(self.intro_label)
        root.addLayout(filtros)
        root.addWidget(self.scroll, 1)
        root.addLayout(acciones)

        self._pendientes: list[ClientePendiente] = []
        self._cargados: list[int] = []
        self._recargar()

    # ----------------------------------------------------------------- datos

    def _recargar(self) -> None:
        """Vuelve a leer los pendientes desde la base."""
        self._pendientes = self.service.listar_clientes_pendientes(
            solo_con_orden=self.only_with_order.isChecked()
        )
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._pendientes))
        for fila, pendiente in enumerate(self._pendientes):
            self._pintar_fila(fila, pendiente)
        self._actualizar_estado()

    def _pintar_fila(self, fila: int, pendiente: ClientePendiente) -> None:
        """Pinta una fila de la grilla con su boton de carga."""
        cliente_item = QTableWidgetItem(pendiente.nombre)
        if pendiente.ultima_orden:
            cliente_item.setToolTip(f"Ultima orden: {pendiente.ultima_orden}")
        self.table.setItem(fila, COLUMNA_CLIENTE, cliente_item)
        self.table.setItem(fila, COLUMNA_VENDEDOR, QTableWidgetItem(pendiente.vendedor))
        self.table.setItem(fila, COLUMNA_TELEFONO, QTableWidgetItem(pendiente.telefono))

        estado_item = QTableWidgetItem(clasificar_telefono(pendiente.telefono).etiqueta)
        estado_item.setData(Qt.UserRole, pendiente.estado_telefono)
        self._pintar_estado(estado_item, pendiente.estado_telefono)
        self.table.setItem(fila, COLUMNA_ESTADO, estado_item)

        self.table.setItem(
            fila, COLUMNA_WHATSAPP, QTableWidgetItem(pendiente.whatsapp_phone)
        )

        boton = QPushButton("Cargar WhatsApp")
        boton.setObjectName(f"whatsappLoadRowButton_{pendiente.client_id}")
        boton.setToolTip("Carga el numero de WhatsApp de este cliente.")
        boton.clicked.connect(
            lambda _checked=False, objetivo=pendiente: self._cargar_whatsapp(objetivo)
        )
        self.table.setCellWidget(fila, COLUMNA_ACCION, boton)

    def _pintar_estado(self, item: QTableWidgetItem, estado: str) -> None:
        """Colorea la celda de estado con el color de la clasificacion."""
        color, fondo, _borde = ESTILOS_CLASIFICACION.get(
            estado, ESTILOS_CLASIFICACION[ESTADO_VACIO]
        )
        item.setForeground(QColor(color))
        item.setBackground(QColor(fondo))

    def _actualizar_estado(self) -> None:
        self.status_label.setText(
            f"{len(self._pendientes)} cliente(s) pendiente(s) | "
            f"{len(self._cargados)} cargado(s) en esta sesion"
        )

    # --------------------------------------------------------------- acciones

    def _cargar_whatsapp(self, pendiente: ClientePendiente) -> None:
        """Abre el dialogo del cliente y deja el numero cargado en la fila."""
        try:
            cliente = Client.get_by_id(pendiente.client_id)
        except Client.DoesNotExist:
            # El cliente se borro entre que se armo la lista y que el operador
            # aprieto el boton: no es un error del sistema, se avisa y se sigue.
            QMessageBox.warning(
                self,
                "Cargar WhatsApp",
                "El cliente ya no existe en la base. "
                'Apriete "Recargar" para actualizar la lista.',
            )
            return
        dialogo = ClientWhatsappEditDialog(
            client=cliente,
            current_user=self.current_user,
            parent=self,
        )
        if dialogo.exec_() != QDialog.Accepted:
            return
        # El dialogo del cliente ya guardo el numero normalizado y lo audito:
        # aca solo se muestra en la fila lo que quedo en la base.
        numero = (cliente.whatsapp_phone or "").strip()
        fila = self._fila_de(pendiente.client_id)
        if fila is not None:
            celda = self.table.item(fila, COLUMNA_WHATSAPP)
            if celda is not None:
                celda.setText(numero)
            boton = self.table.cellWidget(fila, COLUMNA_ACCION)
            if boton is not None:
                # Si el operador vacio el numero y lo guardo, el cliente sigue
                # sin WhatsApp: el boton tiene que quedar habilitado para poder
                # cargarlo, y no puede decir "Cargado" (#923).
                if numero:
                    boton.setText("Cargado")
                    boton.setEnabled(False)
                else:
                    boton.setText("Cargar WhatsApp")
                    boton.setEnabled(True)
        if numero and pendiente.client_id not in self._cargados:
            self._cargados.append(pendiente.client_id)
        self._actualizar_estado()

    def _fila_de(self, client_id: int) -> int | None:
        """La fila de la grilla de un cliente, si esta en la lista."""
        for fila, pendiente in enumerate(self._pendientes):
            if pendiente.client_id == client_id:
                return fila
        return None

    def _cerrar(self) -> None:
        """Cierra la carga. Los numeros ya quedaron guardados al confirmarlos."""
        self._recargar()
        self.accept()

    # -------------------------------------------------------------- resultado

    def numeros_cargados(self) -> list[int]:
        """Los ids de cliente a los que se les cargo el numero en esta sesion."""
        return list(self._cargados)
