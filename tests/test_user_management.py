import pytest


def _seed_profiles():
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()


def test_user_lifecycle_passwords_and_last_admin_protection(db):
    from app.models.audit import AuditLog
    from app.services.auth_service import AuthService

    _seed_profiles()
    auth = AuthService()
    admin = auth.create_initial_admin("admin", "secreto", display_name="Administrador")
    secretary = auth.create_user(
        "secretaria",
        "clave",
        "Secretaria",
        display_name="Ana Secretaría",
        actor=admin,
    )

    assert secretary.display_name == "Ana Secretaría"
    assert secretary.profile.name == "Secretaría"
    assert auth.authenticate("secretaria", "clave") == secretary

    auth.set_active(secretary, False, actor=admin)
    assert auth.authenticate("secretaria", "clave") is None
    auth.set_active(secretary, True, actor=admin)

    auth.change_password(secretary, "nueva", "nueva", actor=secretary)
    assert auth.authenticate("secretaria", "clave") is None
    assert auth.authenticate("secretaria", "nueva") == secretary

    auth.change_password(secretary, "reseteada", "reseteada", actor=admin, reset=True)
    assert auth.authenticate("secretaria", "reseteada") == secretary

    with pytest.raises(ValueError, match="último administrador"):
        auth.set_active(admin, False, actor=admin)

    actions = [row.action for row in AuditLog.select().order_by(AuditLog.id)]
    assert "crear usuario" in actions
    assert "cambiar contraseña" in actions
    assert "restablecer contraseña" in actions
    assert "habilitar usuario" in actions
    assert "deshabilitar usuario" in actions


def test_seed_defaults_consolidates_legacy_profile_names_and_is_idempotent(db):
    from app.models.security import MenuItem, Permission, User, UserProfile
    from app.services.permission_service import PermissionService

    service = PermissionService()
    service.seed_defaults()
    legacy_profile = UserProfile.create(name="Administracion")
    UserProfile.create(name="Secretaria")
    legacy_user = User.create(
        username="legacy",
        password_hash="legacy-hash",
        profile=legacy_profile,
        active=True,
    )
    menu_item = MenuItem.get(MenuItem.title == "Clientes")
    Permission.create(
        profile=legacy_profile,
        menu_item=menu_item,
        action="ver",
        allowed=False,
    )

    service.seed_defaults()
    service.seed_defaults()

    assert set(UserProfile.select().order_by(UserProfile.name).tuples()) == {
        ("Administrador",),
        ("Administración",),
        ("Secretaría",),
        ("Solo consulta",),
    }
    legacy_user = User.get_by_id(legacy_user.id)
    assert legacy_user.profile.name == "Administración"
    assert Permission.select().where(Permission.profile == legacy_profile).count() == 0
    assert (
        Permission.select()
        .where(
            (Permission.profile == legacy_user.profile)
            & (Permission.menu_item == menu_item)
            & (Permission.action == "ver")
        )
        .get()
        .allowed
        is True
    )


def test_admin_can_edit_permissions_and_non_admin_cannot(db):
    from app.models.security import MenuItem
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService

    _seed_profiles()
    auth = AuthService()
    admin = auth.create_initial_admin("admin", "secreto")
    viewer = auth.create_user("viewer", "clave", "Solo consulta")
    profile = viewer.profile
    menu_item = MenuItem.get(MenuItem.title == "Clientes")

    service = PermissionService()
    assert service.update_profile_permissions(
        admin,
        profile,
        {(menu_item.id, "crear"): True},
    ) == 1
    assert service.has_permission(viewer, "Maestros", "crear", "Clientes")

    with pytest.raises(PermissionError, match="administrador"):
        service.update_profile_permissions(viewer, profile, {(menu_item.id, "crear"): False})


def test_initial_admin_cannot_be_created_twice_and_malformed_hash_is_rejected(db):
    from app.services.auth_service import AuthService

    _seed_profiles()
    auth = AuthService()
    auth.create_initial_admin("admin", "secreto")
    with pytest.raises(ValueError, match="Ya existe"):
        auth.create_initial_admin("otro", "secreto")

    user = auth.authenticate("admin", "incorrecta")
    assert user is None


def test_user_management_page_exposes_users_and_permission_matrix(db):
    from PyQt5.QtWidgets import QApplication, QTableWidget, QTabWidget

    from app.services.auth_service import AuthService
    from app.ui.user_management import UserManagementPage

    _seed_profiles()
    admin = AuthService().create_initial_admin("admin", "secreto")
    app = QApplication.instance() or QApplication([])
    page = UserManagementPage(user=admin)

    assert app is not None
    assert page.findChild(QTabWidget, "userManagementTabs") is not None
    assert page.findChild(QTableWidget, "usersTable") is not None
    assert page.findChild(QTableWidget, "permissionsTable") is not None
    page.close()
