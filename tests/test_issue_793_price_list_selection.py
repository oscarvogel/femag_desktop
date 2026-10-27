"""Selección de destinatarios, búsqueda y confirmación de la lista de precios (#793)."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _cliente(nombre, cuit, lista=1, phone=None):
    from app.models.masters import Client

    return Client.create(
        name=nombre,
        cuit=cuit,
        iva_condition="RI",
        phone=phone,
        lista_precios=lista,
    )


def _clientes(cantidad, lista=1):
    return [
        _cliente(
            f"Cliente {indice:04d}",
            f"30{indice:09d}",
            lista,
            f"011 15 5308{indice:04d}",
        )
        for indice in range(1, cantidad + 1)
    ]


def _pagina():
    from PyQt5.QtWidgets import QApplication

    from app.ui.price_list_send_page import PriceListSendPage

    app = QApplication.instance() or QApplication([])
    pagina = PriceListSendPage(user=None, current_user="prueba-793")
    app.processEvents()
    return app, pagina


def _preparar(db, cantidad=3, tmp_path=None):
    """Calcula destinatarios con un PDF ya elegido (el PDF primero es el flujo real)."""
    app, pagina = _pagina()
    if tmp_path is not None:
        pdf = tmp_path / "lista1.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        pagina.pdf_input.setText(str(pdf))
    pagina._calcular_destinatarios()
    app.processEvents()
    return app, pagina


def _marcar(pagina, filas, *, app=None):
    from PyQt5.QtCore import Qt

    for fila in filas:
        pagina.destinatarios_table.item(fila, 0).setCheckState(Qt.Checked)
    if app is not None:
        app.processEvents()


class _EnviosFalsos:
    """Doble del gateway: no manda nada real y registra destinos."""

    def __init__(self):
        self.enviados = []
        self.llamadas = 0

    def resolve_instance_for_user(self, usuario):
        return "instancia-prueba"

    def send_pdf(self, *, envio, pdf_path, poll_attempts=1, poll_interval=0):
        self.llamadas += 1
        envio.estado = "accepted"
        envio.message_id = f"msg-{len(self.enviados) + 1}"
        envio.save()
        self.enviados.append(envio)
        return envio


class _TrabajadorFalso:
    def __init__(self):
        self.runner = SimpleNamespace(pausado=False)


def _preparar_para_enviar(pagina, *, confirmacion=True):
    pagina._envios = _EnviosFalsos()
    pagina._envios_error = ""
    pagina.confirmacion_check.setChecked(True)
    llamadas = {"worker": [], "confirmacion": []}

    def fake_worker(pendientes, *, lote_inicial, excluir_enviados=True):
        llamadas["worker"].append(
            {
                "pendientes": list(pendientes),
                "lote_inicial": lote_inicial,
                "excluir_enviados": excluir_enviados,
            }
        )
        pagina.worker = _TrabajadorFalso()

    def fake_confirmacion(seleccionados, disponibles):
        llamadas["confirmacion"].append((seleccionados, disponibles))
        return confirmacion

    pagina._iniciar_worker = fake_worker
    pagina._pedir_confirmacion_envio = fake_confirmacion
    return llamadas


# ------------------------------------------------------------------ selección


def test_seleccionar_un_cliente_entre_muchos(db, tmp_path):
    from PyQt5.QtCore import Qt

    _clientes(125)
    app, pagina = _preparar(db, 125, tmp_path)
    pagina._deseleccionar_todos()
    app.processEvents()

    _marcar(pagina, [10], app=app)

    assert "1 seleccionados de 125 disponibles" in pagina.contadores_label.text()
    assert len(pagina._destinatarios_seleccionados()) == 1
    assert pagina.destinatarios_table.item(10, 0).checkState() == Qt.Checked


def test_seleccionar_tres_clientes_entre_125(db, tmp_path):
    _clientes(125)
    app, pagina = _preparar(db, 125, tmp_path)
    pagina._deseleccionar_todos()
    app.processEvents()

    _marcar(pagina, [0, 57, 124], app=app)

    seleccionados = pagina._destinatarios_seleccionados()
    assert len(seleccionados) == 3
    assert [d.client_id for d in seleccionados] == [
        pagina.destinatarios[0].client_id,
        pagina.destinatarios[57].client_id,
        pagina.destinatarios[124].client_id,
    ]
    assert "3 seleccionados de 125 disponibles" in pagina.contadores_label.text()


def test_seleccionar_todos_y_deseleccionar_todos(db, tmp_path):
    _clientes(5)
    app, pagina = _preparar(db, 5, tmp_path)

    assert "5 seleccionados de 5 disponibles" in pagina.contadores_label.text()

    pagina._deseleccionar_todos()
    app.processEvents()
    assert "0 seleccionados de 5 disponibles" in pagina.contadores_label.text()
    assert pagina._destinatarios_seleccionados() == []

    pagina._seleccionar_todos()
    app.processEvents()
    assert "5 seleccionados de 5 disponibles" in pagina.contadores_label.text()


def test_los_clientes_sin_whatsapp_valido_no_se_pueden_seleccionar(db, tmp_path):
    _cliente("Con celular", "30793000001", 1, "011 15 53088679")
    _cliente("Sin telefono", "30793000002", 1, None)
    app, pagina = _preparar(db, 2, tmp_path)

    pagina._seleccionar_todos()
    app.processEvents()

    assert [d.nombre for d in pagina._destinatarios_seleccionados()] == ["Con celular"]


# ------------------------------------------------------------------- búsqueda


def test_filtrar_por_nombre_actualiza_sin_enter(db, tmp_path):
    _cliente("BAREIRO JAVIER", "30793000001", 1, "011 15 53080001")
    _cliente("GIMENEZ ROMINA", "30793000002", 1, "011 15 53080002")
    _cliente("LOPEZ ANA", "30793000003", 1, "011 15 53080003")
    app, pagina = _preparar(db, 3, tmp_path)

    pagina.busqueda_input.setText("bareiro")
    app.processEvents()

    assert pagina.destinatarios_table.rowCount() == 1
    assert pagina.destinatarios_table.item(0, 1).text() == "BAREIRO JAVIER"
    assert "1 visibles" in pagina.contadores_label.text()


def test_filtrar_por_telefono_y_numero_de_whatsapp(db, tmp_path):
    _cliente("BAREIRO JAVIER", "30793000001", 1, "011 15 53080001")
    _cliente("GIMENEZ ROMINA", "30793000002", 1, "011 15 53080002")
    app, pagina = _preparar(db, 2, tmp_path)

    pagina.busqueda_input.setText("53080002")
    app.processEvents()
    assert pagina.destinatarios_table.rowCount() == 1
    assert pagina.destinatarios_table.item(0, 1).text() == "GIMENEZ ROMINA"

    pagina.busqueda_input.setText("5491153080002")
    app.processEvents()
    assert pagina.destinatarios_table.rowCount() == 1
    assert pagina.destinatarios_table.item(0, 1).text() == "GIMENEZ ROMINA"


def test_la_busqueda_conserva_los_seleccionados_ocultos(db, tmp_path):
    _cliente("BAREIRO JAVIER", "30793000001", 1, "011 15 53080001")
    _cliente("GIMENEZ ROMINA", "30793000002", 1, "011 15 53080002")
    _cliente("LOPEZ ANA", "30793000003", 1, "011 15 53080003")
    app, pagina = _preparar(db, 3, tmp_path)
    pagina._deseleccionar_todos()
    app.processEvents()

    pagina.busqueda_input.setText("BAREIRO")
    app.processEvents()
    _marcar(pagina, [0], app=app)

    pagina.busqueda_input.setText("GIMENEZ")
    app.processEvents()
    _marcar(pagina, [0], app=app)

    pagina.busqueda_input.setText("LOPEZ")
    app.processEvents()
    _marcar(pagina, [0], app=app)

    pagina.busqueda_input.clear()
    app.processEvents()

    assert pagina.destinatarios_table.rowCount() == 3
    assert len(pagina.seleccionados) == 3
    assert "3 seleccionados de 3 disponibles" in pagina.contadores_label.text()


def test_seleccionar_todos_con_filtro_actua_solo_sobre_los_visibles(db, tmp_path):
    _cliente("BAREIRO JAVIER", "30793000001", 1, "011 15 53080001")
    _cliente("GIMENEZ ROMINA", "30793000002", 1, "011 15 53080002")
    _cliente("LOPEZ ANA", "30793000003", 1, "011 15 53080003")
    app, pagina = _preparar(db, 3, tmp_path)
    pagina._deseleccionar_todos()
    app.processEvents()

    pagina.busqueda_input.setText("GIMENEZ")
    app.processEvents()
    assert pagina.seleccionar_todos_button.text() == "Seleccionar visibles (1)"

    pagina._seleccionar_todos()
    app.processEvents()

    assert [d.nombre for d in pagina._destinatarios_seleccionados()] == ["GIMENEZ ROMINA"]


# --------------------------------------------------------------- confirmación


def test_el_texto_de_confirmacion_usa_las_cantidades_reales():
    from app.ui.price_list_send_page import texto_confirmacion_envio

    texto = texto_confirmacion_envio(3, 125)

    assert (
        "Estás por enviar la lista de precios a 3 clientes seleccionados de 125 disponibles."
        in texto
    )
    assert "¿Confirmás el envío únicamente a estos 3 clientes?" in texto

    singular = texto_confirmacion_envio(1, 125)
    assert "a 1 cliente seleccionado de 125 disponibles" in singular
    assert "únicamente a este cliente" in singular


def test_cancelar_la_confirmacion_no_encola_ni_envia(db, tmp_path):
    from app.models.whatsapp import WhatsAppEnvio

    _clientes(3)
    app, pagina = _preparar(db, 3, tmp_path)
    llamadas = _preparar_para_enviar(pagina, confirmacion=False)

    pagina._iniciar_envio()
    app.processEvents()

    assert llamadas["confirmacion"] == [(3, 3)]
    assert llamadas["worker"] == []
    assert pagina.worker is None
    assert WhatsAppEnvio.select().count() == 0


def test_sin_destinatarios_no_se_puede_iniciar_el_envio(db, tmp_path):
    _clientes(3)
    app, pagina = _preparar(db, 3, tmp_path)
    pagina._deseleccionar_todos()
    app.processEvents()
    llamadas = _preparar_para_enviar(pagina)

    pagina._iniciar_envio()
    app.processEvents()

    assert llamadas["worker"] == []
    assert llamadas["confirmacion"] == []
    assert pagina.feedback.kind == "warning"
    assert "No hay clientes seleccionados" in pagina.feedback.message


def test_confirmar_encola_solo_los_tres_seleccionados_de_125(db, tmp_path):
    _clientes(125)
    app, pagina = _preparar(db, 125, tmp_path)
    pagina._deseleccionar_todos()
    app.processEvents()
    _marcar(pagina, [0, 57, 124], app=app)
    esperados = [d.client_id for d in pagina._destinatarios_seleccionados()]
    llamadas = _preparar_para_enviar(pagina)

    pagina._iniciar_envio()
    app.processEvents()

    assert len(llamadas["confirmacion"]) == 1
    assert llamadas["confirmacion"][0] == (3, 125)
    assert len(llamadas["worker"]) == 1
    pendientes = llamadas["worker"][0]["pendientes"]
    assert len(pendientes) == 3
    assert [d.client_id for d in pendientes] == esperados
    # Los otros 122 clientes nunca entran a la cola.
    assert not ({d.client_id for d in pagina.destinatarios} - set(esperados)) & {
        d.client_id for d in pendientes
    }


def test_confirmar_dos_veces_seguidas_no_duplica_la_cola(db, tmp_path):
    _clientes(3)
    app, pagina = _preparar(db, 3, tmp_path)
    llamadas = _preparar_para_enviar(pagina)

    pagina._iniciar_envio()
    pagina._iniciar_envio()
    app.processEvents()

    assert len(llamadas["confirmacion"]) == 1
    assert len(llamadas["worker"]) == 1
    assert len(llamadas["worker"][0]["pendientes"]) == 3


def test_la_cola_real_envia_solo_a_los_seleccionados(db, tmp_path, monkeypatch):
    """De la pantalla al motor: el runner recibe exactamente los 3 IDs marcados."""
    import app.ui.price_list_send_page as page_module

    _clientes(125)
    app, pagina = _preparar(db, 125, tmp_path)
    pagina._deseleccionar_todos()
    app.processEvents()
    _marcar(pagina, [0, 57, 124], app=app)
    seleccionados = pagina._destinatarios_seleccionados()
    envios = _EnviosFalsos()
    pagina._envios = envios
    pagina._envios_error = ""

    creados = {}

    class _Signal:
        def connect(self, *_args, **_kwargs):
            return None

    class _WorkerFalso:
        def __init__(self, runner):
            self.runner = runner
            self.signals = SimpleNamespace(
                evento=_Signal(), terminado=_Signal(), error=_Signal()
            )

    class _PoolFalso:
        def start(self, worker):
            creados["worker"] = worker

    monkeypatch.setattr(page_module, "PriceListSendWorker", _WorkerFalso)
    monkeypatch.setattr(
        page_module.QThreadPool, "globalInstance", staticmethod(lambda: _PoolFalso())
    )

    pagina._iniciar_worker(seleccionados, lote_inicial=0)

    runner = creados["worker"].runner
    assert [p.client_id for p in runner.pendientes] == [
        d.client_id for d in seleccionados
    ]
    assert [p.telefono for p in runner.pendientes] == [
        d.telefono_normalizado for d in seleccionados
    ]

    # El worker real correría en otro hilo; acá se ejecuta la misma cola sin esperar el throttling.
    runner.intervalo = 0
    runner.dormir = lambda _segundos: None
    resultado = runner.run()

    assert resultado.enviados == 3
    assert envios.llamadas == 3
    assert [e.destinatario for e in envios.enviados] == [
        d.telefono_normalizado for d in seleccionados
    ]


def test_cambiar_la_lista_descarta_la_seleccion_y_la_audiencia(db, tmp_path):
    _clientes(3)
    app, pagina = _preparar(db, 3, tmp_path)
    assert pagina.seleccionados

    pagina.lista_combo.setCurrentIndex(1)
    app.processEvents()

    assert pagina.seleccionados == set()
    assert pagina.destinatarios == []
    assert pagina.destinatarios_table.rowCount() == 0
    assert "Todavía no calculaste" in pagina.contadores_label.text()


def test_cambiar_el_pdf_descarta_la_seleccion_anterior(db, tmp_path):
    _clientes(3)
    app, pagina = _preparar(db, 3, tmp_path)
    assert pagina.seleccionados

    otro = tmp_path / "lista1-nueva.pdf"
    otro.write_bytes(b"%PDF-1.4\n%%EOF\n")
    pagina.pdf_input.setText(str(otro))
    app.processEvents()

    assert pagina.seleccionados == set()
    assert "0 seleccionados de 3 disponibles" in pagina.contadores_label.text()
    assert pagina.enviar_button.isEnabled() is False


def test_si_cambia_un_telefono_se_pide_recalcular_antes_de_enviar(db, tmp_path):
    from app.models.masters import Client

    clientes = _clientes(3)
    app, pagina = _preparar(db, 3, tmp_path)
    llamadas = _preparar_para_enviar(pagina)

    clientes[1].phone = None
    clientes[1].save()

    pagina._iniciar_envio()
    app.processEvents()

    assert llamadas["worker"] == []
    assert "Recalculá" in pagina.feedback.message


def test_al_continuar_un_lote_solo_quedan_los_seleccionados(db, tmp_path):
    from app.services.price_list_send_service import ResultadoCampana

    _clientes(125)
    app, pagina = _preparar(db, 125, tmp_path)
    pagina._deseleccionar_todos()
    app.processEvents()
    _marcar(pagina, [0, 57, 124], app=app)
    seleccionados = pagina._destinatarios_seleccionados()
    pagina.pendientes = list(seleccionados)
    pagina.estado_filas[seleccionados[0].client_id] = {
        "estado": "enviado",
        "detalle": "",
        "hora": "",
    }

    pagina._al_terminar(
        ResultadoCampana(
            enviados=1,
            detenido_por="lote_inicial",
            motivo="1 enviado. Confirmá si querés seguir con los que quedan.",
        )
    )
    app.processEvents()

    assert [d.client_id for d in pagina.pendientes_restantes] == [
        seleccionados[1].client_id,
        seleccionados[2].client_id,
    ]


# ------------------------------------------------------------------- intervalo


class _RelojFalso:
    def __init__(self):
        self.t = 0.0
        self.esperas = []

    def __call__(self):
        return self.t

    def dormir(self, segundos):
        self.esperas.append(segundos)
        self.t += segundos


@pytest.mark.parametrize("intervalo", [10.0, 180.0])
def test_el_intervalo_configurado_se_mantiene(db, tmp_path, intervalo):
    from app.services.price_list_send_service import Pendiente, PriceListCampaignRunner

    pdf = tmp_path / "lista1.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    reloj = _RelojFalso()
    envíos = _EnviosFalsos()
    pendientes = [
        Pendiente(client_id=indice, nombre=f"C{indice}", telefono=f"54911530886{indice}")
        for indice in range(1, 4)
    ]

    runner = PriceListCampaignRunner(
        clave="lista1-lista1-20261027-1000",
        pdf_path=pdf,
        pendientes=pendientes,
        usuario=None,
        envios=envíos,
        instance_id="instancia-prueba",
        intervalo=intervalo,
        lote_inicial=0,
        dormir=reloj.dormir,
        reloj=reloj,
        azar=lambda _a, _b: 0.0,
    )
    runner.run()

    assert len(envíos.enviados) == 3
    # El motor espera después de cada envío; lo que importa es que nunca sea menos del intervalo.
    assert len(reloj.esperas) >= 2
    assert all(espera >= intervalo for espera in reloj.esperas)
