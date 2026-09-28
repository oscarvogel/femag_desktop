from decimal import Decimal

from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton, QTableWidget

from app.models.masters import Product, ProductCostHistory
from app.models.security import User, UserProfile
from app.ui.master_abm import ProductCostDialog, build_master_abm_page, master_abm_configs


def _user(username, profile_name):
    profile, _ = UserProfile.get_or_create(name=profile_name)
    return User.create(username=username, password_hash="x", profile=profile, active=True)


def test_product_cost_dialog_is_admin_only(db):
    product = Product.create(name="Producto costo UI", unit="kg")
    operator = _user("operador-costo-ui", "Administración")

    try:
        ProductCostDialog(user=operator, product_id=product.id, current_user=operator.username)
        assert False, "Un usuario no administrador no debe abrir costos."
    except PermissionError:
        pass


def test_admin_can_update_cost_and_see_history(db):
    app = QApplication.instance() or QApplication([])
    product = Product.create(name="Producto costo admin", unit="kg")
    admin = _user("admin-costo-ui", "Administrador")

    dialog = ProductCostDialog(user=admin, product_id=product.id, current_user=admin.username)
    dialog.findChild(QLineEdit, "productCostInput").setText("1180,50")
    dialog.findChild(QLineEdit, "productCostReasonInput").setText("Actualización mensual")
    dialog.findChild(QPushButton, "saveProductCostButton").click()
    app.processEvents()

    assert Product.get_by_id(product.id).costo_unitario == Decimal("1180.5000")
    history = ProductCostHistory.get(ProductCostHistory.product == product)
    assert history.changed_by == admin.username
    assert history.reason == "Actualización mensual"

    reopened = ProductCostDialog(user=admin, product_id=product.id, current_user=admin.username)
    table = reopened.findChild(QTableWidget, "productCostHistoryTable")
    assert table.rowCount() == 1
    assert table.item(0, 2).text() == "1180.5000"


def test_cost_button_exists_only_for_admin(db):
    app = QApplication.instance() or QApplication([])
    admin = _user("admin-cost-button", "Administrador")
    operator = _user("operator-cost-button", "Administración")
    config = master_abm_configs()["products"]

    admin_page = build_master_abm_page(config=config, user=admin, current_user=admin.username)
    operator_page = build_master_abm_page(config=config, user=operator, current_user=operator.username)
    app.processEvents()

    assert admin_page.findChild(QPushButton, "productCostButton") is not None
    assert operator_page.findChild(QPushButton, "productCostButton") is None
