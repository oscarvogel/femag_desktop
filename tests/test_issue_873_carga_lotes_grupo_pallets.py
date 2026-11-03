"""Carga de lote y fecha por grupo de pallets en la ficha web (#873).

La ficha pide una linea de despacho y no un pallet: el lote y la fecha se
cargan una vez y se aplican a todos los pallets del grupo.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from conftest import _master_data

from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.sync import SyncOutbox, SyncProjection
from app.services.auth_service import AuthService
from app.services.sync_order_publisher import SyncOrderPublisher
from app.services.sync_snapshot_service import SyncSnapshotService
from webapp import create_app
from webapp.load_groups import build_groups, main_group, validate_groups
from webapp.order_service import build_load_lines
from webapp.projected_order_service import projected_load_lines

PASSWORD = "clave-de-prueba-123"


def _app():
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    return app


def _login(client):
    AuthService().create_user(
        "operador",
        PASSWORD,
        "Secretaría",
        display_name="operador",
        actor="test",
    )
    return client.post(
        "/login", data={"username": "operador", "password": PASSWORD}
    )


def _csrf(client, token):
    client.get(f"/orden/{token}")
    with client.session_transaction() as session:
        return session["femag_csrf_token"]


def _order_with_pallets(pallet_count=3):
    """Orden local con una linea de despacho repartida en varios pallets."""

    data = _master_data()
    order = LoadOrder.create(
        order_number=87301,
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
    )
    destination = LoadOrderDestination.create(
        order=order,
        client=data["client"],
        delivery_address=data["address"],
        sequence=1,
    )
    line = LoadOrderProduct.create(
        order=order,
        destination=destination,
        product=data["product"],
        quantity=60 * pallet_count,
        unit="bolsa",
    )
    allocations = []
    for sequence in range(1, pallet_count + 1):
        pallet = LoadOrderPallet.create(order=order, sequence=sequence)
        allocations.append(
            LoadOrderPalletAllocation.create(
                pallet=pallet,
                destination=destination,
                product=data["product"],
                quantity=Decimal("60"),
                peso_unitario_kg=Decimal("25"),
            )
        )
    return data, order, destination, line, allocations


def _projected_order(*, with_line_uid=True, pallet_count=2):
    """Orden proyectada desde la fabrica, con contenidos por pallet."""

    line_uid = str(uuid4())
    client_uid = str(uuid4())
    pallets = []
    for sequence in range(1, pallet_count + 1):
        contents = []
        for index in range(1, pallet_count + 1):
            content = {
                "content_uid": str(uuid4()),
                "product_name": "Fecula Fabrica",
                "quantity": 60,
                "unit": "bolsa",
                "lote": None,
                "fecha_elaboracion": None,
                "fecha_envasado": None,
                "client_name": "Cliente Fabrica",
                "destination": "Ruta Fabrica - Posadas",
            }
            if with_line_uid:
                content["line_uid"] = line_uid
            contents.append(content)
        pallets.append(
            {"pallet_uid": str(uuid4()), "sequence": sequence, "contents": contents}
        )
    return {
        "order_uid": str(uuid4()),
        "order_number": 873,
        "qr_token": "token-873",
        "status": "Emitida",
        "version": 1,
        "order_date": "2026-11-03",
        "published_at": "2026-11-03T12:00:00Z",
        "updated_at": "2026-11-03T12:00:00Z",
        "cancelled_at": None,
        "client": {"client_uid": client_uid, "name": "Cliente Fabrica"},
        "destination": {
            "destination_uid": str(uuid4()),
            "city": "Posadas",
            "address": "Ruta Fabrica",
        },
        "lines": [
            {
                "line_uid": line_uid,
                "product_name": "Fecula Fabrica",
                "quantity": 120,
                "unit": "bolsa",
                "lote": None,
                "fecha_elaboracion": None,
                "fecha_envasado": None,
            }
        ],
        "pallets": pallets,
        "loose_contents": [],
    }


def _apply_snapshot(order):
    SyncSnapshotService.apply_snapshot(
        {
            "schema_version": "1.0",
            "snapshot_id": str(uuid4()),
            "generated_at": "2026-11-03T12:00:00Z",
            "cursor": 1,
            "orders": [order],
        }
    )


# ----------------------------------------------------------------------
# La pantalla
# ----------------------------------------------------------------------


def test_una_linea_con_tres_pallets_muestra_un_solo_formulario(db):
    _, order, _, line, _ = _order_with_pallets(pallet_count=3)

    response = _app().test_client().get(f"/orden/{order.qr_token}")

    assert response.status_code == 200
    # Un unico formulario de lote para los tres pallets de la linea.
    assert response.data.count(f'name="lote_n{line.id}_0"'.encode()) == 1
    # Los tres pallets aparecen como botones de la linea.
    for sequence in (1, 2, 3):
        assert f'data-slot="{sequence}"'.encode() in response.data
    assert b"otro lote para otros pallets" in response.data


def test_la_linea_sin_pallets_mantiene_su_lote(db):
    data = _master_data()
    order = LoadOrder.create(
        order_number=87302,
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
    )
    line = LoadOrderProduct.create(
        order=order,
        product=data["product"],
        quantity=100,
        unit="kg",
        lote="LOTE-VIEJO",
        fecha_elaboracion=date(2026, 10, 20),
    )

    response = _app().test_client().get(f"/orden/{order.qr_token}")

    assert response.status_code == 200
    assert b'value="LOTE-VIEJO"' in response.data
    assert b'value="2026-10-20"' in response.data


# ----------------------------------------------------------------------
# Guardado en la orden local
# ----------------------------------------------------------------------


def test_cargar_una_linea_escribe_el_lote_en_la_linea_y_en_sus_pallets(db):
    _, order, _, line, allocations = _order_with_pallets(pallet_count=3)
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, order.qr_token)

    response = client.post(
        f"/orden/{order.qr_token}",
        data={
            "csrf_token": csrf,
            f"lote_n{line.id}_0": "LOTE-08",
            f"fecha_n{line.id}_0": "2026-10-19",
            f"fecha_envasado_n{line.id}_0": "2026-10-18",
            f"pallets_n{line.id}_0": "1,2,3",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    line = LoadOrderProduct.get_by_id(line.id)
    assert line.lote == "LOTE-08"
    assert line.fecha_elaboracion == date(2026, 10, 19)
    assert line.fecha_envasado == date(2026, 10, 18)
    for allocation in allocations:
        allocation = LoadOrderPalletAllocation.get_by_id(allocation.id)
        assert allocation.lote == "LOTE-08"
        assert allocation.fecha_elaboracion == date(2026, 10, 19)
        assert allocation.fecha_envasado == date(2026, 10, 18)


def test_dos_grupos_dejan_el_lote_de_su_grupo_en_cada_pallet(db):
    _, order, _, line, allocations = _order_with_pallets(pallet_count=3)
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, order.qr_token)

    response = client.post(
        f"/orden/{order.qr_token}",
        data={
            "csrf_token": csrf,
            f"lote_n{line.id}_0": "LOTE-08",
            f"fecha_n{line.id}_0": "2026-10-19",
            f"pallets_n{line.id}_0": "1,2",
            f"lote_n{line.id}_1": "LOTE-09",
            f"fecha_n{line.id}_1": "2026-10-20",
            f"pallets_n{line.id}_1": "3",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    first = LoadOrderPalletAllocation.get_by_id(allocations[0].id)
    second = LoadOrderPalletAllocation.get_by_id(allocations[1].id)
    third = LoadOrderPalletAllocation.get_by_id(allocations[2].id)
    assert first.lote == "LOTE-08"
    assert second.lote == "LOTE-08"
    assert third.lote == "LOTE-09"
    assert third.fecha_elaboracion == date(2026, 10, 20)
    # La linea guarda el lote del grupo que cubre mas pallets.
    line = LoadOrderProduct.get_by_id(line.id)
    assert line.lote == "LOTE-08"


def test_un_pallet_en_dos_grupos_se_rechaza(db):
    _, order, _, line, allocations = _order_with_pallets(pallet_count=3)
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, order.qr_token)

    response = client.post(
        f"/orden/{order.qr_token}",
        data={
            "csrf_token": csrf,
            f"lote_n{line.id}_0": "LOTE-08",
            f"fecha_n{line.id}_0": "2026-10-19",
            f"pallets_n{line.id}_0": "1,2",
            f"lote_n{line.id}_1": "LOTE-09",
            f"fecha_n{line.id}_1": "2026-10-20",
            f"pallets_n{line.id}_1": "2,3",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"dos lotes" in response.data
    # No se guardo nada.
    for allocation in allocations:
        allocation = LoadOrderPalletAllocation.get_by_id(allocation.id)
        assert allocation.lote is None
    line = LoadOrderProduct.get_by_id(line.id)
    assert line.lote is None


def test_una_fecha_invalida_se_rechaza(db):
    _, order, _, line, allocations = _order_with_pallets(pallet_count=2)
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, order.qr_token)

    response = client.post(
        f"/orden/{order.qr_token}",
        data={
            "csrf_token": csrf,
            f"lote_n{line.id}_0": "LOTE-08",
            f"fecha_n{line.id}_0": "19/10/2026",
            f"pallets_n{line.id}_0": "1,2",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"AAAA-MM-DD" in response.data
    for allocation in allocations:
        allocation = LoadOrderPalletAllocation.get_by_id(allocation.id)
        assert allocation.lote is None


def test_la_mercaderia_suelta_tambien_tiene_grupo(db):
    data, order, destination, line, _ = _order_with_pallets(pallet_count=1)
    LoadOrderLooseAllocation.create(
        order=order,
        destination=destination,
        product=data["product"],
        quantity=Decimal("20"),
        peso_unitario_kg=Decimal("25"),
    )

    load_lines = build_load_lines(order)

    assert len(load_lines) == 1
    loose = [content for content in load_lines[0].contents if content.kind == "loose"]
    assert len(loose) == 1
    assert loose[0].slot == "S"


# ----------------------------------------------------------------------
# Nube (orden proyectada)
# ----------------------------------------------------------------------


def test_la_nube_agrupa_por_linea_y_no_por_pallet(db):
    order = _projected_order(pallet_count=2)
    _apply_snapshot(order)

    response = _app().test_client().get("/orden/token-873")

    assert response.status_code == 200
    # Un solo formulario para los pallets de la linea.
    assert response.data.count(b'name="lote_p') == 1
    assert response.data.count(b'data-slot="1"') == 1
    assert response.data.count(b'data-slot="2"') == 1


def test_la_nube_carga_la_linea_y_los_contenidos(db):
    order = _projected_order(pallet_count=2)
    _apply_snapshot(order)
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, "token-873")

    key = f"p{order['lines'][0]['line_uid']}"
    response = client.post(
        "/orden/token-873",
        data={
            "csrf_token": csrf,
            f"lote_{key}_0": "LOTE-08",
            f"fecha_{key}_0": "2026-10-19",
            f"pallets_{key}_0": "1,2",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    events = list(SyncOutbox.select())
    types = {event.event_type for event in events}
    assert "order_content_lote_fecha_updated" in types
    assert "order_lote_fecha_updated" in types
    content_events = [
        event
        for event in events
        if event.event_type == "order_content_lote_fecha_updated"
    ]
    assert len(content_events) == 2
    for event in content_events:
        assert event.payload["lote"] == "LOTE-08"
        assert event.payload["fecha_elaboracion"] == "2026-10-19"


def test_la_nube_sin_line_uid_no_rompe_y_no_completa_la_linea(db):
    order = _projected_order(with_line_uid=False, pallet_count=2)
    _apply_snapshot(order)
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, "token-873")

    response = client.get("/orden/token-873")
    assert response.status_code == 200
    assert b'name="lote_g' in response.data

    key = response.data.decode().split('name="lote_g')[1].split("_")[0]
    client.post(
        "/orden/token-873",
        data={
            "csrf_token": csrf,
            f"lote_g{key}_0": "LOTE-08",
            f"fecha_g{key}_0": "2026-10-19",
            f"pallets_g{key}_0": "1,2",
        },
        follow_redirects=True,
    )

    events = list(SyncOutbox.select())
    types = {event.event_type for event in events}
    assert "order_content_lote_fecha_updated" in types
    # Sin line_uid la nube no sabe que linea completar: no encola evento de linea.
    assert "order_lote_fecha_updated" not in types


# ----------------------------------------------------------------------
# Reglas de agrupamiento
# ----------------------------------------------------------------------


def test_los_contenidos_que_comparten_lote_quedan_en_el_mismo_grupo(db):
    _, order, _, _, allocations = _order_with_pallets(pallet_count=2)
    allocations[0].lote = "LOTE-08"
    allocations[0].fecha_elaboracion = date(2026, 10, 19)
    allocations[0].save()
    allocations[1].lote = "LOTE-08"
    allocations[1].fecha_elaboracion = date(2026, 10, 19)
    allocations[1].save()

    load_lines = build_load_lines(order)

    assert len(load_lines) == 1
    groups = load_lines[0].groups
    assert len(groups) == 1
    assert groups[0].lote == "LOTE-08"
    assert set(groups[0].slots) == {"1", "2"}


def test_un_pallet_sin_lote_queda_en_el_grupo_vacio(db):
    _, order, _, _, allocations = _order_with_pallets(pallet_count=2)
    allocations[0].lote = "LOTE-08"
    allocations[0].save()

    load_lines = build_load_lines(order)

    groups = load_lines[0].groups
    assert len(groups) == 2
    assert groups[0].lote == "LOTE-08"
    assert groups[0].slots == ("1",)
    assert groups[1].lote == ""
    assert groups[1].slots == ("2",)


def test_validar_rechaza_un_pallet_que_no_es_de_la_linea():
    from webapp.load_groups import LoadContent, LoadLine

    line = LoadLine(
        key="n1",
        product="Fecula",
        client="Cliente",
        destination="Destino",
        quantity=100,
        unit="bolsa",
        contents=(
            LoadContent(
                id="1",
                kind="pallet",
                slot="1",
                slot_label="P1",
                pallet_sequence=1,
                product="Fecula",
                quantity=60,
                unit="bolsa",
            ),
        ),
    )
    from webapp.load_groups import LoadGroup

    groups = [LoadGroup(index=0, lote="08", slots=("1", "9"))]
    errors = validate_groups(line, groups)
    assert any("no pertenece" in error for error in errors)


def test_el_grupo_principal_es_el_que_mas_pallets_tiene():
    from webapp.load_groups import LoadGroup

    groups = [
        LoadGroup(index=0, lote="09", slots=("9", "10")),
        LoadGroup(index=1, lote="08", slots=("1", "2", "3", "4", "5", "6", "7", "8")),
    ]
    assert main_group(groups).lote == "08"


# ----------------------------------------------------------------------
# Contrato fabrica -> nube
# ----------------------------------------------------------------------


def test_el_contenido_publicado_trae_el_line_uid(db):
    _, order, _, line, _ = _order_with_pallets(pallet_count=1)

    payload = SyncOrderPublisher().build_order(order)

    content = payload["pallets"][0]["contents"][0]
    assert content["line_uid"]
    assert content["line_uid"] == payload["lines"][0]["line_uid"]


def test_el_grupo_se_arma_con_la_linea_del_contenido(db):
    _, order, _, line, _ = _order_with_pallets(pallet_count=2)

    payload = SyncOrderPublisher().build_order(order)
    line_uid = payload["lines"][0]["line_uid"]

    _apply_snapshot(payload | {"qr_token": "token-publisher"})
    projection = SyncProjection.get(
        SyncProjection.resource_type == SyncProjection.RESOURCE_ORDER
    )
    order_payload = projection.payload
    assert order_payload["pallets"][0]["contents"][0]["line_uid"] == line_uid

    load_lines = projected_load_lines(
        __import__(
            "webapp.projected_order_service", fromlist=["x"]
        ).get_projected_order_by_token("token-publisher")
    )
    assert len(load_lines) == 1
    assert load_lines[0].line_uid == line_uid
    assert len(load_lines[0].contents) == 2
