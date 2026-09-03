import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import _master_data, _valid_order_payload


def _admin_user(username: str):
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    return User.create(username=username, password_hash="x", profile=profile)


def _table_contains_record_id(table, record_id: int) -> bool:
    from PyQt5.QtCore import Qt

    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is not None and item.data(Qt.UserRole) == record_id:
            return True
    return False


def test_load_orders_refresh_sees_order_created_by_another_station(db):
    from PyQt5.QtWidgets import QApplication, QTableWidget

    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.multi_station_refresh_extension import install_multi_station_refresh_extension

    install_multi_station_refresh_extension()
    user = _admin_user("station_b")
    data = _master_data()
    app = QApplication.instance() or QApplication([])

    # Puesto B abre FEMAG antes de que exista la orden.
    window = FemagDesktopWindow(user=user, demo_mode=True)
    window._navigate_to_route("load_orders")
    window.show()
    app.processEvents()
    table = window.findChild(QTableWidget, "loadOrdersTable")
    assert table is not None

    # Puesto A confirma una orden contra la misma base.
    created = LoadOrderService(current_user="station_a").create_order(
        **_valid_order_payload(data)
    )
    assert not _table_contains_record_id(table, created.id)

    # Sin relogin ni recrear la ventana, B vuelve/refresca la ruta.
    window._refresh_route("load_orders")
    app.processEvents()
    assert _table_contains_record_id(table, created.id)

    timer = window._multi_station_refresh_timer
    assert timer.isActive()
    assert timer.interval() == 10_000
    window.close()


def test_master_page_refresh_sees_product_modified_by_another_station(db):
    from PyQt5.QtWidgets import QApplication, QTableWidget

    from app.models.masters import Product
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.multi_station_refresh_extension import install_multi_station_refresh_extension

    install_multi_station_refresh_extension()
    user = _admin_user("station_products")
    data = _master_data()
    product = data["product"]
    app = QApplication.instance() or QApplication([])

    window = FemagDesktopWindow(user=user, demo_mode=True)
    window._navigate_to_route("products")
    window.show()
    app.processEvents()

    product.name = "Producto actualizado desde otra estación"
    product.save()
    assert Product.get_by_id(product.id).name == product.name

    window._refresh_route("products")
    app.processEvents()
    table = window.findChild(QTableWidget, "newProductButtonTable")
    assert table is not None
    visible_names = [
        table.item(row, 0).text()
        for row in range(table.rowCount())
        if table.item(row, 0) is not None
    ]
    assert "Producto actualizado desde otra estación" in visible_names
    window.close()


def test_new_load_order_product_dialog_reads_latest_price(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Client, Product
    from app.ui.desktop_app import LoadOrderProductDialog

    data = _master_data()
    client = Client.get_by_id(data["client"].id)
    product = Product.get_by_id(data["product"].id)
    client.lista_precios = 1
    client.save()
    product.precio_neto_base = 111.0
    product.precio_lista_1 = 111.0
    product.save()

    # Otra estación cambia el precio mientras esta sesión de FEMAG sigue abierta.
    Product.update(precio_lista_1=987.65).where(Product.id == product.id).execute()

    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderProductDialog(client=Client.get_by_id(client.id))
    index = dialog.product_combo.findData(product.id)
    assert index >= 0
    dialog.product_combo.setCurrentIndex(index)
    app.processEvents()

    assert dialog.precio_input.value() == 987.65
    dialog.close()
