def test_aviso_service_count_unread_initially_zero(db):
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.services.aviso_service import AvisoService

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_aviso_infra", password_hash="x", profile=profile)
    svc = AvisoService()
    assert svc.count_unread(user) == 0
    assert svc.get_for_user(user) == []
