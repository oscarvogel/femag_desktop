import ast
from pathlib import Path

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


def test_ui_has_no_direct_qlabel_assignments_for_operational_feedback() -> None:
    """Issue #296: feedback must use FormFeedback, not a styled QLabel."""

    legacy_assignments: list[str] = []
    feedback_tokens = ("feedback", "warning")
    feedback_names = {"issue_label", "bulk_preview_label"}

    for path in sorted(Path("app/ui").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "QLabel"
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                name = ast.unparse(target).lower()
                leaf = name.rsplit(".", 1)[-1]
                if any(token in leaf for token in feedback_tokens) or leaf in feedback_names:
                    legacy_assignments.append(f"{path}:{node.lineno} ({name})")

    assert legacy_assignments == []


def test_known_inline_feedback_inventory_uses_form_feedback() -> None:
    inventory = {
        "app/ui/desktop_app.py": (
            "accountStatementRecipientsFeedback",
            "loadOrderFeedback",
            "legacyDbfImportFeedback",
            "loadOrderPalletDialogFeedback",
        ),
        "app/ui/login_window.py": ("loginFeedback",),
        "app/ui/user_management.py": ("usersFeedback", "permissionsFeedback"),
        "app/ui/transport_setup_extension.py": (
            "transportSetupFeedback",
            "transportSetupTruckWarning",
            "transportSetupDriverWarning",
        ),
        "app/ui/pallet_composition.py": (
            "palletCompositionIssues",
            "bulkPalletAssignmentPreview",
        ),
        "app/ui/master_abm.py": (
            "clientAbmFeedback",
            "clientSearchFeedback",
            "clientPlacesSearchFeedback",
            "clientPlacesFeedback",
        ),
    }

    for filename, object_names in inventory.items():
        source = Path(filename).read_text(encoding="utf-8")
        for object_name in object_names:
            assert f'FormFeedback("{object_name}")' in source, (filename, object_name)
