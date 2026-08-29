import os
os.environ["QT_QPA_PLATFORM"]="offscreen"

def test_aviso_center_shows_empty_label_when_no_avisos(db):
    from PyQt5.QtWidgets import QApplication, QLabel, QTableWidget
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.aviso_center import AvisoCenterPage
    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_empty_center", password_hash="x", profile=profile)
    page = AvisoCenterPage(user=user, on_navigate=lambda *a, **k: None)
    app.processEvents()
    assert page.findChild(QLabel, "avisoCenterEmptyLabel").text() != ""
    assert page.table.isHidden()


def test_aviso_center_reactivate_brings_persistent_avisos_back(db):
    from PyQt5.QtWidgets import QApplication, QPushButton
    from app.models.masters import Product, TipoIVA
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.aviso_center import AvisoCenterPage
    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    iva = TipoIVA.iva_default()
    Product.create(name="Prod Rev", unit="kg", review_required=True, peso_unitario_kg=1, tipo_iva=iva)
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_reactivate", password_hash="x", profile=profile)
    page = AvisoCenterPage(user=user, on_navigate=lambda *a, **k: None)
    app.processEvents()
    # mark all read
    page.service.mark_all_read(user)
    page.refresh()
    assert page.table.rowCount() == 0
    # reactivate
    btn = page.findChild(QPushButton, "avisoCenterReactivateButton")
    assert btn is not None
    btn.click()
    app.processEvents()
    assert page.table.rowCount() == 1
    assert page.table.item(0, 1).text() == "producto_revision"