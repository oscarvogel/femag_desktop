from app.models.security import User, UserProfile
from app.services.auth_service import AuthService
from app.services.managerial_access_service import ManagerialAccessService
from app.services.permission_service import PermissionService


def _create_user(username: str, password: str, profile_name: str) -> User:
    return AuthService().create_user(username, password, profile_name)


def test_managerial_access_accepts_administrator_credentials(db):
    PermissionService().seed_defaults()
    requester = _create_user("secretaria_requester", "secret", "Secretaría")
    admin = _create_user("admin_authorizer", "adminpass", "Administrador")

    authorized = ManagerialAccessService().authorize(
        admin.username,
        "adminpass",
        requested_by=requester,
    )

    assert authorized is not None
    assert authorized.id == admin.id


def test_managerial_access_accepts_manager_credentials(db):
    PermissionService().seed_defaults()
    requester = _create_user("admin_requester", "secret", "Administración")
    manager = _create_user("manager_authorizer", "managerpass", "Gerencia")

    authorized = ManagerialAccessService().authorize(
        manager.username,
        "managerpass",
        requested_by=requester,
    )

    assert authorized is not None
    assert authorized.id == manager.id


def test_managerial_access_rejects_user_without_permission(db):
    PermissionService().seed_defaults()
    requester = _create_user("requester", "secret", "Secretaría")
    regular = _create_user("regular_authorizer", "regularpass", "Administración")

    authorized = ManagerialAccessService().authorize(
        regular.username,
        "regularpass",
        requested_by=requester,
    )

    assert authorized is None


def test_managerial_access_rejects_wrong_password(db):
    PermissionService().seed_defaults()
    requester = _create_user("requester_wrong", "secret", "Secretaría")
    admin = _create_user("admin_wrong", "adminpass", "Administrador")

    authorized = ManagerialAccessService().authorize(
        admin.username,
        "incorrecta",
        requested_by=requester,
    )

    assert authorized is None
