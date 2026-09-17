from __future__ import annotations

from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout


LOAD_ORDER_INSTRUCTIONS_PLACEHOLDER = (
    "Indicaciones operativas para depósito/carga (se imprimen solo en la Orden de Carga)."
)
BUDGET_DESCRIPTION_PLACEHOLDER = (
    "Solo información comercial que debe aparecer en el presupuesto de este cliente."
)


def configure_load_order_instruction_fields(dialog) -> None:
    """Make the two observation concepts explicit without changing persistence.

    ``dialog.observations_input`` already persists to ``LoadOrder.observations`` and the
    load-order print service already includes that value. Destination observations,
    on the other hand, are the commercial description used by each client's budget.
    This helper moves the order-level field to the Review step and labels both concepts
    so operators do not enter loading instructions into a client's budget description.
    """

    observations_input = dialog.observations_input
    observations_input.setPlaceholderText(LOAD_ORDER_INSTRUCTIONS_PLACEHOLDER)
    observations_input.setToolTip(
        "Estas instrucciones pertenecen a la orden completa, salen en la Orden de Carga "
        "y no deben aparecer en los presupuestos."
    )

    review_page = dialog.step_stack.widget(3)
    existing_section = None
    if review_page is not None:
        existing_section = review_page.findChild(QFrame, "loadOrderInstructionsSection")

    if existing_section is None:
        # Remove the old, ambiguous label from Transporte. The input itself is
        # reparented into Revisar so it reads as a property of the complete order.
        transport_page = dialog.step_stack.widget(0)
        if transport_page is not None:
            for label in transport_page.findChildren(QLabel):
                if label.text().strip() == "Observaciones":
                    label.hide()

        parent = observations_input.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().removeWidget(observations_input)

        if review_page is not None and review_page.layout() is not None:
            section = QFrame(review_page)
            section.setObjectName("loadOrderInstructionsSection")
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 4, 0, 4)
            section_layout.setSpacing(4)

            title = QLabel("Instrucciones de carga de la orden", section)
            title.setObjectName("loadOrderInstructionsLabel")
            helper = QLabel(
                "Indicaciones operativas para depósito/carga. Se imprimen en la Orden de Carga "
                "y no en los presupuestos.",
                section,
            )
            helper.setObjectName("loadOrderInstructionsHelp")
            helper.setWordWrap(True)

            observations_input.setParent(section)
            section_layout.addWidget(title)
            section_layout.addWidget(helper)
            section_layout.addWidget(observations_input)

            # Review currently contains title + preparation hint + table. Put the
            # instructions immediately before the table.
            review_page.layout().insertWidget(2, section)

    destination_label = dialog.findChild(QLabel, "loadOrderDestinationBudgetDescriptionLabel")
    if destination_label is not None:
        destination_label.setText("Descripción comercial para presupuesto del cliente/destino")
        destination_label.setToolTip(
            "Este texto corresponde exclusivamente al presupuesto del cliente/destino seleccionado."
        )

    destination_input = getattr(dialog, "destination_budget_description_input", None)
    if destination_input is not None:
        destination_input.setPlaceholderText(BUDGET_DESCRIPTION_PLACEHOLDER)
        destination_input.setToolTip(
            "No use este campo para instrucciones de depósito o carga; esas instrucciones "
            "se cargan en el paso Revisar."
        )


def install_load_order_instructions_extension() -> None:
    """Install issue #454 UI clarification on the load-order entry dialog."""

    from app.ui import desktop_app

    if getattr(desktop_app, "_load_order_instructions_extension_installed", False):
        return

    base_dialog = desktop_app.LoadOrderEntryDialog

    class LoadOrderEntryDialogWithInstructions(base_dialog):
        def _build(self) -> None:
            super()._build()
            configure_load_order_instruction_fields(self)

    LoadOrderEntryDialogWithInstructions.__name__ = base_dialog.__name__
    LoadOrderEntryDialogWithInstructions.__qualname__ = base_dialog.__qualname__

    desktop_app.LoadOrderEntryDialog = LoadOrderEntryDialogWithInstructions
    desktop_app._load_order_instructions_extension_installed = True
