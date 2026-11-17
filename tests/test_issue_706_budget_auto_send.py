"""Envio automatico de presupuestos al emitir una orden (#706).

Se prueba el servicio sin Qt y sin servicios externos: el gateway de WhatsApp y
el SMTP se inyectan falsos. Lo que se valida es la regla del destinatario, el
aislamiento de los PDFs, la tolerancia a fallos y la idempotencia.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import (
    _complete_order_for_issue,
    _master_data,
    _multi_client_data,
    _valid_order_payload,
)


# --------------------------------------------------------------- utilidades


class FakeEnvios:
    """Gateway falso: registra lo que se le pide y no sale a la red."""

    def __init__(self, *, fallar_en=None):
        self.created = []
        self.sent = []
        self.fallar_en = fallar_en

    def create_attempt(self, **kwargs):
        self.created.append(kwargs)
        envio = SimpleNamespace(id=len(self.created), **kwargs)
        return envio

    def send_pdf(self, *, envio, pdf_path, poll_attempts=1, poll_interval=0):
        if self.fallar_en and self.fallar_en(envio):
            raise RuntimeError("gateway caido")
        self.sent.append(envio)
        return envio


class FakeMailer:
    def __init__(self):
        self.sent = []

    def __call__(self, **kwargs):
        self.sent.append(kwargs)


def _emitir(db, *, cantidad_facturar_ahora=None, client_setup=None, salesperson=None):
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    client = data["client"]
    if salesperson is not None:
        client.salesperson = salesperson
    if client_setup:
        client_setup(client, data)
    client.save()

    payload = _valid_order_payload(data)
    if cantidad_facturar_ahora is not None:
        payload["products"][0]["cantidad_facturar_ahora"] = cantidad_facturar_ahora
    order = LoadOrderService(current_user="admin").create_order(**payload)
    _complete_order_for_issue(order)
    LoadOrderOperationService(current_user="admin").issue(order)
    return order, data


def _servicio(envios=None, mailer=None, *, preferir_dedicado=False, prints_dir=None):
    import tempfile

    from app.services.budget_auto_send_service import BudgetAutoSendService

    if prints_dir is None:
        prints_dir = tempfile.mkdtemp(prefix="femag-706-")
    return BudgetAutoSendService(
        "admin",
        prints_dir=prints_dir,
        envios=envios or FakeEnvios(),
        mailer=mailer or FakeMailer(),
        preferir_dedicado=preferir_dedicado,
    )


def _vendedor(nombre="Vendedor Uno", phone="+54 9 376 4000001"):
    from app.models.masters import Salesperson

    return Salesperson.create(name=nombre, phone=phone)


# ------------------------------------------------------------------- flag


def _sin_env_real(monkeypatch, tmp_path):
    monkeypatch.setenv("FEMAG_ENV_FILE", str(tmp_path / "missing.env"))


def test_el_autoenvio_esta_apagado_por_default(monkeypatch, tmp_path):
    from app.config.settings import load_settings

    _sin_env_real(monkeypatch, tmp_path)
    monkeypatch.delenv("FEMAG_PRESUPUESTOS_AUTOENVIO", raising=False)
    assert load_settings().presupuestos_autoenvio is False


@pytest.mark.parametrize("valor", ["1", "true", "yes", "si", "on"])
def test_el_autoenvio_se_enciende_con_la_variable(monkeypatch, tmp_path, valor):
    from app.config.settings import load_settings

    _sin_env_real(monkeypatch, tmp_path)
    monkeypatch.setenv("FEMAG_PRESUPUESTOS_AUTOENVIO", valor)
    assert load_settings().presupuestos_autoenvio is True


def test_la_interfaz_no_encola_nada_con_el_flag_apagado(monkeypatch, tmp_path):
    from app.services.budget_auto_send_service import autoenvio_habilitado
    from app.ui.load_order_budget_auto_send import start_budget_auto_send

    _sin_env_real(monkeypatch, tmp_path)
    monkeypatch.delenv("FEMAG_PRESUPUESTOS_AUTOENVIO", raising=False)
    assert autoenvio_habilitado() is False
    assert start_budget_auto_send(object(), current_user="admin", prints_dir=tmp_path) is False


# -------------------------------------------------------- destinatario unico


def test_cliente_sin_vendedor_recibe_su_propio_presupuesto(db):
    order, data = _emitir(
        db,
        client_setup=lambda client, _data: setattr(client, "phone", "+54 9 376 4555000"),
    )
    envios = FakeEnvios()
    resultado = _servicio(envios).dispatch_order(order)

    assert len(envios.created) == 1
    assert envios.created[0]["destinatario"] == "+5493764555000"
    assert envios.created[0]["documento_id"] == str(resultado.documentos[0].budget_id)
    assert resultado.enviados[0].destinatario_tipo == "cliente"
    assert resultado.enviados[0].destinatario_nombre == data["client"].name


def test_cliente_con_vendedor_va_al_vendedor_y_no_al_cliente(db):
    vendedor = _vendedor(phone="+54 9 376 4000001")
    order, data = _emitir(
        db,
        salesperson=vendedor,
        client_setup=lambda client, _data: setattr(client, "phone", "+54 9 376 4555000"),
    )
    envios = FakeEnvios()
    resultado = _servicio(envios).dispatch_order(order)

    assert len(envios.created) == 1
    assert envios.created[0]["destinatario"] == "+5493764000001"
    assert resultado.enviados[0].destinatario_tipo == "vendedor"
    assert resultado.enviados[0].destinatario_nombre == vendedor.name


def test_si_el_vendedor_no_tiene_numero_no_cae_al_cliente(db):
    vendedor = _vendedor(phone="")
    order, data = _emitir(
        db,
        salesperson=vendedor,
        client_setup=lambda client, _data: setattr(client, "phone", "+54 9 376 4555000"),
    )
    envios = FakeEnvios()
    resultado = _servicio(envios).dispatch_order(order)

    assert envios.created == []
    whatsapp = [item for item in resultado.documentos if item.canal == "whatsapp"]
    assert len(whatsapp) == 1
    assert whatsapp[0].estado == "omitido"
    assert whatsapp[0].destinatario_tipo == "vendedor"
    assert "telefono" in whatsapp[0].motivo.lower()


def test_cada_cliente_recibe_el_pdf_que_le_corresponde(db):
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService
    from tests.load_order_printing_cases import _pdf_text

    data = _multi_client_data()
    data["client"].phone = "+54 9 376 4555000"
    data["client"].save()
    data["other_client"].phone = "+54 9 376 4555001"
    data["other_client"].save()
    order = LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [{"product": data["product"], "quantity": 10}],
            },
            {
                "client": data["other_client"],
                "delivery_address": data["other_address"],
                "products": [{"product": data["other_product"], "quantity": 5}],
            },
        ],
    )
    _complete_order_for_issue(order)
    LoadOrderOperationService(current_user="admin").issue(order)

    envios = FakeEnvios()
    resultado = _servicio(envios).dispatch_order(order)

    assert len(envios.created) == 2
    por_cliente = {
        item.cliente: item.budget_id
        for item in resultado.enviados
        if item.canal == "whatsapp"
    }
    assert set(por_cliente) == {data["client"].name, data["other_client"].name}
    assert por_cliente[data["client"].name] != por_cliente[data["other_client"].name]

    for envio in envios.created:
        budget_id = int(envio["documento_id"])
        texto = _pdf_text(Path(envio["pdf_path"]))
        esperado = (
            data["client"].name
            if por_cliente[data["client"].name] == budget_id
            else data["other_client"].name
        )
        assert esperado in texto
        assert envio["pdf_path"].name == f"presupuesto_{budget_id:06d}.pdf"


# --------------------------------------------------------------- tolerancia


def test_un_envio_ya_confirmado_no_se_repite(db):
    from app.models.whatsapp import WhatsAppEnvio

    order, _data = _emitir(
        db,
        client_setup=lambda client, _data: setattr(client, "phone", "+54 9 376 4555000"),
    )
    budget_id = _servicio().dispatch_order(order).documentos[0].budget_id
    WhatsAppEnvio.create(
        tipo_documento="presupuesto",
        documento_id=str(budget_id),
        destinatario="5493764555000",
        external_ref=f"test:presupuesto:{budget_id}",
        estado="delivered",
        nombre_archivo="presupuesto.pdf",
        mime_type="application/pdf",
    )

    envios = FakeEnvios()
    resultado = _servicio(envios).dispatch_order(order)

    assert envios.created == []
    whatsapp = [item for item in resultado.documentos if item.canal == "whatsapp"]
    assert whatsapp[0].estado == "omitido"
    assert "Ya se envio" in whatsapp[0].motivo


def test_el_fallo_de_un_envio_no_frena_los_demas(db):
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    data["client"].phone = "+54 9 376 4555000"
    data["client"].save()
    data["other_client"].phone = "+54 9 376 4555001"
    data["other_client"].save()
    order = LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [{"product": data["product"], "quantity": 10}],
            },
            {
                "client": data["other_client"],
                "delivery_address": data["other_address"],
                "products": [{"product": data["other_product"], "quantity": 5}],
            },
        ],
    )
    _complete_order_for_issue(order)
    LoadOrderOperationService(current_user="admin").issue(order)

    envios = FakeEnvios(fallar_en=lambda envio: len(envios.created) == 1)
    resultado = _servicio(envios).dispatch_order(order)

    assert len(envios.created) == 2
    assert len(envios.sent) == 1
    assert len(resultado.fallidos) == 1
    assert len([item for item in resultado.enviados if item.canal == "whatsapp"]) == 1
    assert resultado.fallidos[0].motivo == "gateway caido"


def test_el_dispatch_no_levanta_si_un_documento_falla(db, monkeypatch):
    order, _data = _emitir(
        db,
        client_setup=lambda client, _data: setattr(client, "phone", "+54 9 376 4555000"),
    )
    servicio = _servicio()

    def _romper(_budget):
        raise RuntimeError("pdf roto")

    monkeypatch.setattr(servicio, "_dispatch_budget", _romper)

    resultado = servicio.dispatch_order(order)

    assert resultado.documentos
    assert all(item.estado == "fallido" for item in resultado.documentos)


# ------------------------------------------------------------------ correo


def test_sin_correo_el_canal_queda_omitido_con_motivo(db):
    order, _data = _emitir(
        db,
        client_setup=lambda client, _data: setattr(client, "phone", "+54 9 376 4555000"),
    )
    resultado = _servicio().dispatch_order(order)

    correo = [item for item in resultado.documentos if item.canal == "correo"]
    assert len(correo) == 1
    assert correo[0].estado == "omitido"
    assert "correo" in correo[0].motivo.lower()


def test_correo_con_direccion_se_envia_una_sola_vez(db):
    order, data = _emitir(
        db,
        client_setup=lambda client, _data: (
            setattr(client, "phone", "+54 9 376 4555000"),
            setattr(client, "email", "cliente@example.com"),
        ),
    )
    mailer = FakeMailer()
    envios = FakeEnvios()

    primero = _servicio(envios, mailer).dispatch_order(order)
    segundo = _servicio(envios, mailer).dispatch_order(order)

    assert len(mailer.sent) == 1
    assert mailer.sent[0]["recipient"] == "cliente@example.com"
    assert mailer.sent[0]["pdf_path"].name.startswith("presupuesto_")
    assert [item.estado for item in primero.documentos if item.canal == "correo"] == [
        "enviado"
    ]
    assert [item.estado for item in segundo.documentos if item.canal == "correo"] == [
        "omitido"
    ]
    assert data["client"].name in mailer.sent[0]["subject"]


def test_el_correo_va_al_mismo_destinatario_que_el_whatsapp(db):
    vendedor = _vendedor(phone="+54 9 376 4000001")
    from app.models.masters import Salesperson

    Salesperson.update(email="vendedor@example.com").where(Salesperson.id == vendedor.id).execute()
    order, _data = _emitir(
        db,
        salesperson=vendedor,
        client_setup=lambda client, _data: (
            setattr(client, "phone", "+54 9 376 4555000"),
            setattr(client, "email", "cliente@example.com"),
        ),
    )
    mailer = FakeMailer()

    resultado = _servicio(FakeEnvios(), mailer).dispatch_order(order)

    assert mailer.sent[0]["recipient"] == "vendedor@example.com"
    assert {
        item.destinatario_tipo for item in resultado.documentos
    } == {"vendedor"}


# ------------------------------------------------------------- alcance/cableado


def test_los_presupuestos_manuales_no_participan(db, monkeypatch):
    from app.models.budgets import Budget
    from app.models.masters import Product
    from app.services.budget_service import BudgetService

    order, data = _emitir(
        db,
        client_setup=lambda client, _data: setattr(client, "phone", "+54 9 376 4555000"),
    )
    manual = BudgetService(current_user="admin").create_manual(
        client=data["client"],
        items=[
            {
                "product": Product.create(name="Producto manual", unit="kg"),
                "quantity": 1,
                "unit": "kg",
                "unit_price": 100,
                "vat_percentage": 21,
            }
        ],
    )
    envios = FakeEnvios()

    resultado = _servicio(envios).dispatch_order(order)

    ids = {int(envio["documento_id"]) for envio in envios.created}
    assert manual.id not in ids
    assert ids == {
        item.budget_id for item in resultado.documentos if item.canal == "whatsapp"
    }


def test_el_cableado_esta_en_la_emision_compartida():
    fuente = Path("app/ui/load_order_stock_shortfall_dialog.py").read_text(encoding="utf-8")
    assert "_start_budget_auto_send" in fuente
    assert "start_budget_auto_send" in fuente

    ui = Path("app/ui/load_order_budget_auto_send.py").read_text(encoding="utf-8")
    assert "autoenvio_habilitado" in ui
    assert "QThreadPool" in ui

    servicio = Path("app/services/budget_auto_send_service.py").read_text(encoding="utf-8")
    assert "def autoenvio_habilitado" in servicio
    assert "presupuestos_autoenvio" in servicio
