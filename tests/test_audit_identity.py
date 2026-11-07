from app.models.audit import AuditLog
from app.models.security import User, UserProfile
from app.services.audit_identity_service import backfill_audit_user_ids
from app.services.audit_query_service import AuditQueryService
from app.services.audit_service import AuditService


def _user(username: str) -> User:
    profile, _ = UserProfile.get_or_create(name="Administrador")
    return User.create(
        username=username,
        password_hash="hash-de-prueba",
        profile=profile,
        active=True,
    )


def test_audit_service_sets_user_id_and_keeps_snapshot(db):
    gabriela = _user("gabriela")

    row = AuditService().record(user="GABRIELA", module="Clientes", action="crear")

    assert row.user_id == gabriela.id
    assert row.user == "GABRIELA"


def test_audit_service_maps_explicit_alias(db):
    gabriela = _user("gabriela")

    row = AuditService().record(user="gabreila", module="Clientes", action="crear")

    assert row.user_id == gabriela.id
    assert row.user == "gabreila"


def test_audit_service_leaves_dubious_identity_unattributed(db):
    _user("gabriela")

    row = AuditService().record(
        user="gabriela2026",
        module="Sistema",
        action="login fallido",
    )

    assert row.user_id is None
    assert row.user == "gabriela2026"


def test_backfill_maps_history_and_is_idempotent(db):
    gabriela = _user("gabriela")
    cristina = _user("cristina")
    AuditLog.create(user="gabriela", module="Prueba", action="a")
    AuditLog.create(user="GABRIELA", module="Prueba", action="a")
    AuditLog.create(user="gabreila", module="Prueba", action="a")
    AuditLog.create(user="CRISTINA", module="Prueba", action="a")
    AuditLog.create(user="gabriela2026", module="Prueba", action="a")
    AuditLog.create(user=None, module="Prueba", action="a")

    first = backfill_audit_user_ids()

    assert first == {"updated": 4, "unattributed": 2}
    assert AuditLog.select().where(AuditLog.user_id == gabriela.id).count() == 3
    assert AuditLog.select().where(AuditLog.user_id == cristina.id).count() == 1
    assert AuditLog.select().where(AuditLog.user_id.is_null(True)).count() == 2

    second = backfill_audit_user_ids()

    assert second == {"updated": 0, "unattributed": 2}


def test_audit_query_filter_includes_aliases_and_unattributed(db):
    _user("gabriela")
    _user("cristina")
    AuditLog.create(user="gabriela", module="Prueba", action="a")
    AuditLog.create(user="GABRIELA", module="Prueba", action="a")
    AuditLog.create(user="gabreila", module="Prueba", action="a")
    AuditLog.create(user="gabriela2026", module="Prueba", action="a")
    AuditLog.create(user=None, module="Prueba", action="a")
    backfill_audit_user_ids()

    service = AuditQueryService()

    assert len(service.search(user="gabriela")) == 3
    assert len(service.search(user="Sin atribuir")) == 1
    assert len(service.search(user="Sistema")) == 1

    options = service.filter_options()
    assert "gabriela" in options["users"]
    assert "cristina" in options["users"]
    assert "Sin atribuir" in options["users"]
    assert "Sistema" in options["users"]


def test_audit_query_page_displays_canonical_username(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.audit_query_page import AuditQueryPage

    gabriela = _user("gabriela")
    AuditLog.create(
        user="GABRIELA",
        user_id=gabriela.id,
        module="Clientes",
        action="crear",
    )

    app = QApplication.instance() or QApplication([])
    page = AuditQueryPage()
    app.processEvents()

    assert page.table.item(0, 3).text() == "gabriela"


def test_webapp_audit_record_sets_user_id(db):
    from webapp import audit

    gabriela = _user("gabriela")

    audit.record(user="gabriela", module="Sistema", action="salida")

    row = AuditLog.get()
    assert row.user_id == gabriela.id
    assert row.user == "gabriela"
