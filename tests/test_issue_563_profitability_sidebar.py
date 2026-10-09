from app.models.security import User, UserProfile
from app.services.permission_service import PermissionService
from app.services.menu_service import set_managerial_dashboard_menu_enabled
from app.ui.menu import build_sidebar_tree_spec


def _user(name, profile_name):
    profile, _ = UserProfile.get_or_create(name=profile_name)
    return User.create(username=name, password_hash="x", profile=profile, active=True)


def _managerial_children(spec):
    node = next(item for item in spec.sections[0].items if item.title == "Dashboard Gerencial")
    return {child.title: child.route_key for child in node.children}


def test_admin_sidebar_contains_profitability_route(db):
    admin = _user("admin-sidebar-profit", "Administrador")
    PermissionService().seed_defaults()
    set_managerial_dashboard_menu_enabled(True)
    children = _managerial_children(build_sidebar_tree_spec(admin))
    assert children["Rentabilidad por producto"] == "product_profitability"


def test_non_admin_sidebar_does_not_contain_profitability(db):
    operator = _user("operator-sidebar-profit", "Administración")
    PermissionService().seed_defaults()
    set_managerial_dashboard_menu_enabled(True)
    spec = build_sidebar_tree_spec(operator)
    titles = [item.title for section in spec.sections for item in section.items]
    if "Dashboard Gerencial" in titles:
        assert "Rentabilidad por producto" not in _managerial_children(spec)
