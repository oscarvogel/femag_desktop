from app.models.security import Permission, User, UserProfile
from app.services.permission_service import PermissionService
from app.ui.menu import build_sidebar_tree_spec


def _sidebar_titles(user: User) -> list[str]:
    spec = build_sidebar_tree_spec(user)
    return [item.title for section in spec.sections for item in section.items]


def test_manager_profile_sees_only_managerial_home_defaults(db):
    service = PermissionService()
    service.seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Gerencia")
    user = User.create(username="gerencia", password_hash="x", profile=profile)

    assert service.can_view_managerial_dashboard(user)
    assert "Dashboard Gerencial" in _sidebar_titles(user)
    assert service.has_permission(user, "Inicio", "ver", "Dashboard")
    assert not service.has_permission(user, "Operaciones", "ver", "Órdenes de carga")
    assert not service.has_permission(user, "Sistema", "ver", "Usuarios")


def test_administrator_sees_managerial_dashboard(db):
    service = PermissionService()
    service.seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_managerial", password_hash="x", profile=profile)

    assert service.can_view_managerial_dashboard(user)
    assert "Dashboard Gerencial" in _sidebar_titles(user)


def test_regular_profiles_do_not_receive_managerial_dashboard_by_default(db):
    service = PermissionService()
    service.seed_defaults()

    for index, profile_name in enumerate(("Secretaría", "Administración", "Solo consulta"), start=1):
        profile = UserProfile.get(UserProfile.name == profile_name)
        user = User.create(username=f"regular_{index}", password_hash="x", profile=profile)
        assert not service.can_view_managerial_dashboard(user)
        assert "Dashboard Gerencial" not in _sidebar_titles(user)


def test_explicit_permission_can_enable_managerial_dashboard_for_other_profile(db):
    service = PermissionService()
    service.seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administración")
    user = User.create(username="administracion_autorizada", password_hash="x", profile=profile)

    permission = (
        Permission.select()
        .where(
            Permission.profile == profile,
            Permission.action == "ver",
        )
        .join_from(Permission, Permission.menu_item.rel_model)
        .where(Permission.menu_item.rel_model.title == "Dashboard Gerencial")
        .get()
    )
    permission.allowed = True
    permission.save()

    assert service.can_view_managerial_dashboard(user)
    assert "Dashboard Gerencial" in _sidebar_titles(user)
