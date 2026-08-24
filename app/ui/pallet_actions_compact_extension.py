from __future__ import annotations

from PyQt5.QtWidgets import QFrame, QSizePolicy


def _compact_batch_actions(widget) -> None:
    """Reordena las acciones de Preparacion de pallets sin alterar su logica."""

    batch_frame = widget.findChild(QFrame, "palletBatchActions")
    if batch_frame is None:
        return
    layout = batch_frame.layout()
    if layout is None:
        return

    label_item = layout.itemAtPosition(0, 0)
    add_label = label_item.widget() if label_item is not None else None

    while layout.count():
        layout.takeAt(0)

    if add_label is not None:
        add_label.setText("Agregar:")

    widget.propose_distribution_button.setText("Proponer distribucion")
    widget.reorganize_pending_button.setText("Reorganizar")
    widget.recalculate_all_button.setText("Recalcular")
    widget.configure_pallet_capacity_button.setText("Kg/pallet")
    widget.configure_truck_capacity_button.setText("Cap. camion")
    widget.clear_assignments_button.setText("Quitar asignaciones")

    buttons = (
        widget.add_pallet_button,
        widget.propose_distribution_button,
        widget.reorganize_pending_button,
        widget.recalculate_all_button,
        widget.configure_pallet_capacity_button,
        widget.configure_truck_capacity_button,
        widget.clear_assignments_button,
    )
    for button in buttons:
        button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        button.setMinimumWidth(0)
        button.setMaximumHeight(34)

    widget.bulk_pallet_count_input.setMinimumWidth(44)
    widget.bulk_pallet_count_input.setMaximumWidth(64)
    widget.bulk_pallet_count_input.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    widget.clear_assignments_button.setToolTip(
        "Quita todas las asignaciones de mercaderia de los pallets."
    )
    widget.clear_assignments_button.setStyleSheet(
        "QPushButton { color: #9b2c2c; font-weight: 700; }"
    )

    layout.setHorizontalSpacing(6)
    layout.setVerticalSpacing(0)
    column = 0
    if add_label is not None:
        layout.addWidget(add_label, 0, column)
        column += 1
    layout.addWidget(widget.bulk_pallet_count_input, 0, column)
    column += 1
    layout.addWidget(widget.add_pallet_button, 0, column)
    column += 1
    layout.addWidget(widget.propose_distribution_button, 0, column)
    column += 1
    layout.addWidget(widget.reorganize_pending_button, 0, column)
    column += 1
    layout.addWidget(widget.recalculate_all_button, 0, column)
    column += 1
    layout.addWidget(widget.configure_pallet_capacity_button, 0, column)
    column += 1
    layout.addWidget(widget.configure_truck_capacity_button, 0, column)
    column += 1
    layout.addWidget(widget.clear_assignments_button, 0, column)

    for stretch_column in range(2, column + 1):
        layout.setColumnStretch(stretch_column, 1)


def install_compact_pallet_actions() -> None:
    """Instala una extension UI acotada para la barra de acciones de pallets."""

    from app.ui.pallet_composition import PalletCompositionWidget

    if getattr(PalletCompositionWidget, "_compact_actions_issue_300_installed", False):
        return

    original_install = PalletCompositionWidget._install_auto_distribution_ui

    def compact_install(self) -> None:
        original_install(self)
        _compact_batch_actions(self)

    PalletCompositionWidget._install_auto_distribution_ui = compact_install
    PalletCompositionWidget._compact_actions_issue_300_installed = True
