"""#717: el camino que ofrece migrar el esquema al entrar.

El arranque detecta que la base quedo una version atrasada, pregunta y aplica
la migracion con la credencial administrativa que el operador ingresa. La
credencial **no se guarda**: la administrativa sirve para un ALTER y no debe
quedar en disco como la de todos los dias.

``ConnectionDialog._test_and_save`` se ejercita sobre un doble en vez de
construir el QDialog: hacer ``exec_`` o ``_test_and_save`` sobre el widget real
dentro de pytest deja el proceso de Python colgado en Windows con 0xC0000409,
y el metodo bajo prueba no toca el widget para nada. Los cuatro argumentos que
importa son ``connection()``, ``_save_connection``, ``_test_and_save`` y
``accept``.
"""

from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

from app.ui import connection_dialog as connection_dialog_module
from app.ui import desktop_app


class _ConexionFalsa:
    """Lo unico que el dialogo le pide a la conexion es ``validate()``."""

    def validate(self):
        return None


class _DialogoSinWidget:
    """Ejecuta el metodo real del dialogo sin construir el widget."""

    def __init__(self, save_connection):
        self._save_connection = save_connection

    def connection(self):
        return _ConexionFalsa()

    def accept(self):
        return None

    _test_and_save = connection_dialog_module.ConnectionDialog._test_and_save


def _apagar_avisos(monkeypatch):
    """Los QMessageBox reales son modales y cuelgan el proceso."""
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "critical", lambda *_a, **_k: None)


def test_el_dialogo_de_migracion_no_guarda_la_credencial(monkeypatch):
    """La administrativa sirve para un ALTER y no debe quedar en disco."""
    QApplication.instance() or QApplication([])
    guardadas = []
    monkeypatch.setattr(
        connection_dialog_module, "save_runtime_connection", lambda c: guardadas.append(c)
    )
    monkeypatch.setattr(connection_dialog_module, "test_runtime_connection", lambda c: None)
    monkeypatch.setattr(connection_dialog_module, "prepare_runtime_schema", lambda c: None)
    _apagar_avisos(monkeypatch)

    _DialogoSinWidget(save_connection=False)._test_and_save()

    assert guardadas == [], "no debe guardar la credencial administrativa"


def test_el_dialogo_de_conexion_normal_si_guarda(monkeypatch):
    """El comportamiento de siempre, para no romper el primer ingreso."""
    QApplication.instance() or QApplication([])
    guardadas = []
    monkeypatch.setattr(
        connection_dialog_module, "save_runtime_connection", lambda c: guardadas.append(c)
    )
    monkeypatch.setattr(connection_dialog_module, "test_runtime_connection", lambda c: None)
    monkeypatch.setattr(connection_dialog_module, "prepare_runtime_schema", lambda c: None)
    _apagar_avisos(monkeypatch)

    _DialogoSinWidget(save_connection=True)._test_and_save()

    assert len(guardadas) == 1, "la conexion operativa si se guarda"


def test_ofrecer_migracion_devuelve_true_si_el_operador_acepta(monkeypatch):
    from app.config.schema import SchemaValidationError

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.Yes)
    monkeypatch.setattr(desktop_app, "load_runtime_connection", lambda: None)

    class _DialogoAceptado:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def exec_(self):
            return QDialog.Accepted

    monkeypatch.setattr(desktop_app, "ConnectionDialog", _DialogoAceptado)
    error = SchemaValidationError("Faltan columnas requeridas (carrier: address).")
    assert desktop_app._offer_schema_preparation(error) is True


def test_el_dialogo_de_migracion_no_guarda_la_conexion_que_se_le_pasa(monkeypatch):
    """El dialogo del arranque se abre con save_connection=False."""
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(desktop_app, "load_runtime_connection", lambda: None)
    capturado = {}

    class _Dialogo:
        def __init__(self, **kwargs):
            capturado.update(kwargs)

        def exec_(self):
            return QDialog.Rejected

    monkeypatch.setattr(desktop_app, "ConnectionDialog", _Dialogo)
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.Yes)

    from app.config.schema import SchemaValidationError

    desktop_app._offer_schema_preparation(SchemaValidationError("x"))
    assert capturado["save_connection"] is False


def test_ofrecer_migracion_devuelve_false_si_el_operador_dice_no(monkeypatch):
    from app.config.schema import SchemaValidationError

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.No)
    error = SchemaValidationError("Faltan columnas requeridas (carrier: address).")
    assert desktop_app._offer_schema_preparation(error) is False


def test_el_mensaje_ya_no_manda_a_un_script_de_desarrollo():
    """El mensaje anterior era un callejon sin salida para el operador."""
    import inspect

    fuente = inspect.getsource(desktop_app._prepare_database)
    assert "init_db.py" not in fuente
    assert "_offer_schema_preparation" in fuente