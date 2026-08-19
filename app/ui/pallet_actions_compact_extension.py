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

    secondary_buttons = (
        widget.reorganize_pending_button,
        widget.recalculate_all_button,
        widget.configure_pallet_capacity_button,
        widget.configure_truck_capacity_button,
    )
    for button in (*secondary_buttons, widget.clear_assignments_button):
        layout.removeWidget(button)

    widget.configure_pallet_capacity_button.setText("Configurar kg/pallet")
    widget.configure_truck_capacity_button.setText("Capacidad camion")

    for button in secondary_buttons:
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setMaximumHeight(36)

    layout.setHorizontalSpacing(8)
    layout.setVerticalSpacing(6)
    layout.addWidget(widget.reorganize_pending_button, 4, 0)
    layout.addWidget(widget.recalculate_all_button, 4, 1)
    layout.addWidget(widget.configure_pallet_capacity_button, 5, 0)
    layout.addWidget(widget.configure_truck_capacity_button, 5, 1)

    # La accion destructiva queda separada de las acciones operativas frecuentes.
    layout.setRowMinimumHeight(6, 8)
    layout.addWidget(widget.clear_assignments_button, 7, 0, 1, 2)


def install_compact_pallet_actions() -> None:
    """Instala una extension UI acotada para el issue #300."""

    from app.ui.pallet_composition import PalletCompositionWidget

    if getattr(PalletCompositionWidget, "_compact_actions_issue_300_installed", False):
        return

    original_install = PalletCompositionWidget._install_auto_distribution_ui

    def compact_install(self) -> None:
        original_install(self)
        _compact_batch_actions(self)

    PalletCompositionWidget._install_auto_distribution_ui = compact_install
    PalletCompositionWidget._compact_actions_issue_300_installed = True
