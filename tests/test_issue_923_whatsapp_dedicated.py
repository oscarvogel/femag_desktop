"""Numero de WhatsApp dedicado para clientes y vendedores (#923)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_cliente_tiene_campo_whatsapp_phone(db):
    from app.models.masters import Client

    cliente = Client.create(name="Cliente 923", cuit="30923000001", iva_condition="RI")
    assert cliente.whatsapp_phone is None


def test_vendedor_tiene_campo_whatsapp_phone(db):
    from app.models.masters import Salesperson

    vendedor = Salesperson.create(name="Vendedor 923")
    assert vendedor.whatsapp_phone is None


def test_el_esquema_existente_gana_la_columna(db):
    """La columna tiene que aparecer sola en una base que ya existe (#923)."""
    from app.config.schema import ensure_runtime_schema
    from app.config.database import bind_database
    from peewee import SqliteDatabase, CharField
    from app.models.base import BaseModel

    class TablaVieja(BaseModel):
        name = CharField(null=True)

        class Meta:
            table_name = "tabla_vieja_923"

    base = SqliteDatabase(":memory:")
    bind_database(base)
    base.connect(reuse_if_open=True)
    base.create_tables([TablaVieja])
    assert "whatsapp_phone" not in {
        columna.name for columna in base.get_columns("tabla_vieja_923")
    }
    # ensure_runtime_schema crea lo que falta en TODOS los modelos declarados.
    ensure_runtime_schema(base)
    assert "whatsapp_phone" in {
        columna.name for columna in base.get_columns("client")
    }
    assert "whatsapp_phone" in {
        columna.name for columna in base.get_columns("salesperson")
    }
