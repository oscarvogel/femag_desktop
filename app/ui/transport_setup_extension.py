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
from app.ui.combo_autocomplete import combo_current_data, enable_combo_autocomplete
from app.ui.form_feedback import FormFeedback


class TransportSetupDialog(QDialog):
    """Guided setup/reassignment for a carrier, driver and habitual truck."""

    def __init__(
        self,
        *,
        current_user: str,
        initial_carrier_id: int | None = None,
        initial_truck_id: int | None = None,
        initial_driver_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.current_user = current_user
        self.initial_carrier_id = initial_carrier_id
        self.initial_truck_id = initial_truck_id
        self.initial_driver_id = initial_driver_id
        self.saved_carrier: Carrier | None = None
        self.saved_driver: Driver | None = None
        self.saved_truck: Truck | None = None
        self.setObjectName("transportSetupDialog")
        self.setWindowTitle("Configurar transporte")
        self.setMinimumWidth(660)
        self._build()
        self._refresh_carriers()
        self._refresh_trucks()
        self._refresh_drivers()
        self._apply_initial_context()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("Configurar transporte")
        title.setObjectName("transportSetupTitle")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title)

        intro = QLabel(
            "Seleccione datos ya cargados o cree los que falten. "
            "Si un chofer o camión pertenece a otro transportista, FEMAG lo avisará antes de guardar la nueva relación."
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
        enable_combo_autocomplete(
            self.carrier_combo,
            placeholder="Buscar transportista...",
        )
        self.carrier_combo.currentIndexChanged.connect(self._carrier_changed)
        form.addWidget(QLabel("Usar"), 1, 0)
        form.addWidget(self.carrier_combo, 1, 1)

        self.carrier_name_input = QLineEdit()
        self.carrier_name_input.setObjectName("transportSetupCarrierNameInput")
        self.carrier_name_input.textChanged.connect(self._update_assignment_warnings)
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

        self.truck_combo = QComboBox()
        self.truck_combo.setObjectName("transportSetupTruckInput")
        enable_combo_autocomplete(
            self.truck_combo,
            placeholder="Buscar patente...",
        )
        self.truck_combo.currentIndexChanged.connect(self._truck_changed)
        form.addWidget(QLabel("Usar"), 6, 0)
        form.addWidget(self.truck_combo, 6, 1)

        self.truck_domain_input = QLineEdit()
        self.truck_domain_input.setObjectName("transportSetupTruckDomainInput")
        self.truck_domain_input.setPlaceholderText("Ej. AF123ZZ")
        self.trailer_domain_input = QLineEdit()
        self.trailer_domain_input.setObjectName("transportSetupTrailerDomainInput")
        self.trailer_domain_input.setPlaceholderText("Opcional")
        form.addWidget(QLabel("Patente tractor"), 7, 0)
        form.addWidget(self.truck_domain_input, 7, 1)
        form.addWidget(QLabel("Patente acoplado"), 8, 0)
        form.addWidget(self.trailer_domain_input, 8, 1)

        self.truck_warning = FormFeedback("transportSetupTruckWarning")
        form.addWidget(self.truck_warning, 9, 0, 1, 2)

        section_driver = QLabel("3. Chofer")
        section_driver.setStyleSheet("font-weight: 700;")
        form.addWidget(section_driver, 10, 0, 1, 2)

        self.driver_combo = QComboBox()
        self.driver_combo.setObjectName("transportSetupDriverInput")
        enable_combo_autocomplete(
            self.driver_combo,
            placeholder="Buscar chofer...",
        )
        self.driver_combo.currentIndexChanged.connect(self._driver_changed)
        form.addWidget(QLabel("Usar"), 11, 0)
        form.addWidget(self.driver_combo, 11, 1)

        self.driver_name_input = QLineEdit()
        self.driver_name_input.setObjectName("transportSetupDriverNameInput")
        self.driver_document_input = QLineEdit()
        self.driver_document_input.setObjectName("transportSetupDriverDocumentInput")
        self.driver_phone_input = QLineEdit()
        self.driver_phone_input.setObjectName("transportSetupDriverPhoneInput")
        form.addWidget(QLabel("Nombre"), 12, 0)
        form.addWidget(self.driver_name_input, 12, 1)
        form.addWidget(QLabel("Documento"), 13, 0)
        form.addWidget(self.driver_document_input, 13, 1)
        form.addWidget(QLabel("Teléfono"), 14, 0)
        form.addWidget(self.driver_phone_input, 14, 1)

        self.driver_warning = FormFeedback("transportSetupDriverWarning")
        form.addWidget(self.driver_warning, 15, 0, 1, 2)

        layout.addLayout(form)

        self.feedback = FormFeedback("transportSetupFeedback")
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
        self.carrier_combo.blockSignals(True)
        self.carrier_combo.clear()
        self.carrier_combo.addItem("+ Nuevo transportista", None)
        for carrier in Carrier.select().where(Carrier.active == True).order_by(Carrier.name):  # noqa: E712
            self.carrier_combo.addItem(carrier.name, carrier.id)
        self.carrier_combo.blockSignals(False)
        self._carrier_changed()

    def _refresh_trucks(self) -> None:
        self.truck_combo.blockSignals(True)
        self.truck_combo.clear()
        self.truck_combo.addItem("+ Nueva patente", None)
        for truck in Truck.select().where(Truck.active == True).order_by(Truck.domain):  # noqa: E712
            carrier_name = truck.carrier.name if truck.carrier_id is not None else "Sin transportista"
            label = truck.domain
            if truck.trailer_domain:
                label += f" / {truck.trailer_domain}"
            self.truck_combo.addItem(f"{label} · {carrier_name}", truck.id)
        self.truck_combo.blockSignals(False)
        self._truck_changed()

    def _refresh_drivers(self) -> None:
        self.driver_combo.blockSignals(True)
        self.driver_combo.clear()
        self.driver_combo.addItem("+ Nuevo chofer", None)
        for driver in Driver.select().where(Driver.active == True).order_by(Driver.name):  # noqa: E712
            carrier_name = driver.carrier.name if driver.carrier_id is not None else "Sin transportista"
            self.driver_combo.addItem(f"{driver.name} · {carrier_name}", driver.id)
        self.driver_combo.blockSignals(False)
        self._driver_changed()

    def _apply_initial_context(self) -> None:
        if self.initial_carrier_id is not None:
            self._set_combo_by_data(self.carrier_combo, self.initial_carrier_id)
        if self.initial_truck_id is not None:
            self._set_combo_by_data(self.truck_combo, self.initial_truck_id)
        if self.initial_driver_id is not None:
            self._set_combo_by_data(self.driver_combo, self.initial_driver_id)
        self._update_assignment_warnings()

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, value: int) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _carrier_changed(self) -> None:
        carrier_id = combo_current_data(self.carrier_combo)
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
        else:
            carrier = Carrier.get_by_id(carrier_id)
            self.carrier_name_input.setText(carrier.name)
            self.carrier_cuit_input.setText(carrier.cuit or "")
            self.carrier_phone_input.setText(carrier.phone or "")
        self._update_assignment_warnings()

    def _truck_changed(self) -> None:
        truck_id = combo_current_data(self.truck_combo)
        is_new = truck_id is None
        self.truck_domain_input.setEnabled(is_new)
        self.trailer_domain_input.setEnabled(True)
        if is_new:
            self.truck_domain_input.clear()
            self.trailer_domain_input.clear()
        else:
            truck = Truck.get_by_id(truck_id)
            self.truck_domain_input.setText(truck.domain)
            self.trailer_domain_input.setText(truck.trailer_domain or "")
        self._update_assignment_warnings()

    def _driver_changed(self) -> None:
        driver_id = combo_current_data(self.driver_combo)
        is_new = driver_id is None
        for widget in (
            self.driver_name_input,
            self.driver_document_input,
            self.driver_phone_input,
        ):
            widget.setEnabled(is_new)
        if is_new:
            self.driver_name_input.clear()
            self.driver_document_input.clear()
            self.driver_phone_input.clear()
        else:
            driver = Driver.get_by_id(driver_id)
            self.driver_name_input.setText(driver.name)
            self.driver_document_input.setText(driver.document or "")
            self.driver_phone_input.setText(driver.phone or "")
        self._update_assignment_warnings()

    def _target_carrier_name(self) -> str:
        carrier_id = combo_current_data(self.carrier_combo)
        if carrier_id is not None:
            return Carrier.get_by_id(carrier_id).name
        return self.carrier_name_input.text().strip() or "el nuevo transportista"

    def _update_assignment_warnings(self) -> None:
        if not hasattr(self, "truck_warning") or not hasattr(self, "driver_warning"):
            return
        carrier_id = combo_current_data(self.carrier_combo)
        target_name = self._target_carrier_name()

        truck_message = ""
        truck_id = combo_current_data(self.truck_combo)
        if truck_id is not None:
            truck = Truck.get_by_id(truck_id)
            if truck.carrier_id is not None and truck.carrier_id != carrier_id:
                truck_message = (
                    f"Atención: esta patente está asignada a {truck.carrier.name}. "
                    f"Al guardar se reasignará a {target_name}."
                )
        if truck_message:
            self.truck_warning.show_warning(truck_message)
        else:
            self.truck_warning.clear_message()

        driver_message = ""
        driver_id = combo_current_data(self.driver_combo)
        if driver_id is not None:
            driver = Driver.get_by_id(driver_id)
            messages: list[str] = []
            if driver.carrier_id is not None and driver.carrier_id != carrier_id:
                messages.append(
                    f"Este chofer está asignado a {driver.carrier.name}; al guardar se reasignará a {target_name}."
                )
            if truck_id is not None and driver.usual_truck_id not in {None, truck_id}:
                messages.append(
                    f"Su camión habitual actual es {driver.usual_truck.domain}; al guardar quedará la patente seleccionada."
                )
            driver_message = " ".join(messages)
        if driver_message:
            self.driver_warning.show_warning(driver_message)
        else:
            self.driver_warning.clear_message()

    @staticmethod
    def _find_named_driver(name: str) -> Driver | None:
        return Driver.get_or_none(fn.LOWER(Driver.name) == name.lower())

    @staticmethod
    def _find_named_carrier(name: str) -> Carrier | None:
        return Carrier.get_or_none(fn.LOWER(Carrier.name) == name.lower())

    def _save(self) -> None:
        from app.ui import master_abm

        carrier_id = combo_current_data(self.carrier_combo)
        truck_id = combo_current_data(self.truck_combo)
        driver_id = combo_current_data(self.driver_combo)
        carrier_name = self.carrier_name_input.text().strip()
        domain = master_abm._normalize_domain(self.truck_domain_input.text())
        trailer_domain = master_abm._normalize_domain(self.trailer_domain_input.text()) or None
        driver_name = self.driver_name_input.text().strip()

        if carrier_id is None and not carrier_name:
            self.feedback.show_warning(
                "Complete el nombre del transportista o seleccione uno existente.",
                focus_widget=self.carrier_name_input,
            )
            return
        if truck_id is None and not domain:
            self.feedback.show_warning(
                "Seleccione una patente existente o complete una nueva patente.",
                focus_widget=self.truck_domain_input,
            )
            return
        if driver_id is None and not driver_name:
            self.feedback.show_warning(
                "Seleccione un chofer existente o complete un nuevo chofer.",
                focus_widget=self.driver_name_input,
            )
            return
        if carrier_id is None and self._find_named_carrier(carrier_name) is not None:
            self.feedback.show_warning(
                "Ese transportista ya existe. Selecciónelo en la lista para continuar.",
                focus_widget=self.carrier_combo,
            )
            return
        if truck_id is None and Truck.get_or_none(Truck.domain == domain) is not None:
            self.feedback.show_warning(
                "Esa patente ya existe. Selecciónela en la lista para poder conservar o cambiar su asignación.",
                focus_widget=self.truck_combo,
            )
            return
        if driver_id is None and self._find_named_driver(driver_name) is not None:
            self.feedback.show_warning(
                "Ese chofer ya existe. Selecciónelo en la lista para poder conservar o cambiar su asignación.",
                focus_widget=self.driver_combo,
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

                if truck_id is None:
                    truck = service.create_truck(
                        domain,
                        carrier=carrier,
                        trailer_domain=trailer_domain,
                    )
                else:
                    truck = Truck.get_by_id(truck_id)
                    truck.trailer_domain = trailer_domain
                    if truck.carrier_id != carrier.id:
                        truck.carrier = carrier
                    truck.save()

                if driver_id is None:
                    driver = service.create_driver(
                        driver_name,
                        carrier=carrier,
                        usual_truck=truck,
                        document=self.driver_document_input.text().strip() or None,
                        phone=self.driver_phone_input.text().strip() or None,
                    )
                else:
                    driver = Driver.get_by_id(driver_id)
                    driver.carrier = carrier
                    driver.usual_truck = truck
                    driver.save()

                self.saved_carrier = carrier
                self.saved_driver = driver
                self.saved_truck = truck
            self.accept()
        except Exception as exc:
            self.feedback.show_error(str(exc))


def _selected_transport_context(page: QWidget, title: str) -> tuple[int | None, int | None, int | None]:
    controller = getattr(page, "master_table_controller", None)
    row_id = controller.selected_id() if controller is not None else None
    if row_id is None:
        return None, None, None
    if title == "Transportistas":
        return row_id, None, None
    if title == "Choferes":
        driver = Driver.get_by_id(row_id)
        return driver.carrier_id, driver.usual_truck_id, driver.id
    if title == "Camiones":
        truck = Truck.get_by_id(row_id)
        return truck.carrier_id, truck.id, None
    return None, None, None


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
            "¿Configuración inicial o cambio de asignación? Seleccione una fila y configure el conjunto sin salir de esta pantalla."
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
            initial_carrier_id, initial_truck_id, initial_driver_id = _selected_transport_context(
                page,
                config.title,
            )
            dialog = TransportSetupDialog(
                current_user=current_user,
                initial_carrier_id=initial_carrier_id,
                initial_truck_id=initial_truck_id,
                initial_driver_id=initial_driver_id,
                parent=parent,
            )
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
