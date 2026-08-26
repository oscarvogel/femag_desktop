import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"


def test_aviso_center_marks_read_and_navigates(db):
    from decimal import Decimal

    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Product
    from app.models.notifications import AvisoLectura
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.aviso_center import AvisoCenterPage

    app = QApplication.instance() or QApplication([])

    PermissionService().seed_defaults()

    # Ensure at least one aviso: producto_revision visible for Administracion/Administrador
    Product.create(
        name="Prod Centro Aviso",
        unit="kg",
        peso_unitario_kg=Decimal("0.000"),
        review_required=True,
        product_kind="producto",
    )

    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_centro", password_hash="x", profile=profile)

    navigated = {}

    def on_navigate(route_key):
        navigated["route"] = route_key

    page = AvisoCenterPage(user=user, on_navigate=on_navigate)
    app.processEvents()

    assert page.table.rowCount() >= 1, "Centro de Avisos should show at least one aviso"
    # Verify 5 columns and header labels
    assert page.table.columnCount() == 5
    assert page.table.horizontalHeaderItem(0).text() == "Prioridad"
    assert page.table.horizontalHeaderItem(4).text() == "Acción"
    # Verify title label exists - Direct check: page contains QLabel "Centro de Avisos"
    from PyQt5.QtWidgets import QLabel

    found_title = any(lbl.text() == "Centro de Avisos" for lbl in page.findChildren(QLabel))
    assert found_title, "Centro de Avisos title missing"

    # Capture aviso before navigation
    from app.services.aviso_service import AvisoService

    svc = AvisoService()
    avisos_before = svc.get_for_user(user)
    assert len(avisos_before) >= 1
    first = avisos_before[0]

    # Simulate click via _on_click (cellClicked)
    page._on_click(0, 0)
    app.processEvents()

    assert "route" in navigated, "on_navigate should have been called"
    assert navigated["route"] == first.route_key

    # Should have marked read
    rec = AvisoLectura.get_or_none(
        (AvisoLectura.user == user) & (AvisoLectura.tipo == first.tipo) & (AvisoLectura.referencia_id == first.referencia_id)
    )
    assert rec is not None
    assert rec.leido_at is not None

    # After marking read, that aviso should be filtered out
    avisos_after = svc.get_for_user(user)
    assert len(avisos_after) == len(avisos_before) - 1 or all(
        not (a.tipo == first.tipo and a.referencia_id == first.referencia_id) for a in avisos_after
    )

    # Also test button navigation path via _navigate directly on second aviso if exists or via table button
    # Create a fresh page and test _navigate path if more than one aviso remains
    # Not strictly required but ensures second path works
    if avisos_after:
        navigated.clear()
        second = avisos_after[0]
        page2 = AvisoCenterPage(user=user, on_navigate=lambda r: navigated.__setitem__("route", r))
        app.processEvents()
        # directly call _navigate
        page2._navigate(second)
        assert navigated.get("route") == second.route_key
