from __future__ import annotations

from peewee import fn
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.models.masters import Carrier, Driver, Truck
from app.services.master_service import MasterService


class TransportSetupDialog(QDialog):
    """Guided setup for a carrier, its driver and its habitual truck."""

    def __init__(self, *, current_user: str, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.saved_carrier: Carrier | None = None
        self.saved_driver: Driver | None = None
        self.saved_truck: Truck | None = None
        self.setObjectName("transportSetupDialog")
        self.setWindowTitle("Configurar transporte")
        self.setMinimumWidth(620)
        self._build()
        self._refresh_carriers()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("Configurar transporte")
        title.setObjectName("transportSetupTitle")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title)

        intro = QLabel(
            "Cargue transportista, chofer y camión en un solo paso. "
            "También puede elegir un transportista existente y agregarle una nueva unidad."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)

        section_carrier = QLabel("1. Transportista")
        section_carrier.setStyleSheet("font-weight: 700;")
        form.addWidget(section_carrier, 0, 0, 1, 2)

        self.carrier_combo = QComboBox()
        self.carrier_combo.setObjectName("transportSetupCarrierInput")
        self.carrier_combo.currentIndexChanged.connect(self._carrier_changed)
        form.addWidget(QLabel("Usar"), 1, 0)
        form.addWidget(self.carrier_combo, 1, 1)

        self.carrier_name_input = QLineEdit()
        self.carrier_name_input.setObjectName("transportSetupCarrierNameInput")
        self.carrier_cuit_input = QLineEdit()
        self.carrier_cuit_input.setObjectName("transportSetupCarrierCuitInput")
        self.carrier_phone_input = QLineEdit()
        self.carrier_phone_input.setObjectName("transportSetupCarrierPhoneInput")
        form.addWidget(QLabel("Nombre / razón social"), 2, 0)
        form.addWidget(self.carrier_name_input, 2, 1)
        form.addWidget(QLabel("CUIT"), 3, 0)
        form.addWidget(self.carrier_cuit_input, 3, 1)
        form.addWidget(QLabel("Teléfono"), 4, 0)
        form.addWidget(self.carrier_phone_input, 4, 1)

        section_truck = QLabel("2. Camión")
        section_truck.setStyleSheet("font-weight: 700;")
        form.addWidget(section_truck, 5, 0, 1, 2)

        self.truck_domain_input = QLineEdit()
        self.truck_domain_input.setObjectName("transportSetupTruckDomainInput")
        self.truck_domain_input.setPlaceholderText("Ej. AF123ZZ")
        self.trailer_domain_input = QLineEdit()
        self.trailer_domain_input.setObjectName("transportSetupTrailerDomainInput")
        self.trailer_domain_input.setPlaceholderText("Opcional")
        form.addWidget(QLabel("Patente tractor"), 6, 0)
        form.addWidget(self.truck_domain_input, 6, 1)
        form.addWidget(QLabel("Patente acoplado"), 7, 0)
        form.addWidget(self.trailer_domain_input, 7, 1)

        section_driver = QLabel("3. Chofer")
        section_driver.setStyleSheet("font-weight: 700;")
        form.addWidget(section_driver, 8, 0, 1, 2)

        self.driver_name_input = QLineEdit()
        self.driver_name_input.setObjectName("transportSetupDriverNameInput")
        self.driver_document_input = QLineEdit()
        self.driver_document_input.setObjectName("transportSetupDriverDocumentInput")
        self.driver_phone_input = QLineEdit()
        self.driver_phone_input.setObjectName("transportSetupDriverPhoneInput")
        form.addWidget(QLabel("Nombre"), 9, 0)
        form.addWidget(self.driver_name_input, 9, 1)
        form.addWidget(QLabel("Documento"), 10, 0)
        form.addWidget(self.driver_document_input, 10, 1)
        form.addWidget(QLabel("Teléfono"), 11, 0)
        form.addWidget(self.driver_phone_input, 11, 1)

        layout.addLayout(form)

        self.feedback = QLabel("")
        self.feedback.setObjectName("transportSetupFeedback")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.setObjectName("cancelTransportSetupButton")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Guardar configuración")
        save.setObjectName("saveTransportSetupButton")
        save.clicked.connect(self._save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)

    def _refresh_carriers(self) -> None:
        current_id = self.carrier_combo.currentData()
        self.carrier_combo.blockSignals(True)
        self.carrier_combo.clear()
        self.carrier_combo.addItem("+ Nuevo transportista", None)
        for carrier in Carrier.select().where(Carrier.active == True).order_by(Carrier.name):  # noqa: E712
            self.carrier_combo.addItem(carrier.name, carrier.id)
        if current_id is not None:
            index = self.carrier_combo.findData(current_id)
            if index >= 0:
                self.carrier_combo.setCurrentIndex(index)
        self.carrier_combo.blockSignals(False)
        self._carrier_changed()

    def _carrier_changed(self) -> None:
        carrier_id = self.carrier_combo.currentData()
        is_new = carrier_id is None
        for widget in (
            self.carrier_name_input,
            self.carrier_cuit_input,
            self.carrier_phone_input,
        ):
            widget.setEnabled(is_new)

        if is_new:
            self.carrier_name_input.clear()
            self.carrier_cuit_input.clear()
            self.carrier_phone_input.clear()
            return

        carrier = Carrier.get_by_id(carrier_id)
        self.carrier_name_input.setText(carrier.name)
        self.carrier_cuit_input.setText(carrier.cuit or "")
        self.carrier_phone_input.setText(carrier.phone or "")

    @staticmethod
    def _find_named_driver(name: str) -> Driver | None:
        return Driver.get_or_none(fn.LOWER(Driver.name) == name.lower())

    @staticmethod
    def _find_named_carrier(name: str) -> Carrier | None:
        return Carrier.get_or_none(fn.LOWER(Carrier.name) == name.lower())

    def _save(self) -> None:
        from app.ui import master_abm

        carrier_id = self.carrier_combo.currentData()
        carrier_name = self.carrier_name_input.text().strip()
        driver_name = self.driver_name_input.text().strip()
        domain = master_abm._normalize_domain(self.truck_domain_input.text())
        trailer_domain = master_abm._normalize_domain(self.trailer_domain_input.text()) or None

        if carrier_id is None and not carrier_name:
            self.feedback.setText("Complete el nombre del transportista o seleccione uno existente.")
            return
        if not domain:
            self.feedback.setText("Complete la patente del camión.")
            return
        if not driver_name:
            self.feedback.setText("Complete el nombre del chofer.")
            return

        if carrier_id is None and self._find_named_carrier(carrier_name) is not None:
            self.feedback.setText(
                "Ese transportista ya existe. Selecciónelo en la lista para agregarle el chofer y el camión."
            )
            return

        service = MasterService(self.current_user)
        database = Carrier._meta.database
        try:
            with database.atomic():
                if carrier_id is None:
                    carrier = service.create_carrier(
                        carrier_name,
                        cuit=self.carrier_cuit_input.text().strip() or None,
                        phone=self.carrier_phone_input.text().strip() or None,
                    )
                else:
                    carrier = Carrier.get_by_id(carrier_id)

                truck = Truck.get_or_none(Truck.domain == domain)
                if truck is None:
                    truck = service.create_truck(
                        domain,
                        carrier=carrier,
                        trailer_domain=trailer_domain,
                    )
                elif truck.carrier_id not in {None, carrier.id}:
                    raise ValueError("La patente ingresada ya pertenece a otro transportista.")
                else:
                    changed = False
                    if truck.carrier_id is None:
                        truck.carrier = carrier
                        changed = True
                    if trailer_domain and not truck.trailer_domain:
                        truck.trailer_domain = trailer_domain
                        changed = True
                    if changed:
                        truck.save()

                driver = self._find_named_driver(driver_name)
                if driver is None:
                    driver = service.create_driver(
                        driver_name,
                        carrier=carrier,
                        usual_truck=truck,
                        document=self.driver_document_input.text().strip() or None,
                        phone=self.driver_phone_input.text().strip() or None,
                    )
                elif driver.carrier_id not in {None, carrier.id}:
                    raise ValueError("Ese chofer ya pertenece a otro transportista.")
                else:
                    driver.carrier = carrier
                    driver.usual_truck = truck
                    if self.driver_document_input.text().strip():
                        driver.document = self.driver_document_input.text().strip()
                    if self.driver_phone_input.text().strip():
                        driver.phone = self.driver_phone_input.text().strip()
                    driver.save()

                self.saved_carrier = carrier
                self.saved_driver = driver
                self.saved_truck = truck
            self.accept()
        except Exception as exc:
            self.feedback.setText(str(exc))


def install_transport_setup_extension() -> None:
    """Add a guided setup entry point without replacing the existing ABMs."""
    from app.ui import master_abm

    base_builder = master_abm.build_master_abm_page
    if getattr(base_builder, "_transport_setup_extension_installed", False):
        return

    def build_master_abm_page(*, config, user, current_user: str, parent=None) -> QWidget:
        page = base_builder(
            config=config,
            user=user,
            current_user=current_user,
            parent=parent,
        )
        if config.title not in {"Transportistas", "Choferes", "Camiones"}:
            return page

        panel = QWidget(page)
        panel.setObjectName(f"transportSetupPanel{config.new_button_name}")
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(
            "¿Configuración inicial? Cargue transportista, chofer y camión sin salir de esta pantalla."
        )
        hint.setWordWrap(True)
        button = QPushButton("Configurar transporte")
        button.setObjectName(f"transportSetupButton{config.new_button_name}")

        can_setup = all(
            master_abm._can_use_menu_action(user, "Maestros", "crear", title)
            for title in ("Transportistas", "Choferes", "Camiones")
        )
        button.setEnabled(can_setup)
        if not can_setup:
            button.setToolTip(
                "Se necesitan permisos de creación de transportistas, choferes y camiones."
            )

        def open_setup() -> None:
            if not can_setup:
                return
            dialog = TransportSetupDialog(current_user=current_user, parent=parent)
            if dialog.exec_() == QDialog.Accepted:
                refresh = getattr(page, "refresh", None)
                if callable(refresh):
                    refresh()

        button.clicked.connect(open_setup)
        row.addWidget(hint, 1)
        row.addWidget(button)

        layout = page.layout()
        insert_at = max(0, layout.count() - 2)
        layout.insertWidget(insert_at, panel)
        return page

    build_master_abm_page._transport_setup_extension_installed = True
    master_abm.build_master_abm_page = build_master_abm_page
