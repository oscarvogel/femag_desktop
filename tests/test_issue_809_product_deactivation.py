from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox, QPushButton, QTableWidget

from app.models.audit import AuditLog
from app.models.masters import Product
from app.models.security import User, UserProfile
from app.services.master_service import MasterService
from app.services.permission_service import PermissionService
from app.ui.master_abm import build_master_abm_page, master_abm_configs


def _admin(username):
    profile, _ = UserProfile.get_or_create(name="Administrador")
    return User.create(
        username=username,
        password_hash="x",
        profile=profile,
        active=True,
    )


def test_product_active_status_is_audited_without_deleting_product(db):
    product = Product.create(name="Producto baja servicio 809", unit="kg")
    service = MasterService("admin_issue809")

    service.set_product_active(product, False)

    product = Product.get_by_id(product.id)
    assert product.active is False
    assert product.name == "Producto baja servicio 809"
    audit = AuditLog.get(AuditLog.record_ref == f"Product:{product.id}")
    assert audit.action == "desactivar producto"
    assert audit.old_value == {"active": True}
    assert audit.new_value == {"active": False}

    service.set_product_active(product, True)
    assert Product.get_by_id(product.id).active is True
    assert AuditLog.select().where(
        (AuditLog.record_ref == f"Product:{product.id}")
        & (AuditLog.action == "activar producto")
    ).exists()


def test_products_abm_confirms_and_toggles_selected_product(db, monkeypatch):
    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    admin = _admin("admin_issue809_ui")
    product = Product.create(name="Producto baja UI 809", unit="kg")
    page = build_master_abm_page(
        config=master_abm_configs()["products"],
        user=admin,
        current_user=admin.username,
    )
    table = page.findChild(QTableWidget, "newProductButtonTable")
    button = page.findChild(QPushButton, "toggleProductActiveButton")
    assert table is not None
    assert button is not None
    assert button.isEnabled()

    row = next(
        index
        for index in range(table.rowCount())
        if table.item(index, 0).data(Qt.UserRole) == product.id
    )
    table.setCurrentCell(row, 0)
    app.processEvents()
    assert button.text() == "Dar de baja"

    answers = iter((QMessageBox.No, QMessageBox.Yes, QMessageBox.Yes))
    prompts = []

    def confirm(*args):
        prompts.append(args[2])
        return next(answers)

    monkeypatch.setattr(QMessageBox, "question", confirm)
    button.click()
    assert Product.get_by_id(product.id).active is True
    assert len(prompts) == 1
    assert button.text() == "Dar de baja"

    button.click()
    app.processEvents()
    assert len(prompts) == 2
    assert Product.get_by_id(product.id).active is False
    assert table.item(row, table.columnCount() - 1).text() == "Inactivo"
    assert button.text() == "Reactivar"

    button.click()
    app.processEvents()
    assert Product.get_by_id(product.id).active is True
    assert button.text() == "Dar de baja"
    assert len(prompts) == 3
