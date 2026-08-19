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


def test_layout_owned_feedback_remains_inline_and_does_not_auto_dismiss():
    from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget

    from app.ui.form_feedback import FormFeedback

    app = QApplication.instance() or QApplication([])
    host = QWidget()
    layout = QVBoxLayout(host)
    feedback = FormFeedback("inlineFeedback")
    layout.addWidget(feedback)
    host.show()
    app.processEvents()

    feedback.show_info("Seleccione un cliente.")
    app.processEvents()

    assert feedback.parentWidget() is host
    assert feedback.is_floating_toast is False
    assert feedback.isWindow() is False
    assert feedback.isVisible() is True
    assert feedback._dismiss_timer.isActive() is False

    host.close()
