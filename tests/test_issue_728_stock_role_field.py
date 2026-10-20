"""#728: el ABM de productos que corre en la app tiene que permitir marcar
una materia prima.

El diálogo que se abre en producción no es ``master_abm.ProductEntryDialog``:
``app/ui/product_code_extension.py`` lo reemplaza por ``ProductCodeEntryDialog``
para agregar el campo "Código", y esa reescritura reconstruye el formulario
entero. Cuando #656 agrego "Rol en el stock" al ABM base, la extension no se
actualizo y el campo quedo inalcanzable: era imposible marcar un producto como
materia prima, la pantalla de ingreso de big bags no tenia nada que mostrar y
el libro de stock no tenia ninguna entrada.

Estos tests apuntan al dialogo **extendido** (el que corre en la app), no al
base: si el base esta bien y el extendido no, el bug esta vivo.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _dialogo_real():
    """El dialogo de Producto tal como lo abre la app."""
    from app.ui.master_abm import master_abm_configs

    return master_abm_configs()["products"].dialog_class


def test_el_dialogo_de_la_app_tiene_el_campo_rol_en_el_stock(db):
    from PyQt5.QtWidgets import QComboBox

    app = _app()
    dialogo = _dialogo_real()(current_user="issue728")

    combo = dialogo.findChild(QComboBox, "productStockRoleInput")

    assert combo is not None, "el ABM de productos no tiene el campo Rol en el stock"
    assert combo.findData("materia_prima") >= 0
    assert combo.findData("terminado") >= 0

    app.processEvents()


def test_el_rol_materia_prima_aclara_que_el_peso_es_el_del_big_bag(db):
    from PyQt5.QtWidgets import QComboBox, QLabel

    app = _app()
    dialogo = _dialogo_real()(current_user="issue728")

    combo = dialogo.findChild(QComboBox, "productStockRoleInput")
    combo.setCurrentIndex(combo.findData("materia_prima"))
    app.processEvents()

    ayuda = dialogo.findChild(QLabel, "subheading")
    assert ayuda is not None
    assert "big bag" in ayuda.text().lower()
    assert "peso unitario" in ayuda.text().lower()


def test_guardar_una_materia_prima_persiste_el_rol_y_lo_muestra_el_listado(db):
    from PyQt5.QtWidgets import QComboBox, QDoubleSpinBox, QLineEdit, QPushButton

    from app.models.masters import Product
    from app.ui.master_abm import master_abm_configs

    app = _app()
    dialogo = _dialogo_real()(current_user="issue728")

    dialogo.findChild(QLineEdit, "productCodeInput").setText("ALM-100")
    dialogo.findChild(QLineEdit, "productNameInput").setText("ALMIDON MAIZ BIG BAG")
    dialogo.findChild(QLineEdit, "productUnitInput").setText("kg")
    dialogo.findChild(QDoubleSpinBox, "productWeightKgInput").setValue(1000.0)

    combo = dialogo.findChild(QComboBox, "productStockRoleInput")
    combo.setCurrentIndex(combo.findData("materia_prima"))
    app.processEvents()

    dialogo.findChild(QPushButton, "saveProductButton").click()
    app.processEvents()

    guardado = Product.get(Product.name == "ALMIDON MAIZ BIG BAG")
    assert guardado.stock_role == "materia_prima"

    config = master_abm_configs()["products"]
    assert "Rol en el stock" in config.columns
    fila = next(fila for fila in config.rows_fn() if fila[2] == "ALMIDON MAIZ BIG BAG")
    # La fila arranca con el id, que no es una columna visible: las columnas
    # que ve el operador son row[1:], igual que arma la tabla el ABM.
    valores = fila[1:]
    indice = config.columns.index("Rol en el stock")
    assert valores[indice] == "Materia prima"


def test_editar_un_producto_carga_su_rol_actual(db):
    from PyQt5.QtWidgets import QComboBox

    from app.models.masters import Product

    app = _app()
    producto = Product.create(
        codigo="ALM-200",
        name="ALMIDON MANDIOCA BIG BAG",
        unit="kg",
        peso_unitario_kg=1000,
        product_kind="producto",
        stock_role="materia_prima",
        active=True,
    )

    dialogo = _dialogo_real()(current_user="issue728", record_id=producto.id)
    combo = dialogo.findChild(QComboBox, "productStockRoleInput")

    assert combo.currentData() == "materia_prima"

    app.processEvents()


def test_un_producto_sin_rol_se_conserva_como_producto_terminado_al_editarlo(db):
    from PyQt5.QtWidgets import QComboBox, QLineEdit, QPushButton

    from app.models.masters import Product

    app = _app()
    producto = Product.create(
        codigo="LEG-300",
        name="BOLSAS DE FECULA NATIVA",
        unit="unidad",
        peso_unitario_kg=25,
        product_kind="producto",
        active=True,
    )

    dialogo = _dialogo_real()(current_user="issue728", record_id=producto.id)
    combo = dialogo.findChild(QComboBox, "productStockRoleInput")

    assert combo.currentData() == "terminado"

    dialogo.findChild(QLineEdit, "productNameInput").setText("BOLSAS DE FECULA NATIVA")
    dialogo.findChild(QPushButton, "saveProductButton").click()
    app.processEvents()

    assert Product.get_by_id(producto.id).stock_role == "terminado"


def test_la_materia_prima_marcada_desde_el_abm_aparece_en_el_ingreso_de_big_bags(db):
    """El circuito completo: marcar la materia prima en el ABM la hace
    aparecer en la pantalla de Ingreso de materia prima, que antes quedaba
    vacia porque no habia ningun producto con ese rol."""
    from PyQt5.QtWidgets import QComboBox, QDoubleSpinBox, QLineEdit, QPushButton

    from app.ui.raw_material_intake import RawMaterialIntakePage

    app = _app()
    dialogo = _dialogo_real()(current_user="issue728")

    dialogo.findChild(QLineEdit, "productCodeInput").setText("ALM-400")
    dialogo.findChild(QLineEdit, "productNameInput").setText("ALMIDON ARROZ BIG BAG")
    dialogo.findChild(QLineEdit, "productUnitInput").setText("kg")
    dialogo.findChild(QDoubleSpinBox, "productWeightKgInput").setValue(1000.0)

    combo = dialogo.findChild(QComboBox, "productStockRoleInput")
    combo.setCurrentIndex(combo.findData("materia_prima"))
    app.processEvents()

    dialogo.findChild(QPushButton, "saveProductButton").click()
    app.processEvents()

    pagina = RawMaterialIntakePage(current_username="issue728")
    app.processEvents()

    nombres = [
        pagina.product_combo.itemText(indice)
        for indice in range(pagina.product_combo.count())
    ]

    assert "ALMIDON ARROZ BIG BAG" in nombres
