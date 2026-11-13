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
    """La columna tiene que aparecer sola en una base que ya existe (#923).

    Las tablas quedan con la forma que tenian antes del cambio: las mismas
    filas, pero sin la columna ``whatsapp_phone``. Como la tabla ya existe,
    ``ensure_runtime_schema`` no puede resolverlo por ``CREATE TABLE``
    (``create_tables(safe=True)`` no toca una tabla que ya esta): la unica
    ruta que queda es ``ALTER TABLE ... ADD COLUMN``, que es la que corre en
    la base real cuando la app nueva se abre contra la base vieja.
    """
    from app.config.schema import ensure_runtime_schema
    from app.models.masters import Client, Salesperson

    cliente = Client.create(
        name="Cliente Legacy 923",
        cuit="30923000009",
        iva_condition="RI",
        phone="3511550002",
    )
    vendedor = Salesperson.create(name="Vendedor Legacy 923", phone="3511550001")

    # La base queda como estaba antes del cambio.
    db.execute_sql("ALTER TABLE `client` DROP COLUMN `whatsapp_phone`")
    db.execute_sql("ALTER TABLE `salesperson` DROP COLUMN `whatsapp_phone`")

    columnas_client = [columna.name for columna in db.get_columns("client")]
    columnas_salesperson = [columna.name for columna in db.get_columns("salesperson")]
    assert "whatsapp_phone" not in columnas_client
    assert "whatsapp_phone" not in columnas_salesperson

    ensure_runtime_schema(db)

    # ALTER TABLE agrega la columna al final de la tabla. Si la tabla se
    # recreara, el orden seria el de declaracion del modelo y estas listas no
    # darian igual.
    assert [
        columna.name for columna in db.get_columns("client")
    ] == columnas_client + ["whatsapp_phone"]
    assert [
        columna.name for columna in db.get_columns("salesperson")
    ] == columnas_salesperson + ["whatsapp_phone"]

    # Las filas que ya estaban siguen ahi: la columna es adicional, no pisa
    # el ``phone`` que el cliente y el vendedor ya tenian.
    cliente = Client.get_by_id(cliente.id)
    vendedor = Salesperson.get_by_id(vendedor.id)
    assert cliente.phone == "3511550002"
    assert vendedor.phone == "3511550001"

    # Y las filas viejas quedan sin numero de WhatsApp: no se inventa un valor.
    assert cliente.whatsapp_phone is None
    assert vendedor.whatsapp_phone is None


# ------------------------------------------------------------------ resolver


def test_el_whatsapp_dedicado_manda_sobre_el_telefono():
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_DEDICADO,
        resolver_contacto,
    )

    contacto = resolver_contacto(
        whatsapp_phone="+5491153088679", phone="011 4441-2835"
    )
    assert contacto.enviable
    assert contacto.numero == "5491153088679"
    assert contacto.origen == ORIGEN_DEDICADO


def test_sin_whatsapp_dedicado_cae_al_telefono_si_es_celular():
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_TELEFONO,
        resolver_contacto,
    )

    contacto = resolver_contacto(whatsapp_phone="", phone="011 15 53088679")
    assert contacto.enviable
    assert contacto.numero == "5491153088679"
    assert contacto.origen == ORIGEN_TELEFONO


def test_un_telefono_dudoso_no_es_destino():
    from app.services.whatsapp_contact_resolver import resolver_contacto

    contacto = resolver_contacto(whatsapp_phone="", phone="011 4441-2835")
    assert not contacto.enviable
    assert contacto.numero == ""
    assert "dudoso" in contacto.mensaje


def test_un_whatsapp_cargado_que_no_es_celular_no_cae_al_telefono():
    """Si el operador cargo un WhatsApp roto, no se manda a otro numero."""
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_DEDICADO,
        resolver_contacto,
    )

    contacto = resolver_contacto(
        whatsapp_phone="011 4441-2835", phone="011 15 53088679"
    )
    assert not contacto.enviable
    assert contacto.origen == ORIGEN_DEDICADO


def test_sin_telefono_no_hay_destino():
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_NINGUNO,
        resolver_contacto,
    )

    contacto = resolver_contacto(whatsapp_phone="", phone="")
    assert not contacto.enviable
    assert contacto.origen == ORIGEN_NINGUNO


def test_con_el_flag_apagado_se_ignora_el_campo_nuevo():
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_TELEFONO,
        resolver_contacto,
    )

    contacto = resolver_contacto(
        whatsapp_phone="+5491153088679",
        phone="011 15 53088679",
        preferir_dedicado=False,
    )
    assert contacto.numero == "5491153088679"
    assert contacto.origen == ORIGEN_TELEFONO


def test_el_mensaje_es_el_mismo_que_el_de_hoy():
    """El texto de error no cambia: el operador ve lo mismo que siempre."""
    from app.services.account_statement_share_service import normalize_whatsapp_phone
    from app.services.whatsapp_contact_resolver import resolver_contacto

    for numero in ("011 4441-2835", "01148975105//01157357632", ""):
        try:
            normalize_whatsapp_phone(numero)
            esperado = None
        except ValueError as exc:
            esperado = str(exc)
        contacto = resolver_contacto(whatsapp_phone="", phone=numero)
        assert contacto.mensaje == esperado
