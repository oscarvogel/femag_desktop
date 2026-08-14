from PyQt5.QtWidgets import QApplication, QLineEdit

from app.ui.form_feedback import FormFeedback


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_feedback_is_collapsed_until_it_has_a_message() -> None:
    app = _app()
    feedback = FormFeedback("testFeedback")

    assert feedback.isHidden()
    assert feedback.message == ""

    feedback.show_info("Mensaje informativo")

    assert not feedback.isHidden()
    assert feedback.kind == "info"
    assert feedback.message == "Mensaje informativo"
    assert "Mensaje informativo" in feedback.text()
    assert feedback.property("feedbackKind") == "info"

    feedback.clear_message()

    assert feedback.isHidden()
    assert feedback.message == ""
    assert feedback.text() == ""
    assert app is not None


def test_feedback_supports_all_semantic_variants() -> None:
    app = _app()
    feedback = FormFeedback()
    styles = set()

    for kind in ("info", "success", "warning", "error"):
        feedback.show_message(f"Estado {kind}", kind)

        assert feedback.kind == kind
        assert feedback.message == f"Estado {kind}"
        assert feedback.property("feedbackKind") == kind
        assert feedback.styleSheet()
        assert feedback.accessibleDescription()
        styles.add(feedback.styleSheet())
    assert len(styles) == 4
    assert app is not None


def test_feedback_can_focus_the_field_that_needs_attention() -> None:
    class FocusTrackingLineEdit(QLineEdit):
        def __init__(self) -> None:
            super().__init__()
            self.focus_requested = False

        def setFocus(self, *args) -> None:
            self.focus_requested = True
            super().setFocus(*args)

    app = _app()
    field = FocusTrackingLineEdit()
    feedback = FormFeedback()

    feedback.show_warning("Complete el campo.", focus_widget=field)

    assert field.focus_requested
    assert feedback.kind == "warning"
    assert app is not None
