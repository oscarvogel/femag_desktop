"""Motor de la campana de lista de precios por WhatsApp (#705 Fase B, issue #763)."""

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _RelojFalso:
    """Reloj que solo avanza cuando el motor duerme."""

    def __init__(self):
        self.t = 0.0
        self.esperas = []

    def __call__(self):
        return self.t

    def dormir(self, segundos):
        self.esperas.append(segundos)
        self.t += segundos


class _EnviosFalsos:
    """Doble del servicio de envio: no toca el gateway y puede fallar por destino."""

    def __init__(self, errores=None):
        self.errores = errores or {}
        self.enviados = []
        self.llamadas = 0

    def resolve_instance_for_user(self, usuario):
        return "instancia-prueba"

    def send_pdf(self, *, envio, pdf_path, poll_attempts=1, poll_interval=0):
        self.llamadas += 1
        cola = self.errores.get(envio.destinatario)
        if cola:
            error = cola.pop(0)
            envio.estado = "failed"
            envio.error = str(error)
            envio.save()
            raise error
        envio.estado = "accepted"
        envio.message_id = f"msg-{len(self.enviados) + 1}"
        envio.save()
        self.enviados.append(envio)
        return envio


def _pendiente(client_id=1, telefono="5491153088679", nombre="Cliente"):
    from app.services.price_list_send_service import Pendiente

    return Pendiente(
        client_id=client_id,
        nombre=nombre,
        telefono=telefono,
        caption="Hola, adjuntamos la lista de precios.",
    )


def _runner(tmp_path, pendientes, **kwargs):
    from app.services.price_list_send_service import PriceListCampaignRunner

    pdf = tmp_path / "lista1.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    reloj = _RelojFalso()
    envios = kwargs.pop("envios", None) or _EnviosFalsos()
    opciones = dict(
        clave="lista1-lista1-20261023-1700",
        pdf_path=pdf,
        pendientes=pendientes,
        usuario=None,
        envios=envios,
        instance_id="instancia-prueba",
        intervalo=180.0,
        lote_inicial=0,
        dormir=reloj.dormir,
        reloj=reloj,
        azar=lambda a, b: 0.0,
    )
    opciones.update(kwargs)
    runner = PriceListCampaignRunner(**opciones)
    return runner, reloj, envios


# ---------------------------------------------------------------------- la clave


def test_la_clave_de_campana_trae_lista_pdf_y_sello():
    from app.services.price_list_send_service import clave_campana

    momento = datetime(2026, 10, 23, 17, 30)

    assert clave_campana(1, "C:/listas/lista1.pdf", momento) == "lista1-lista1-20261023-1730"
    assert clave_campana(2, "lista2.pdf", momento) == "lista2-lista2-20261023-1730"


# ------------------------------------------------------------------- idempotencia


def test_los_pendientes_sacan_a_quien_ya_fue_enviado(db):
    from app.models.whatsapp import WhatsAppEnvio
    from app.services.price_list_send_service import (
        TIPO_DOCUMENTO,
        destinatarios_pendientes,
        external_ref,
    )
    from app.services.price_list_campaign_service import Destinatario

    clave = "lista1-lista1-20261023-1700"
    WhatsAppEnvio.create(
        tipo_documento=TIPO_DOCUMENTO,
        documento_id=clave,
        destinatario="5491153088679",
        instance_id="instancia-prueba",
        external_ref=external_ref(clave, 1),
        nombre_archivo="lista1.pdf",
        estado="delivered",
    )
    WhatsAppEnvio.create(
        tipo_documento=TIPO_DOCUMENTO,
        documento_id=clave,
        destinatario="5491153088680",
        instance_id="instancia-prueba",
        external_ref=external_ref(clave, 2),
        nombre_archivo="lista1.pdf",
        estado="preparing",
    )

    audiencia = [
        Destinatario(1, "Ya enviado", "5491153088679", "5491153088679", "celular", "", 1, True),
        Destinatario(2, "A medio camino", "5491153088680", "5491153088680", "celular", "", 1, True),
    ]

    pendientes = destinatarios_pendientes(clave, audiencia)

    assert [d.client_id for d in pendientes] == [2]


def test_el_tope_diario_cuenta_lo_de_hoy_y_no_lo_de_ayer(db):
    from app.models.whatsapp import WhatsAppEnvio
    from app.services.price_list_send_service import (
        TIPO_DOCUMENTO,
        contar_envios_del_dia,
        external_ref,
    )

    clave = "lista1-lista1-20261023-1700"
    ahora = datetime(2026, 10, 23, 17, 30)
    hoy = datetime(2026, 10, 23, 10, 0)
    ayer = datetime(2026, 10, 22, 10, 0)

    for indice, momento in enumerate((hoy, hoy, ayer), start=1):
        WhatsAppEnvio.create(
            tipo_documento=TIPO_DOCUMENTO,
            documento_id=clave,
            destinatario=f"54911530886{indice}",
            instance_id="instancia-prueba",
            external_ref=external_ref(clave, indice),
            nombre_archivo="lista1.pdf",
            estado="accepted",
            created_at=momento,
        )

    assert contar_envios_del_dia("instancia-prueba", ahora) == 2
    assert contar_envios_del_dia("otra-instancia", ahora) == 0


# ------------------------------------------------------------------- la cola


def test_la_cola_manda_en_orden_y_respeta_el_intervalo(db, tmp_path):
    pendientes = [
        _pendiente(1, "5491153088679", "Uno"),
        _pendiente(2, "5491153088680", "Dos"),
        _pendiente(3, "5491153088681", "Tres"),
    ]
    tiempos = []
    runner, reloj, envios = _runner(tmp_path, pendientes, intervalo=180.0)
    runner.al_evento = lambda evento: tiempos.append(reloj()) if evento.tipo == "enviado" else None

    resultado = runner.run()

    assert resultado.enviados == 3
    assert [envio.destinatario for envio in envios.enviados] == [
        "5491153088679",
        "5491153088680",
        "5491153088681",
    ]
    # Entre dos envios consecutivos hay al menos el intervalo configurado.
    assert tiempos[1] - tiempos[0] >= 180.0
    assert tiempos[2] - tiempos[1] >= 180.0


def test_el_lote_inicial_detiene_la_campana(db, tmp_path):
    pendientes = [_pendiente(indice, f"54911530886{indice}") for indice in range(1, 5)]
    runner, reloj, envios = _runner(tmp_path, pendientes, lote_inicial=2)

    resultado = runner.run()

    assert resultado.enviados == 2
    assert resultado.detenido_por == "lote_inicial"
    assert "Confirmá" in resultado.motivo
    assert len(envios.enviados) == 2


def test_el_tope_diario_detiene_la_campana(db, tmp_path):
    pendientes = [_pendiente(indice, f"54911530886{indice}") for indice in range(1, 5)]
    runner, reloj, envios = _runner(tmp_path, pendientes, tope_diario=1)

    resultado = runner.run()

    assert resultado.enviados == 1
    assert resultado.detenido_por == "tope_diario"
    assert "Límite diario" in resultado.motivo


def test_el_circuit_breaker_para_la_campana_completa(db, tmp_path):
    from app.services.whatsapp_api_client import WhatsAppApiError

    pendientes = [
        _pendiente(1, "5491153088679", "Uno"),
        _pendiente(2, "5491153088680", "Dos"),
        _pendiente(3, "5491153088681", "Tres"),
    ]
    envios = _EnviosFalsos(
        {"5491153088679": [WhatsAppApiError("El gateway respondió HTTP 429; se esperaba 202.")]}
    )
    runner, reloj, _ = _runner(tmp_path, pendientes, envios=envios)

    resultado = runner.run()

    assert resultado.enviados == 0
    assert resultado.fallidos == 0
    assert resultado.detenido_por == "circuit_breaker"
    assert "límite de envíos" in resultado.motivo
    # No insiste: el primer rechazo corta la campaña.
    assert envios.llamadas == 1


def test_un_error_transitorio_se_reintenta(db, tmp_path):
    from app.services.whatsapp_api_client import WhatsAppApiError

    pendientes = [_pendiente(1, "5491153088679")]
    envios = _EnviosFalsos(
        {"5491153088679": [WhatsAppApiError("No se pudo conectar con el gateway de WhatsApp.")]}
    )
    runner, reloj, _ = _runner(tmp_path, pendientes, envios=envios)

    resultado = runner.run()

    assert resultado.enviados == 1
    assert envios.llamadas == 2


def test_un_error_permanente_no_se_reintenta(db, tmp_path):
    from app.services.whatsapp_api_client import WhatsAppApiError

    pendientes = [_pendiente(1, "5491153088679")]
    envios = _EnviosFalsos(
        {"5491153088679": [WhatsAppApiError("El gateway respondió HTTP 400; se esperaba 202.")]}
    )
    runner, reloj, _ = _runner(tmp_path, pendientes, envios=envios)

    resultado = runner.run()

    assert resultado.enviados == 0
    assert resultado.fallidos == 1
    assert envios.llamadas == 1
    assert "HTTP 400" in resultado.errores[0]


def test_cancelar_detiene_la_campana(db, tmp_path):
    pendientes = [_pendiente(indice, f"54911530886{indice}") for indice in range(1, 4)]
    runner, reloj, envios = _runner(tmp_path, pendientes)

    def al_enviar(evento):
        if evento.tipo == "enviado":
            runner.cancelar()

    runner.al_evento = al_enviar
    resultado = runner.run()

    assert resultado.enviados == 1
    assert resultado.detenido_por == "cancelado"


def test_la_pausa_espera_a_reanudar(db, tmp_path):
    pendientes = [_pendiente(1, "5491153088679")]
    runner, reloj, envios = _runner(tmp_path, pendientes)
    runner.pausar()

    def dormir(segundos):
        runner.reanudar()
        reloj.dormir(segundos)

    runner.dormir = dormir
    resultado = runner.run()

    assert resultado.enviados == 1
    assert envios.llamadas == 1


# ------------------------------------------------------------------- auditoria


def test_la_auditoria_registra_el_envio_con_el_numero_del_clasificador(tmp_path, db):
    from app.models.whatsapp import WhatsAppEnvio

    pendientes = [_pendiente(1, "5491153088679", "BAREIRO JAVIER")]
    runner, reloj, envios = _runner(tmp_path, pendientes)

    runner.run()

    envio = WhatsAppEnvio.get(WhatsAppEnvio.external_ref == "femag:lista_precios:lista1-lista1-20261023-1700:1")
    assert envio.tipo_documento == "lista_precios"
    assert envio.documento_id == "lista1-lista1-20261023-1700"
    # El numero va tal cual lo devolvio el clasificador, sin el normalizador viejo.
    assert envio.destinatario == "5491153088679"
    assert envio.instance_id == "instancia-prueba"
    assert envio.nombre_archivo == "lista1.pdf"
    assert envio.estado == "accepted"
    assert envio.message_id


def test_reintentar_un_fallido_reusa_la_fila_y_no_duplica_el_external_ref(tmp_path, db):
    from app.models.whatsapp import WhatsAppEnvio
    from app.services.whatsapp_api_client import WhatsAppApiError

    pendientes = [_pendiente(1, "5491153088679")]
    envios = _EnviosFalsos(
        {"5491153088679": [WhatsAppApiError("El gateway respondió HTTP 400; se esperaba 202.")]}
    )
    runner, reloj, _ = _runner(tmp_path, pendientes, envios=envios)
    runner.run()

    assert WhatsAppEnvio.select().count() == 1

    # Segundo intento del mismo destinatario (el boton "Reintentar fallidos").
    envios2 = _EnviosFalsos()
    runner2, _, _ = _runner(tmp_path, pendientes, envios=envios2)
    runner2.run()

    assert WhatsAppEnvio.select().count() == 1
    assert envios2.llamadas == 1
