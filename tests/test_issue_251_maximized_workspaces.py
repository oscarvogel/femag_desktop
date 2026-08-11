import os
import subprocess
import sys
import textwrap


def test_workspace_window_policy_maximizes_main_and_operational_dialogs_only():
    code = textwrap.dedent(
        """
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication, QDialog, QMainWindow

        from app.ui.window_policy import install_workspace_window_policy

        app = QApplication.instance() or QApplication([])
        install_workspace_window_policy()

        main_window = QMainWindow()
        main_window.show()
        app.processEvents()
        assert main_window.isMaximized()

        workspace = QDialog()
        workspace.setWindowTitle("Preparación de pallets")
        QTimer.singleShot(0, workspace.accept)
        workspace.exec_()
        assert workspace.isMaximized()

        compact = QDialog()
        compact.setWindowTitle("Cambiar mi contraseña")
        QTimer.singleShot(0, compact.accept)
        compact.exec_()
        assert not compact.isMaximized()
        """
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_workspace_dialog_title_matching_is_scoped_to_large_workspaces():
    from app.ui.window_policy import _is_workspace_dialog_title

    assert _is_workspace_dialog_title("Preparación de pallets")
    assert _is_workspace_dialog_title("Orden de carga OC-000123")
    assert not _is_workspace_dialog_title("Cambiar mi contraseña")
    assert not _is_workspace_dialog_title("Confirmar anulación")
