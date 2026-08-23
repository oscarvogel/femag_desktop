import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_product_code_is_editable_unique_and_does_not_change_primary_key(db):
    from app.models.masters import Product
    from app.services.master_service import MasterService

    service = MasterService(current_user="issue319")
    product = service.create_product("Almidón mandioca", "kg", codigo="100")
    original_id = product.id

    assert product.codigo == "100"

    with pytest.raises(ValueError, match="Ya existe un artículo con el código"):
        service.create_product("Otro almidón", "kg", codigo=" 100 ")

    service.update_product(product, product.name, product.unit, codigo="200-A")
    product = Product.get_by_id(original_id)

    assert product.id == original_id
    assert product.codigo == "200-A"


def test_legacy_products_can_remain_without_code_until_manually_edited(db):
    from app.models.masters import Product

    legacy = Product.create(name="Producto legacy sin código", unit="kg", codigo=None)

    assert legacy.codigo is None


def test_product_master_config_exposes_code_column_search_and_required_editor(db):
    from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton

    from app.models.masters import Product
    from app.ui.master_abm import master_abm_configs

    app = QApplication.instance() or QApplication([])
    config = master_abm_configs()["products"]

    assert config.columns[0] == "Código"
    assert "código" in config.search_placeholder.lower()

    dialog = config.dialog_class(current_user="issue319")
    code_input = dialog.findChild(QLineEdit, "productCodeInput")
    assert code_input is not None

    dialog.findChild(QLineEdit, "productNameInput").setText("Almidón maíz UI")
    dialog.findChild(QLineEdit, "productUnitInput").setText("kg")
    dialog.findChild(QPushButton, "saveProductButton").click()
    app.processEvents()
    assert Product.get_or_none(Product.name == "Almidón maíz UI") is None

    code_input.setText("210")
    dialog.findChild(QPushButton, "saveProductButton").click()
    app.processEvents()

    stored = Product.get(Product.name == "Almidón maíz UI")
    assert stored.codigo == "210"


def test_product_master_rows_are_searchable_by_code_or_name(db):
    from app.services.master_service import MasterService
    from app.ui.master_abm import filter_and_sort_master_rows, master_abm_configs

    service = MasterService(current_user="issue319")
    service.create_product("Almidón mandioca premium", "kg", codigo="115-M")
    service.create_product("Almidón maíz premium", "kg", codigo="215-Z")

    rows = master_abm_configs()["products"].rows_fn()

    by_code = filter_and_sort_master_rows(rows, query="115-M")
    by_name = filter_and_sort_master_rows(rows, query="maiz premium")

    assert len(by_code) == 1
    assert by_code[0][1] == "115-M"
    assert len(by_name) == 1
    assert by_name[0][1] == "215-Z"


def test_operational_product_options_include_code_for_autocomplete(db):
    from app.models.masters import Product
    from app.ui import desktop_app
    from app.ui.product_code_extension import install_desktop_product_code_extension

    Product.create(
        codigo="305-X",
        name="Fécula especial",
        unit="kg",
        product_kind="producto",
        active=True,
    )
    install_desktop_product_code_extension()

    options = desktop_app._product_options()

    assert any(value == "305-X - Fécula especial" for _product_id, value in options)
