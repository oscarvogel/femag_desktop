from decimal import Decimal

import pytest

from app.models.masters import Product, ProductCostHistory, TipoIVA
from app.models.security import User, UserProfile
from app.services.master_service import MasterService


def _user(name, profile_name):
    profile, _ = UserProfile.get_or_create(name=profile_name)
    return User.create(username=name, password_hash="x", profile=profile, active=True)


def test_product_cost_starts_unknown(db):
    product = Product.create(name="Fécula costo desconocido", unit="kg", tipo_iva=TipoIVA.iva_default())
    assert product.costo_unitario is None


def test_only_administrator_can_change_product_cost(db):
    product = Product.create(name="Fécula protegida", unit="kg", tipo_iva=TipoIVA.iva_default())
    operator = _user("operador-costo", "Administración")

    with pytest.raises(PermissionError):
        MasterService(operator.username).update_product_cost(product, "123.45", actor=operator)

    assert Product.get_by_id(product.id).costo_unitario is None
    assert ProductCostHistory.select().count() == 0


def test_admin_cost_change_is_historical_and_audited(db):
    product = Product.create(name="Fécula histórica", unit="kg", tipo_iva=TipoIVA.iva_default())
    admin = _user("admin-costo", "Administrador")
    service = MasterService(admin.username)

    service.update_product_cost(product, "100,125", actor=admin, reason="Costo inicial")
    service.update_product_cost(product, "120.50", actor=admin, reason="Nueva compra")

    product = Product.get_by_id(product.id)
    history = list(ProductCostHistory.select().where(ProductCostHistory.product == product).order_by(ProductCostHistory.id))
    assert product.costo_unitario == Decimal("120.5000")
    assert [(row.previous_cost, row.new_cost) for row in history] == [
        (None, Decimal("100.1250")),
        (Decimal("100.1250"), Decimal("120.5000")),
    ]
    assert [row.changed_by for row in history] == ["admin-costo", "admin-costo"]


def test_runtime_schema_adds_nullable_cost_without_backfill(db):
    from app.config.schema import ensure_runtime_schema

    product = Product.create(name="Producto legacy sin costo", unit="kg", tipo_iva=TipoIVA.iva_default())
    db.execute_sql("ALTER TABLE product DROP COLUMN costo_unitario")

    ensure_runtime_schema(db)

    columns = {column.name: column for column in db.get_columns("product")}
    assert "costo_unitario" in columns
    assert columns["costo_unitario"].null is True
    assert db.execute_sql("SELECT costo_unitario FROM product WHERE id = ?", (product.id,)).fetchone() == (None,)
