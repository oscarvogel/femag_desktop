"""El seed demo de FEMAG Web crea datos sinteticos e idempotentes (#803)."""

from app.models.load_orders import LoadOrder, LoadOrderProduct
from app.models.security import User
from app.services.auth_service import AuthService

PASSWORD = "demo-web-pass-123"


def _configure(monkeypatch, tmp_path):
    monkeypatch.setenv("FEMAG_DB_ENGINE", "sqlite")
    monkeypatch.setenv("FEMAG_DEMO", "1")
    monkeypatch.setenv("FEMAG_SECURE_CONFIG", "0")
    monkeypatch.setenv("FEMAG_SQLITE_PATH", str(tmp_path / "demo-web.sqlite3"))
    monkeypatch.setenv("FEMAG_WEB_DEMO_ADMIN_USER", "demo")
    monkeypatch.setenv("FEMAG_WEB_DEMO_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("FEMAG_WEB_DEMO_ORDER_TOKEN", "demo-web-order-2026")
    monkeypatch.setenv("FEMAG_WEB_PUBLIC_URL", "http://localhost:8080")


def test_seed_is_idempotent_and_creates_login_and_order(db, monkeypatch, tmp_path):
    from scripts import seed_webapp_demo

    _configure(monkeypatch, tmp_path)

    assert seed_webapp_demo.main() == 0
    assert seed_webapp_demo.main() == 0

    user = User.get_or_none(User.username == "demo")
    assert user is not None
    assert AuthService().authenticate("demo", PASSWORD) is not None

    order = LoadOrder.get_or_none(LoadOrder.qr_token == "demo-web-order-2026")
    assert order is not None
    assert order.order_number == 990001
    assert LoadOrderProduct.select().where(LoadOrderProduct.order == order).count() == 2


def test_seed_refuses_to_run_without_demo_flag(db, monkeypatch, tmp_path):
    from scripts import seed_webapp_demo

    _configure(monkeypatch, tmp_path)
    monkeypatch.delenv("FEMAG_DEMO")
    monkeypatch.delenv("FEMAG_WEB_ALLOW_DEMO_SEED", raising=False)

    assert seed_webapp_demo.main() == 1
