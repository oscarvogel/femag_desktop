def test_default_permissions_and_sensitive_actions(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService

    permission_service = PermissionService()
    permission_service.seed_defaults()
    admin = AuthService().create_user("admin", "secreto", "Administrador")
    secretary = AuthService().create_user("secre", "clave", "Secretaria")
    viewer = AuthService().create_user("consulta", "clave", "Solo consulta")

    assert permission_service.has_permission(admin, "Sistema", "configurar")
    assert permission_service.has_permission(secretary, "Maestros", "crear")
    assert permission_service.has_permission(secretary, "Maestros", "crear", "Tipos de IVA")
    assert not permission_service.has_permission(viewer, "Maestros", "crear")
    assert permission_service.has_permission(viewer, "Maestros", "ver", "Tipos de IVA")
    assert permission_service.requires_admin_password("anular remito")
    assert not permission_service.requires_admin_password("reimprimir")


def test_login_success_and_failure_are_audited(db):
    from app.models.audit import AuditLog
    from app.services.auth_service import AuthService

    service = AuthService()
    service.create_user("admin", "secreto", "Administrador")

    assert service.authenticate("admin", "secreto").username == "admin"
    assert service.authenticate("admin", "mala") is None

    actions = [row.action for row in AuditLog.select().order_by(AuditLog.id)]
    assert actions == ["crear usuario", "login exitoso", "login fallido"]
