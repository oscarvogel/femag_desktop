import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_parentless_feedback_is_attached_to_active_window_as_toast():
    from PyQt5.QtWidgets import QApplication, QWidget

    from app.ui.form_feedback import FormFeedback

    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.resize(640, 480)
    host.show()
    host.activateWindow()
    host.raise_()
    app.processEvents()

    feedback = FormFeedback("orphanFeedback")
    assert feedback.parentWidget() is None

    feedback.show_success("Cliente actualizado.")
    app.processEvents()

    assert feedback.parentWidget() is host
    assert feedback.is_floating_toast is True
    assert feedback.isWindow() is False
    assert feedback.isVisible() is True
    assert feedback.message == "Cliente actualizado."
    assert feedback._dismiss_timer.isActive() is True

    host.close()


def test_layout_owned_feedback_is_detached_from_layout_and_shown_as_toast():
    from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget

    from app.ui.form_feedback import FormFeedback

    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.resize(640, 480)
    layout = QVBoxLayout(host)
    container = QWidget(host)
    container_layout = QVBoxLayout(container)
    feedback = FormFeedback("inlineFeedback")
    container_layout.addWidget(feedback)
    layout.addWidget(container)
    host.show()
    app.processEvents()

    assert feedback.parentWidget() is container

    feedback.show_info("Seleccione un cliente.")
    app.processEvents()

    assert feedback.parentWidget() is host
    assert feedback.is_floating_toast is True
    assert feedback.isWindow() is False
    assert feedback.isVisible() is True
    assert feedback._dismiss_timer.isActive() is True

    host.close()


def test_feedback_inside_dialog_uses_dialog_as_toast_host():
    from PyQt5.QtWidgets import QApplication, QDialog, QVBoxLayout, QWidget

    from app.ui.form_feedback import FormFeedback

    app = QApplication.instance() or QApplication([])
    dialog = QDialog()
    dialog.resize(520, 260)
    layout = QVBoxLayout(dialog)
    form_container = QWidget(dialog)
    form_layout = QVBoxLayout(form_container)
    feedback = FormFeedback("dialogFeedback")
    form_layout.addWidget(feedback)
    layout.addWidget(form_container)
    dialog.show()
    app.processEvents()

    feedback.show_warning("Complete los datos obligatorios.")
    app.processEvents()

    assert feedback.parentWidget() is dialog
    assert feedback.is_floating_toast is True
    assert feedback.isWindow() is False
    assert feedback._dismiss_timer.isActive() is True

    dialog.close()
