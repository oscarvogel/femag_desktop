import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_issue_454_separates_load_instructions_from_budget_description(db):
    from PyQt5.QtWidgets import QApplication, QLabel

    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog
    from app.ui.load_order_instructions_extension import (
        BUDGET_DESCRIPTION_PLACEHOLDER,
        LOAD_ORDER_INSTRUCTIONS_PLACEHOLDER,
        configure_load_order_instruction_fields,
    )

    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderEntryDialog(
        LoadOrderService(current_user="issue454"),
        "issue454",
    )

    configure_load_order_instruction_fields(dialog)

    instructions = dialog.observations_input
    section = dialog.findChild(type(dialog.step_stack.widget(3)), "loadOrderInstructionsSection")
    if section is None:
        from PyQt5.QtWidgets import QFrame

        section = dialog.findChild(QFrame, "loadOrderInstructionsSection")

    assert section is not None
    assert instructions.parentWidget() is section
    assert instructions.placeholderText() == LOAD_ORDER_INSTRUCTIONS_PLACEHOLDER
    assert "Orden de Carga" in instructions.toolTip()
    assert "presupuestos" in instructions.toolTip()

    review_page = dialog.step_stack.widget(3)
    title = review_page.findChild(QLabel, "loadOrderInstructionsLabel")
    helper = review_page.findChild(QLabel, "loadOrderInstructionsHelp")
    assert title is not None
    assert title.text() == "Instrucciones de carga de la orden"
    assert helper is not None
    assert "no en los presupuestos" in helper.text()

    destination_label = dialog.findChild(QLabel, "loadOrderDestinationBudgetDescriptionLabel")
    assert destination_label is not None
    assert destination_label.text() == "Descripción comercial para presupuesto del cliente/destino"
    assert dialog.destination_budget_description_input.placeholderText() == BUDGET_DESCRIPTION_PLACEHOLDER
    assert "instrucciones" in dialog.destination_budget_description_input.toolTip().lower()

    transport_page = dialog.step_stack.widget(0)
    old_labels = [
        label
        for label in transport_page.findChildren(QLabel)
        if label.text().strip() == "Observaciones"
    ]
    assert old_labels
    assert all(label.isHidden() for label in old_labels)

    dialog.close()
    app.processEvents()


def test_issue_454_runtime_installs_load_order_extension():
    from app.ui import desktop_app
    from app.ui.load_order_instructions_extension import install_load_order_instructions_extension

    install_load_order_instructions_extension()
    patched_class = desktop_app.LoadOrderEntryDialog

    assert getattr(desktop_app, "_load_order_instructions_extension_installed", False)
    assert "Instructions" in patched_class.__mro__[0].__qualname__ or patched_class.__name__ == "LoadOrderEntryDialog"

    # Installation is deliberately idempotent because app.main imports it at startup.
    install_load_order_instructions_extension()
    assert desktop_app.LoadOrderEntryDialog is patched_class
