from pathlib import Path


def test_requirements_declares_pyqt5libs_dependency():
    requirements = Path("requirements.txt").read_text(encoding="utf-8")

    assert "pyqt5libs @ git+https://github.com/oscarvogel/pyqt5libs.git@master" in requirements
    assert "PyQt5" in requirements
    assert "PySide6" not in requirements


def test_ui_framework_reports_pyqt5libs_target_without_importing_it():
    from app.ui.framework import get_ui_framework

    framework = get_ui_framework()

    assert framework.name == "pyqt5libs"
    assert framework.qt_binding == "PyQt5"
    assert framework.required_components == ("ABM", "tables", "buttons", "forms", "views")


def test_abm_view_spec_prepares_future_pyqt5libs_views():
    from app.ui.abm import ABMViewSpec, build_client_abm_spec

    spec = build_client_abm_spec()

    assert isinstance(spec, ABMViewSpec)
    assert spec.library == "pyqt5libs"
    assert spec.entity == "clientes"
    assert spec.title == "Clientes"
    assert spec.permissions_menu == "Maestros"
    assert "name" in spec.fields
    assert "cuit" in spec.fields
    assert spec.actions == ("ver", "crear", "modificar")
