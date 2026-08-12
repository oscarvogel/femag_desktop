from __future__ import annotations

from PyQt5.QtWidgets import QDialog, QMainWindow


_WORKSPACE_DIALOG_TITLES = (
    "preparación de pallets",
    "preparacion de pallets",
    "orden de carga",
)
_installed = False
_original_main_window_show = None
_original_dialog_exec = None


def _is_workspace_dialog_title(title: str) -> bool:
    normalized = (title or "").strip().casefold()
    return any(token in normalized for token in _WORKSPACE_DIALOG_TITLES)


def install_workspace_window_policy() -> None:
    """Maximize FEMAG workspaces without affecting compact utility dialogs."""
    global _installed, _original_main_window_show, _original_dialog_exec
    if _installed:
        return

    _original_main_window_show = QMainWindow.show
    _original_dialog_exec = QDialog.exec_

    def _show_main_window_maximized(window: QMainWindow) -> None:
        window.showMaximized()

    def _exec_dialog(dialog: QDialog) -> int:
        if _is_workspace_dialog_title(dialog.windowTitle()):
            dialog.showMaximized()
        return _original_dialog_exec(dialog)

    QMainWindow.show = _show_main_window_maximized
    QDialog.exec_ = _exec_dialog
    _installed = True
