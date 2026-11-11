"""Precarga asistida por IA desde foto/PDF (#913).

La IA solo propone lote y fechas. Estos tests verifican que:
- el archivo se valide y se convierta en imagenes,
- el JSON del proveedor se normalice y se mapee a las lineas reales,
- el prellenado no escriba en la base,
- el guardado siga siendo el camino existente y quede auditado.
"""

import hashlib
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from PIL import Image

from conftest import _master_data

from app.models.audit import AuditLog
from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.services import order_capture_ai_service
from app.services.auth_service import AuthService
from app.services.order_capture_ai_service import (
    CaptureInputError,
    CaptureLine,
    CaptureLot,
    CaptureProposal,
    load_capture_config,
    parse_capture_date,
    prepare_media,
    validate_extraction,
)
from webapp import capture_rate_limit, create_app
from webapp.capture_service import apply_capture_to_load_lines
from webapp.load_groups import LoadContent, LoadLine
from webapp.order_service import build_load_lines

PASSWORD = "clave-de-prueba-123"

CAPTURE_ENV = (
    "FEMAG_ORDER_CAPTURE_AI_PROVIDER",
    "FEMAG_ORDER_CAPTURE_AI_API_KEY",
    "FEMAG_ORDER_CAPTURE_AI_MODEL",
    "FEMAG_ORDER_CAPTURE_AI_BASE_URL",
    "FEMAG_ORDER_CAPTURE_RATE_LIMIT_PER_HOUR",
)


@pytest.fixture(autouse=True)
def _reset_capture_state(monkeypatch):
    capture_rate_limit.reset()
    for name in CAPTURE_ENV:
        monkeypatch.delenv(name, raising=False)
    yield
    capture_rate_limit.reset()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _app():
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    return app


def _login(client):
    AuthService().create_user(
        "operador_ia",
        PASSWORD,
        "Secretaría",
        display_name="operador_ia",
        actor="test",
    )
    return client.post(
        "/login", data={"username": "operador_ia", "password": PASSWORD}
    )


def _csrf(client, token):
    client.get(f"/orden/{token}")
    with client.session_transaction() as session:
        return session["femag_csrf_token"]


def _enable_capture(monkeypatch, **overrides):
    monkeypatch.setenv("FEMAG_ORDER_CAPTURE_AI_PROVIDER", "minimax")
    monkeypatch.setenv("FEMAG_ORDER_CAPTURE_AI_API_KEY", "clave-de-prueba")
    monkeypatch.setenv(
        "FEMAG_ORDER_CAPTURE_AI_BASE_URL", "https://api.minimax.test/v1"
    )
    config = load_capture_config()
    return replace(config, **overrides) if overrides else config


def _png_bytes(width=900, height=1200):
    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _pdf_bytes(pages=1):
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    for index in range(pages):
        pdf.drawString(80, 760, f"Orden de despacho - pagina {index + 1}")
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _provider_response(payload: dict):
    return {
        "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}],
        "usage": {"total_tokens": 1200},
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }


def _order_with_line(pallet_count=2, *, order_number=91301):
    data = _master_data()
    order = LoadOrder.create(
        order_number=order_number,
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


def _order_with_two_destinations():
    data = _master_data()
    other_address = data["address"]
    from app.models.masters import ClientAddress

    second_address = ClientAddress.create(
        client=data["client"],
        address_type="entrega",
        province="Misiones",
        city="Eldorado",
        address="Ruta 12 km 1540",
    )
    order = LoadOrder.create(
        order_number=91302,
        client=data["client"],
        delivery_address=other_address,
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
    )
    first = LoadOrderDestination.create(
        order=order,
        client=data["client"],
        delivery_address=other_address,
        sequence=1,
    )
    second = LoadOrderDestination.create(
        order=order,
        client=data["client"],
        delivery_address=second_address,
        sequence=2,
    )
    first_line = LoadOrderProduct.create(
        order=order,
        destination=first,
        product=data["product"],
        quantity=100,
        unit="kg",
    )
    second_line = LoadOrderProduct.create(
        order=order,
        destination=second,
        product=data["product"],
        quantity=100,
        unit="kg",
    )
    return order, first_line, second_line


def _proposal(line_key, *, lote="08", pallets=None, status="matched"):
    return CaptureProposal(
        schema_version=1,
        order_number="91301",
        date=date(2026, 11, 6),
        client="Cliente FEMAG",
        lines=(
            CaptureLine(
                line_key=line_key,
                product_text="Fecula de mandioca",
                destination_text="Cliente FEMAG - Ruta 12",
                match_status=status,
                lots=(
                    CaptureLot(
                        lote=lote,
                        fecha_elaboracion=date(2026, 10, 19),
                        fecha_envasado=None,
                        pallets=pallets,
                        confidence=0.92,
                    ),
                ),
                warnings=(),
                confidence=0.92,
            ),
        ),
        warnings=(),
        provider="minimax",
        model="MiniMax-M3.1-Flash",
        file_sha256="abc123",
    )


# ----------------------------------------------------------------------
# Normalizacion y contrato
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("30/10/2026", date(2026, 10, 30)),
        ("30-10-26", date(2026, 10, 30)),
        ("2026-10-30", date(2026, 10, 30)),
        ("2026/10/30", date(2026, 10, 30)),
        ("elab. 30/10", None),
        ("02-0", None),
        ("", None),
        (None, None),
    ],
)
def test_fechas_manuscritas(raw, expected):
    assert parse_capture_date(raw) == expected


def test_el_lote_se_normaliza_y_limita(db):
    from app.services.order_capture_ai_service import normalize_lote

    lote, warnings = normalize_lote("  lote 08  ")
    assert lote == "LOTE 08"
    assert warnings == []

    lote, warnings = normalize_lote("x" * 300)
    assert len(lote) == 255
    assert warnings


def test_mapea_por_producto_y_destino_aunque_el_modelo_no_devuelva_key(db):
    _, order, _, line, _ = _order_with_line()
    load_lines = build_load_lines(order)
    payload = {
        "schema_version": 1,
        "lineas": [
            {
                "line_key": None,
                "producto_texto": "Fecula de mandioca",
                "cliente_destino_texto": "Cliente FEMAG - Ruta 12",
                "match_status": "matched",
                "confianza": 0.9,
                "lotes": [{"lote": "08", "fecha_elaboracion": "19/10/2026"}],
            }
        ],
    }

    lines, _warnings = validate_extraction(payload, load_lines=load_lines)

    assert len(lines) == 1
    assert lines[0].line_key == load_lines[0].key
    assert lines[0].match_status == "matched"


def test_marca_ambiguo_si_el_mismo_producto_va_a_dos_destinos(db):
    order, first_line, _ = _order_with_two_destinations()
    load_lines = build_load_lines(order)
    payload = {
        "schema_version": 1,
        "lineas": [
            {
                "line_key": None,
                "producto_texto": "Fecula de mandioca",
                "cliente_destino_texto": "",
                "match_status": "matched",
                "lotes": [{"lote": "08"}],
            }
        ],
    }

    lines, warnings = validate_extraction(payload, load_lines=load_lines)

    assert lines[0].line_key is None
    assert lines[0].match_status == "ambiguous"
    assert any("no pudo distinguir" in warning for warning in warnings)


def test_desambigua_por_destino_cuando_el_producto_se_repite(db):
    order, first_line, second_line = _order_with_two_destinations()
    load_lines = build_load_lines(order)
    payload = {
        "schema_version": 1,
        "lineas": [
            {
                "line_key": None,
                "producto_texto": "Fecula de mandioca",
                "cliente_destino_texto": "Ruta 12 km 1540 - Eldorado",
                "match_status": "matched",
                "lotes": [{"lote": "09"}],
            }
        ],
    }

    lines, _warnings = validate_extraction(payload, load_lines=load_lines)

    assert lines[0].line_key is not None
    assert lines[0].line_key != first_line.id
    assert lines[0].match_status == "matched"


def test_descarta_una_key_que_no_pertenece_a_la_orden(db):
    _, order, _, _, _ = _order_with_line()
    load_lines = build_load_lines(order)
    payload = {
        "schema_version": 1,
        "lineas": [
            {
                "line_key": "linea-inventada",
                "producto_texto": "Producto inexistente",
                "cliente_destino_texto": "",
                "match_status": "matched",
                "lotes": [{"lote": "08"}],
            }
        ],
    }

    lines, warnings = validate_extraction(payload, load_lines=load_lines)

    assert lines[0].line_key is None
    assert lines[0].match_status == "unmatched"
    assert any("no pertenece" in warning for warning in warnings)


def test_ignora_totales_y_encabezados(db):
    _, order, _, _, _ = _order_with_line()
    load_lines = build_load_lines(order)
    payload = {
        "schema_version": 1,
        "lineas": [
            {
                "line_key": None,
                "producto_texto": "TOTALES",
                "cliente_destino_texto": "",
                "match_status": "matched",
                "lotes": [{"lote": "19"}],
            }
        ],
    }

    lines, warnings = validate_extraction(payload, load_lines=load_lines)

    assert lines == ()
    assert any("totales" in warning for warning in warnings)


def test_rechaza_un_esquema_desconocido(db):
    _, order, _, _, _ = _order_with_line()
    with pytest.raises(Exception):
        validate_extraction(
            {"schema_version": 99, "lineas": []},
            load_lines=build_load_lines(order),
        )


# ----------------------------------------------------------------------
# Archivos
# ----------------------------------------------------------------------


def test_imagen_valida_se_convierte_a_jpeg(monkeypatch):
    config = _enable_capture(monkeypatch)
    media = prepare_media(_png_bytes(), "image/png", config=config)
    assert len(media) == 1
    assert media[0][0] == "image/jpeg"
    assert media[0][1].startswith(b"\xff\xd8")


def test_pdf_se_renderiza_a_imagenes(monkeypatch):
    config = _enable_capture(monkeypatch, max_pages=2)
    media = prepare_media(_pdf_bytes(pages=2), "application/pdf", config=config)
    assert len(media) == 2
    assert all(mime == "image/jpeg" for mime, _data in media)


def test_pdf_con_demasiadas_paginas_se_rechaza(monkeypatch):
    config = _enable_capture(monkeypatch, max_pages=1)
    with pytest.raises(CaptureInputError):
        prepare_media(_pdf_bytes(pages=2), "application/pdf", config=config)


def test_archivo_invalido_se_rechaza(monkeypatch):
    config = _enable_capture(monkeypatch)
    with pytest.raises(CaptureInputError):
        prepare_media(b"no soy una imagen", "text/plain", config=config)


def test_archivo_demasiado_grande_se_rechaza(monkeypatch):
    config = _enable_capture(monkeypatch, max_mb=1)
    with pytest.raises(CaptureInputError):
        prepare_media(b"x" * (1024 * 1024 + 1), "application/pdf", config=config)


# ----------------------------------------------------------------------
# Prellenado
# ----------------------------------------------------------------------


def test_un_solo_lote_prellena_el_primer_grupo(db):
    _, order, _, _, _ = _order_with_line(pallet_count=2)
    load_lines = build_load_lines(order)

    prefilled, review = apply_capture_to_load_lines(
        load_lines, _proposal(load_lines[0].key)
    )

    assert review[load_lines[0].key]["status"] == "aplicado"
    assert prefilled[0].groups[0].lote == "08"
    assert prefilled[0].groups[0].fecha_elaboracion == "2026-10-19"
    assert set(prefilled[0].groups[0].slots) == {"1", "2"}


def test_dos_lotes_con_pallets_se_reparten_en_orden(db):
    _, order, _, _, _ = _order_with_line(pallet_count=3)
    load_lines = build_load_lines(order)
    proposal = CaptureProposal(
        schema_version=1,
        order_number=None,
        date=None,
        client=None,
        lines=(
            CaptureLine(
                line_key=load_lines[0].key,
                product_text="Fecula de mandioca",
                destination_text="Cliente FEMAG",
                match_status="matched",
                lots=(
                    CaptureLot("08", date(2026, 10, 19), None, 2, 0.9),
                    CaptureLot("09", date(2026, 10, 20), None, 1, 0.8),
                ),
                warnings=(),
                confidence=0.9,
            ),
        ),
        warnings=(),
        provider="minimax",
        model="MiniMax-M3.1-Flash",
        file_sha256="abc",
    )

    prefilled, review = apply_capture_to_load_lines(load_lines, proposal)

    groups = prefilled[0].groups
    assert [group.lote for group in groups] == ["08", "09"]
    assert groups[0].slots == ("1", "2")
    assert groups[1].slots == ("3",)
    assert review[load_lines[0].key]["applied"] is True


def test_varios_lotes_sin_reparto_seguro_prellena_el_primero_y_avisa(db):
    _, order, _, _, _ = _order_with_line(pallet_count=3)
    load_lines = build_load_lines(order)
    proposal = CaptureProposal(
        schema_version=1,
        order_number=None,
        date=None,
        client=None,
        lines=(
            CaptureLine(
                line_key=load_lines[0].key,
                product_text="Fecula de mandioca",
                destination_text="Cliente FEMAG",
                match_status="matched",
                lots=(
                    CaptureLot("08", None, None, None, 0.9),
                    CaptureLot("09", None, None, None, 0.8),
                ),
                warnings=(),
                confidence=0.9,
            ),
        ),
        warnings=(),
        provider="minimax",
        model="MiniMax-M3.1-Flash",
        file_sha256="abc",
    )

    prefilled, review = apply_capture_to_load_lines(load_lines, proposal)

    assert prefilled[0].groups[0].lote == "08"
    assert any(
        "no se pudo repartir" in warning
        for warning in review[load_lines[0].key]["warnings"]
    )


def test_una_linea_ambiguo_no_se_prellena(db):
    _, order, _, _, _ = _order_with_line()
    load_lines = build_load_lines(order)
    proposal = CaptureProposal(
        schema_version=1,
        order_number=None,
        date=None,
        client=None,
        lines=(
            CaptureLine(
                line_key=None,
                product_text="Fecula de mandioca",
                destination_text="",
                match_status="ambiguous",
                lots=(CaptureLot("08", None, None, None, 0.5),),
                warnings=(),
                confidence=0.5,
            ),
        ),
        warnings=(),
        provider="minimax",
        model="MiniMax-M3.1-Flash",
        file_sha256="abc",
    )

    prefilled, review = apply_capture_to_load_lines(load_lines, proposal)

    assert prefilled[0].groups[0].lote == ""
    assert review[load_lines[0].key]["applied"] is False


# ----------------------------------------------------------------------
# Ruta web
# ----------------------------------------------------------------------


def test_importar_sin_login_redirige_al_login(db):
    _, order, _, _, _ = _order_with_line()

    response = _app().test_client().get(f"/orden/{order.qr_token}/importar")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert "/importar" in response.headers["Location"]


def test_importar_con_ia_deshabilitada_explica_el_estado(db):
    _, order, _, _, _ = _order_with_line()
    client = _app().test_client()
    _login(client)

    response = client.get(f"/orden/{order.qr_token}/importar")

    assert response.status_code == 200
    assert b"No est\xc3\xa1 disponible" in response.data or b"no est" in response.data
    assert b"FEMAG_ORDER_CAPTURE_AI_API_KEY" in response.data
    assert b"Falta la API key" in response.data


def test_importar_post_sin_csrf_no_llama_al_proveedor(db, monkeypatch):
    _, order, _, _, _ = _order_with_line()
    _enable_capture(monkeypatch)
    called = {"value": False}

    def fake_post(*args, **kwargs):
        called["value"] = True
        return _provider_response({"schema_version": 1, "lineas": []})

    monkeypatch.setattr(order_capture_ai_service, "_post_json", fake_post)
    client = _app().test_client()
    _login(client)

    response = client.post(
        f"/orden/{order.qr_token}/importar",
        data={"archivo": (BytesIO(_png_bytes()), "orden.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert called["value"] is False


def test_importar_prellena_pero_no_escribe_hasta_guardar(db, monkeypatch):
    _, order, _, line, allocations = _order_with_line(pallet_count=2)
    _enable_capture(monkeypatch)
    payload = {
        "schema_version": 1,
        "orden_numero": "91301",
        "lineas": [
            {
                "line_key": None,
                "producto_texto": "Fecula de mandioca",
                "cliente_destino_texto": "Cliente FEMAG - Ruta 12",
                "match_status": "matched",
                "confianza": 0.92,
                "lotes": [
                    {
                        "lote": "08",
                        "fecha_elaboracion": "19/10/2026",
                        "pallets": 2,
                        "confianza": 0.9,
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(
        order_capture_ai_service,
        "_post_json",
        lambda *args, **kwargs: _provider_response(payload),
    )
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, order.qr_token)
    image = _png_bytes()

    response = client.post(
        f"/orden/{order.qr_token}/importar",
        data={"csrf_token": csrf, "archivo": (BytesIO(image), "orden.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert "Precargado por IA".encode() in response.data
    assert b'value="08"' in response.data
    assert b'value="2026-10-19"' in response.data
    assert b'name="capture_source" value="ia"' in response.data
    assert LoadOrderProduct.get_by_id(line.id).lote is None
    for allocation in allocations:
        assert LoadOrderPalletAllocation.get_by_id(allocation.id).lote is None

    audit_row = (
        AuditLog.select()
        .where(AuditLog.action == "importacion de orden por ia")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit_row is not None
    assert audit_row.new_value["archivo_sha256"] == hashlib.sha256(image).hexdigest()

    key = build_load_lines(order)[0].key
    saved = client.post(
        f"/orden/{order.qr_token}",
        data={
            "csrf_token": csrf,
            f"lote_{key}_0": "08",
            f"fecha_{key}_0": "2026-10-19",
            f"pallets_{key}_0": "1,2",
            "capture_source": "ia",
            "capture_file_sha256": hashlib.sha256(image).hexdigest(),
            "capture_provider": "minimax",
            "capture_model": "MiniMax-M3.1-Flash",
        },
        follow_redirects=True,
    )

    assert saved.status_code == 200
    assert LoadOrderProduct.get_by_id(line.id).lote == "08"
    for allocation in allocations:
        assert LoadOrderPalletAllocation.get_by_id(allocation.id).lote == "08"
    saved_audit = (
        AuditLog.select()
        .where(AuditLog.action == "carga de lote")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert saved_audit.new_value["captura"]["origen"] == "ia"
    assert saved_audit.new_value["captura"]["archivo_sha256"] == hashlib.sha256(
        image
    ).hexdigest()


def test_importar_archivo_invalido_no_escribe(db, monkeypatch):
    _, order, _, line, _ = _order_with_line()
    _enable_capture(monkeypatch)
    monkeypatch.setattr(
        order_capture_ai_service,
        "_post_json",
        lambda *args, **kwargs: _provider_response({"schema_version": 1, "lineas": []}),
    )
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, order.qr_token)

    response = client.post(
        f"/orden/{order.qr_token}/importar",
        data={"csrf_token": csrf, "archivo": (BytesIO(b"hola"), "nota.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"no es una imagen" in response.data
    assert LoadOrderProduct.get_by_id(line.id).lote is None


def test_importar_error_del_proveedor_no_bloquea_la_carga_manual(db, monkeypatch):
    _, order, _, line, _ = _order_with_line()
    _enable_capture(monkeypatch)

    def fail(*args, **kwargs):
        raise order_capture_ai_service.CaptureProviderError("sin conexión")

    monkeypatch.setattr(order_capture_ai_service, "_post_json", fail)
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, order.qr_token)

    response = client.post(
        f"/orden/{order.qr_token}/importar",
        data={"csrf_token": csrf, "archivo": (BytesIO(_png_bytes()), "orden.png")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Prob\xc3\xa1 de nuevo" in response.data or b"Prob" in response.data
    assert LoadOrderProduct.get_by_id(line.id).lote is None


def test_importar_aplica_cuota_por_usuario(db, monkeypatch):
    _, order, _, _, _ = _order_with_line()
    _enable_capture(monkeypatch)
    monkeypatch.setenv("FEMAG_ORDER_CAPTURE_RATE_LIMIT_PER_HOUR", "1")
    monkeypatch.setattr(
        order_capture_ai_service,
        "_post_json",
        lambda *args, **kwargs: _provider_response({"schema_version": 1, "lineas": []}),
    )
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, order.qr_token)

    first = client.post(
        f"/orden/{order.qr_token}/importar",
        data={"csrf_token": csrf, "archivo": (BytesIO(_png_bytes()), "uno.png")},
        content_type="multipart/form-data",
    )
    second = client.post(
        f"/orden/{order.qr_token}/importar",
        data={"csrf_token": csrf, "archivo": (BytesIO(_png_bytes()), "dos.png")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert b"Demasiadas importaciones" in second.data


# ----------------------------------------------------------------------
# Dialogo nativo del escritorio: "Lote / fecha"
# ----------------------------------------------------------------------


def _traceability_proposal(line_key, *, lots, status="matched"):
    return CaptureProposal(
        schema_version=1,
        order_number="91301",
        date=date(2026, 11, 6),
        client="Cliente FEMAG",
        lines=(
            CaptureLine(
                line_key=line_key,
                product_text="Fecula de mandioca",
                destination_text="Cliente FEMAG - Ruta 12",
                match_status=status,
                lots=tuple(lots),
                warnings=(),
                confidence=0.9,
            ),
        ),
        warnings=(),
        provider="minimax",
        model="MiniMax-M3.1-Flash",
        file_sha256="abc",
    )


def test_las_lineas_del_dialogo_se_arman_para_la_ia(db):
    from app.ui.load_order_traceability_dialog import capture_line_contexts

    _, order, _, line, _ = _order_with_line(pallet_count=2)

    contexts = capture_line_contexts(order)

    assert len(contexts) == 1
    assert contexts[0].key == f"n{line.id}"
    assert contexts[0].pallets == 2
    assert contexts[0].product == "Fecula de mandioca"


def test_el_dialogo_precarga_todos_los_pallets_con_un_lote(db):
    from app.ui.load_order_traceability_dialog import (
        capture_updates_for_rows,
        load_order_traceability_rows,
    )

    _, order, _, line, _ = _order_with_line(pallet_count=2)
    rows = load_order_traceability_rows(order)

    updates, warnings, applied = capture_updates_for_rows(
        rows,
        _traceability_proposal(
            f"n{line.id}",
            lots=[
                CaptureLot(
                    "08", date(2026, 10, 19), None, 2, 0.9
                )
            ],
        ),
    )

    assert applied == 2
    assert {update["lote"] for update in updates} == {"08"}
    assert warnings == []


def test_el_dialogo_reparte_dos_lotes_por_cantidad_de_pallets(db):
    from app.ui.load_order_traceability_dialog import (
        capture_updates_for_rows,
        load_order_traceability_rows,
    )

    _, order, _, line, _ = _order_with_line(pallet_count=3)
    rows = load_order_traceability_rows(order)

    updates, _warnings, applied = capture_updates_for_rows(
        rows,
        _traceability_proposal(
            f"n{line.id}",
            lots=[
                CaptureLot("08", date(2026, 10, 19), None, 2, 0.9),
                CaptureLot("09", date(2026, 10, 20), None, 1, 0.8),
            ],
        ),
    )

    assert applied == 3
    first = next(update for update in updates if update["id"] == rows[0]["id"])
    last = next(update for update in updates if update["id"] == rows[2]["id"])
    assert first["lote"] == "08"
    assert last["lote"] == "09"


def test_el_dialogo_precarga_una_orden_legacy_sin_pallets(db):
    from app.ui.load_order_traceability_dialog import (
        capture_updates_for_rows,
        load_order_traceability_rows,
    )

    _, order, _, line, _ = _order_with_line(pallet_count=0)
    rows = load_order_traceability_rows(order)

    assert rows[0]["kind"] == "line"

    updates, _warnings, applied = capture_updates_for_rows(
        rows,
        _traceability_proposal(
            f"n{line.id}",
            lots=[CaptureLot("08", date(2026, 10, 19), None, None, 0.9)],
        ),
    )

    assert applied == 1
    assert updates[0]["kind"] == "line"
    assert updates[0]["lote"] == "08"


def test_el_dialogo_tiene_el_boton_de_importar_y_precarga_la_tabla(
    db, monkeypatch
):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.services.load_order_traceability_service import (
        LoadOrderTraceabilityService,
    )
    from app.ui import load_order_traceability_dialog as dialog_module
    from app.ui.load_order_traceability_dialog import (
        LoadOrderTraceabilityDialog,
    )
    from app.ui.theme import Theme

    monkeypatch.setattr(dialog_module, "load_theme", lambda: Theme.LIGHT)

    _, order, _, _line, allocations = _order_with_line(pallet_count=2)
    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderTraceabilityDialog(
        LoadOrderTraceabilityService(current_user="test"), order
    )
    app.processEvents()

    button = dialog.findChild(QPushButton, "loadOrderTraceabilityAiButton")
    assert button is not None

    dialog._apply_capture_updates(
        [
            {
                "kind": "pallet_content",
                "id": allocations[0].id,
                "lote": "08",
                "fecha_elaboracion": date(2026, 10, 19),
                "fecha_envasado": None,
            }
        ]
    )
    editor = dialog._editors_by_key[("pallet_content", allocations[0].id)]
    assert editor["lote"].text() == "08"
    assert editor["elaboracion"].date().toPyDate() == date(2026, 10, 19)
    assert "color: #1f2937" in editor["lote"].styleSheet()
    assert "background-color: #eaf7ef" in editor["lote"].styleSheet()
    other = dialog._editors_by_key[("pallet_content", allocations[1].id)]
    assert "color: #1f2937" in other["lote"].styleSheet()
    assert "background-color: #ffffff" in other["lote"].styleSheet()
    dialog.close()


def test_el_dialogo_usa_colores_oscuros_en_tema_oscuro(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication

    from app.services.load_order_traceability_service import (
        LoadOrderTraceabilityService,
    )
    from app.ui import load_order_traceability_dialog as dialog_module
    from app.ui.load_order_traceability_dialog import (
        LoadOrderTraceabilityDialog,
    )
    from app.ui.theme import Theme

    monkeypatch.setattr(dialog_module, "load_theme", lambda: Theme.DARK)
    _, order, _, _line, allocations = _order_with_line(pallet_count=1)
    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderTraceabilityDialog(
        LoadOrderTraceabilityService(current_user="test"), order
    )
    app.processEvents()

    editor = dialog._editors_by_key[("pallet_content", allocations[0].id)]
    assert "background-color: #161c24" in editor["lote"].styleSheet()
    assert "color: #e5edf6" in editor["lote"].styleSheet()

    dialog._apply_capture_updates(
        [
            {
                "kind": "pallet_content",
                "id": allocations[0].id,
                "lote": "56",
                "fecha_elaboracion": date(2026, 10, 30),
                "fecha_envasado": None,
            }
        ]
    )
    assert "background-color: #173a2a" in editor["lote"].styleSheet()
    assert "color: #d9fbe8" in editor["lote"].styleSheet()
    dialog.close()


def test_la_tarea_del_dialogo_emite_la_propuesta_sin_bloquear(db, monkeypatch):
    from app.ui import load_order_traceability_dialog as dialog_module
    from app.ui.load_order_traceability_dialog import capture_line_contexts

    _, order, _, line, _ = _order_with_line(pallet_count=1)
    config = _enable_capture(monkeypatch)
    expected = _traceability_proposal(
        f"n{line.id}",
        lots=[CaptureLot("08", date(2026, 10, 19), None, 1, 0.9)],
    )
    monkeypatch.setattr(
        dialog_module, "extract_capture", lambda *args, **kwargs: expected
    )
    task = dialog_module._CaptureTask(
        data=b"imagen",
        filename="orden.png",
        mime="image/png",
        contexts=capture_line_contexts(order),
        order_number=order.order_number,
        order_date=order.date,
        client_name=order.client.name,
        config=config,
    )
    completed = []
    failed = []
    finished = []
    task.signals.completed.connect(completed.append)
    task.signals.failed.connect(failed.append)
    task.signals.finished.connect(lambda: finished.append(True))

    task.run()

    assert completed == [expected]
    assert failed == []
    assert finished == [True]


def test_el_guardado_del_escritorio_audita_la_precarga_ia(db):
    from app.services.load_order_traceability_service import (
        LoadOrderTraceabilityService,
    )

    _, order, _, _line, allocations = _order_with_line(pallet_count=1)
    service = LoadOrderTraceabilityService(current_user="test")

    service.update_lote_fecha(
        order,
        [
            {
                "kind": "pallet_content",
                "id": allocations[0].id,
                "lote": "08",
                "fecha_elaboracion": date(2026, 10, 19),
                "fecha_envasado": None,
            }
        ],
        source="Precarga asistida por IA",
    )

    audit = (
        AuditLog.select()
        .where(AuditLog.action == "editar lote/fecha")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.observation == "Precarga asistida por IA"


def test_el_dialogo_pasa_el_origen_ia_al_guardar(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.load_order_traceability_dialog import (
        LoadOrderTraceabilityDialog,
    )

    _, order, _, _line, _allocations = _order_with_line(pallet_count=1)

    class FakeService:
        def __init__(self):
            self.calls = []

        def update_lote_fecha(
            self, order, items, *, reason=None, source=None
        ):
            self.calls.append((reason, source))
            return 0

    app = QApplication.instance() or QApplication([])
    service = FakeService()
    dialog = LoadOrderTraceabilityDialog(service, order)
    dialog._capture_used = True

    dialog._save()
    app.processEvents()

    assert service.calls == [("", "Precarga asistida por IA")]
    dialog.close()


def test_el_instalador_del_escritorio_crea_las_variables_de_ia():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    content = (root / "installer" / "FEMAG_Desktop.iss").read_text(
        encoding="utf-8"
    )

    assert "CreateAiCaptureConfig" in content
    assert "FEMAG_ORDER_CAPTURE_AI_PROVIDER=minimax" in content
    assert "FEMAG_ORDER_CAPTURE_AI_API_KEY=" in content


def test_minimax_pide_thinking_adaptive(monkeypatch):
    config = _enable_capture(monkeypatch)
    captured = {}

    def fake_post(url, headers, payload, timeout):
        captured.update(payload)
        return {
            "choices": [
                {"message": {"content": '{"schema_version": 1, "lineas": []}'}}
            ],
            "base_resp": {"status_code": 0},
        }

    monkeypatch.setattr(order_capture_ai_service, "_post_json", fake_post)

    content, _usage = order_capture_ai_service.call_minimax(
        config, [{"role": "user", "content": "hola"}]
    )

    assert captured["thinking"]["type"] == "adaptive"
    assert captured["reasoning_effort"] == "low"
    assert captured["max_completion_tokens"] >= 32768
    assert content.startswith("{")


def test_el_error_del_proveedor_se_extrae_del_json():
    detail = (
        '{"type":"error","error":{"type":"bad_request_error",'
        '"message":"invalid params, thinking.type=disabled is not allowed"}}'
    )

    assert (
        order_capture_ai_service._provider_error_detail(detail)
        == "invalid params, thinking.type=disabled is not allowed"
    )
    assert (
        order_capture_ai_service._provider_error_detail("error simple")
        == "error simple"
    )


def test_minimax_respuesta_vacia_informa_finish_reason(monkeypatch):
    config = _enable_capture(monkeypatch)
    monkeypatch.setattr(
        order_capture_ai_service,
        "_post_json",
        lambda *args, **kwargs: {
            "choices": [
                {"message": {"content": ""}, "finish_reason": "length"}
            ],
            "base_resp": {"status_code": 0},
        },
    )

    with pytest.raises(order_capture_ai_service.CaptureProviderError) as excinfo:
        order_capture_ai_service.call_minimax(
            config, [{"role": "user", "content": "x"}]
        )

    assert "finish_reason=length" in str(excinfo.value)


def test_minimax_usa_reasoning_si_content_viene_vacio(monkeypatch):
    config = _enable_capture(monkeypatch)
    reasoning = '{"schema_version": 1, "lineas": []}'
    monkeypatch.setattr(
        order_capture_ai_service,
        "_post_json",
        lambda *args, **kwargs: {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": reasoning,
                    },
                    "finish_reason": "stop",
                }
            ],
            "base_resp": {"status_code": 0},
        },
    )

    content, _usage = order_capture_ai_service.call_minimax(
        config, [{"role": "user", "content": "x"}]
    )

    assert content == reasoning
