"""Idempotencia de los backfills de arranque y filtro en SQL del de correos.

El PR #637 acotó cuatro backfills para que dejaran de trabajar cuando no hay
nada que trabajar. Los cuatro issues pedían que correr la función dos veces
seguidas no escribiera nada en la segunda, y ese criterio no tenía cobertura:
quedaba probado por medición, no por la suite. Acá está.

Los conteos se hacen parcheando ``execute_sql`` de la instancia, que es por
donde pasa todo el SQL que emite peewee. Si una aserción falla, el mensaje
incluye las consultas que se vieron, porque un "no dio 0 escrituras" sin decir
qué escribió no sirve para nada.
"""


from itertools import count

_CUIT = count(1)


def _operaciones(db, fn):
    """Corre ``fn(db)`` y devuelve (operaciones SQL, escrituras, detalle)."""
    sqls = []
    original = db.execute_sql

    def contada(sql, *args, **kwargs):
        sqls.append(str(sql))
        return original(sql, *args, **kwargs)

    db.execute_sql = contada
    try:
        fn(db)
    finally:
        db.execute_sql = original

    encabezados = ("SELECT", "INSERT", "UPDATE", "DELETE")
    vistas = [s for s in sqls if s.strip().upper().startswith(encabezados)]
    escrituras = [s for s in vistas if not s.strip().upper().startswith("SELECT")]
    return len(vistas), len(escrituras), escrituras


def _sin_escrituras(db, fn, mensaje):
    vistas, escrituras, detalle = _operaciones(db, fn)
    assert escrituras == 0, "%s: escribió %d veces\n%s" % (mensaje, escrituras, "\n".join(detalle))
    return vistas


# --------------------------------------------------------------------- #589


def _cliente_con_correo(nombre, correo, **campos):
    from app.models.masters import Client

    return Client.create(
        name=nombre, cuit="20%011d" % next(_CUIT),
        iva_condition="RI", email=correo, **campos
    )


def test_backfill_client_emails_filtra_en_sql_y_no_toca_la_cartera(db):
    """Criterio 1 y 2 de #589: 1 consulta, sin importar cuantos clientes haya.

    Con el corte en Python eran 1 consulta por cliente sobre la cartera ya
    consolidada. El número tiene que ser constante, no proporcional: por eso se
    funden 60 clientes y se exige 1 sola operación.
    """
    from app.config.schema import _backfill_client_emails
    from app.models.masters import ClientEmail

    for i in range(60):
        cliente = _cliente_con_correo("Cliente %d" % i, "cliente%d@ejemplo.com" % i)
        ClientEmail.create(
            client=cliente, email="cliente%d@ejemplo.com" % i,
            label="Legacy", is_primary=True, active=True,
        )

    vistas = _sin_escrituras(db, _backfill_client_emails, "2da corrida sobre cartera consolidada")

    assert vistas == 1, "el filtro deberia ser una consulta constante, se vio %d" % vistas


def test_backfill_client_emails_promueve_el_correo_del_cliente_si_no_es_primario(db):
    """El caso que un filtro mal puesto rompe: hay trabajo y no hay primario.

    El cliente tiene su correo cargado pero la fila de `ClientEmail` que le
    corresponde esta inactiva. El backfill existe justamente para promoting, asi
    que el filtro tiene que dejarlo entrar: si mirara cualquier fila de
    `ClientEmail` en vez de "no tiene un primario activo", este cliente se
    quedaria a medias para siempre.
    """
    from app.config.schema import _backfill_client_emails
    from app.models.masters import ClientEmail

    cliente = _cliente_con_correo("Inactivo", "mio@ejemplo.com")
    ClientEmail.create(
        client=cliente, email="mio@ejemplo.com", label="Legacy",
        is_primary=False, active=False,
    )

    _backfill_client_emails(db)

    fila = ClientEmail.get(ClientEmail.client == cliente)
    assert fila.active is True
    assert fila.is_primary is True


def test_backfill_client_emails_no_toca_filas_que_no_son_el_correo_del_cliente(db):
    """Las filas viejas de otros correos no son de este backfill.

    El backfill migra `client.email`. Un `ClientEmail` con otro correo pertenece
    a otra cosa y no se promueve ni se borra: el criterio es "no perder trabajo",
    no "dejar la tabla impecable".
    """
    from app.config.schema import _backfill_client_emails
    from app.models.masters import ClientEmail

    cliente = _cliente_con_correo("Con historial", "actual@ejemplo.com")
    vieja = ClientEmail.create(
        client=cliente, email="viejo@ejemplo.com", label="Legacy",
        is_primary=False, active=False,
    )

    _backfill_client_emails(db)

    assert ClientEmail.select().count() == 2
    assert ClientEmail.get_by_id(vieja.id).active is False
    assert ClientEmail.get_by_id(vieja.id).is_primary is False

    creada = ClientEmail.get(ClientEmail.email == "actual@ejemplo.com")
    assert creada.is_primary is True
    assert creada.active is True


def test_backfill_client_emails_no_promueve_si_ya_hay_otro_primario(db):
    """Con un primario activo alcanza: el resto de las filas no se tocan."""
    from app.config.schema import _backfill_client_emails
    from app.models.masters import ClientEmail

    cliente = _cliente_con_correo("Con primario", "primario@ejemplo.com")
    ClientEmail.create(
        client=cliente, email="principal@ejemplo.com", label="Legacy",
        is_primary=True, active=True,
    )
    ClientEmail.create(
        client=cliente, email="respaldo@ejemplo.com", label="Legacy",
        is_primary=False, active=False,
    )

    _sin_escrituras(db, _backfill_client_emails, "cliente que ya tiene primario activo")

    filas = {
        fila.email: (fila.active, fila.is_primary)
        for fila in ClientEmail.select().where(ClientEmail.client == cliente)
    }
    assert filas["respaldo@ejemplo.com"] == (False, False), "un respaldo no se promueve por su cuenta"


def test_backfill_client_emails_consolida_una_sola_vez(db):
    """Criterios 4 y 5 de #589: crea los pendientes y descarta los malformados. """
    from app.config.schema import _backfill_client_emails
    from app.models.masters import ClientEmail

    for i in range(12):
        _cliente_con_correo("Valido %d" % i, "valido%d@ejemplo.com" % i)
    for i in range(3):
        _cliente_con_correo("Malformado %d" % i, "no-es-correo@@%d" % i)

    _backfill_client_emails(db)

    assert ClientEmail.select().count() == 12
    assert ClientEmail.select().where(ClientEmail.is_primary == True).count() == 12  # noqa: E712
    assert ClientEmail.select().where(ClientEmail.active == True).count() == 12  # noqa: E712

    # Y la segunda corrida no agrega nada.
    _sin_escrituras(db, _backfill_client_emails, "2da corrida tras consolidar")
    assert ClientEmail.select().count() == 12


# --------------------------------------------------------------------- #588


def _cartera_pallets_normalizada(db):
    from app.models.load_orders import LoadOrder, LoadOrderPallet
    from app.models.masters import Carrier, Driver, PalletType, Truck

    carrier = Carrier.create(name="Transporte idempotencia")
    driver = Driver.create(name="Chofer idempotencia", carrier=carrier)
    truck = Truck.create(domain="MID001", carrier=carrier)
    pallet_type = PalletType.create(type="Idempotencia", measure="1x1", weight=0)
    for n in range(5):
        order = LoadOrder.create(order_number=7000 + n, carrier=carrier, driver=driver, truck=truck)
        for seq in range(1, 4):
            LoadOrderPallet.create(
                order=order, pallet_type=pallet_type, sequence=seq,
                measure="1x1", weight=0, quantity=1,
            )


def test_normalize_legacy_pallet_rows_no_escribe_en_la_segunda_corrida(db):
    """#588: 0 escrituras y updated_at intacto cuando ya esta normalizado. """
    from app.config.schema import _normalize_legacy_pallet_rows
    from app.models.load_orders import LoadOrderPallet

    _cartera_pallets_normalizada(db)
    antes = {row.id: row.updated_at for row in LoadOrderPallet.select()}

    _sin_escrituras(db, _normalize_legacy_pallet_rows, "2da corrida sobre pallets normalizados")

    despues = {row.id: row.updated_at for row in LoadOrderPallet.select()}
    tocados = [pid for pid in antes if antes[pid] != despues.get(pid)]
    assert tocados == [], "el arranque no debe alterar la trazabilidad de los pallets"
    assert LoadOrderPallet.select().count() == 15


# --------------------------------------------------------------------- #590


def test_backfill_product_classification_no_escribe_en_la_segunda_corrida(db):
    """#590: la 1ra clasifica, la 2da no toca nada. """
    from app.config.schema import _backfill_product_classification
    from app.models.masters import Product

    for i in range(8):
        Product.create(name="Producto idempotencia %d" % i, unit="kg")

    vistas, escrituras, detalle = _operaciones(db, _backfill_product_classification)
    assert escrituras == 8, "la primera corrida tiene que clasificar los 8, no %d\n%s" % (
        escrituras, "\n".join(detalle))

    _sin_escrituras(db, _backfill_product_classification, "2da corrida sobre productos clasificados")


# --------------------------------------------------------------------- #591


def test_consolidate_shared_client_addresses_preselecciona_en_sql(db):
    """#591: la segunda corrida no recorre la cartera.

    El fix de #637 sobre esta funcion fue de **lecturas**, no de escrituras: la
    segunda corrida ya daba cero escrituras antes de ese PR, asi que contar
    escrituras no distingue nada. Lo que se elimino fue la consulta por cliente.

    Con 30 clientes ya consolidados tiene que dar 2 SELECT -- el set de los que
    ya tienen direccion compartida y la consulta filtrada -- y no uno por
    cliente.
    """
    from app.config.schema import _consolidate_shared_client_addresses
    from app.models.masters import Client, ClientAddress

    valores = dict(
        province="Misiones", city="Posadas", address="Ruta 12",
        observations="Codigo postal: 3300", is_primary=True,
    )
    for i in range(30):
        cliente = Client.create(
            name="Cliente idempotencia %d" % i, cuit="20%011d" % i, iva_condition="RI"
        )
        ClientAddress.create(client=cliente, address_type="fiscal", **valores)
        ClientAddress.create(client=cliente, address_type="entrega", **valores)

    # 1ra corrida: consolida de verdad, una fila compartida por cliente.
    _consolidate_shared_client_addresses(db)
    assert ClientAddress.select().where(ClientAddress.address_type == "fiscal_entrega").count() == 30

    # 2da corrida: no escribe y no recorre.
    vistas = _sin_escrituras(
        db, _consolidate_shared_client_addresses, "2da corrida sobre cartera consolidada"
    )
    assert vistas == 2, "esperaba 2 SELECT (set de consolidados + consulta filtrada), vi %d" % vistas
    assert ClientAddress.select().count() == 30
