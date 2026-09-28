from app.models.security import User, UserProfile
from app.services.menu_service import MenuService
from app.services.permission_service import PermissionService


def _user(name, profile_name):
    profile, _ = UserProfile.get_or_create(name=profile_name)
    return User.create(username=name, password_hash="x", profile=profile, active=True)


def test_profitability_menu_is_visible_only_to_administrator(db):
    admin = _user("admin-profit-menu", "Administrador")
    operator = _user("operator-profit-menu", "Administración")
    PermissionService().seed_defaults()

    def titles(user):
        return [child.title for section in MenuService().get_menu_tree_for_user(user) for child in section.children]

    assert "Rentabilidad por producto" in titles(admin)
    assert "Rentabilidad por producto" not in titles(operator)
