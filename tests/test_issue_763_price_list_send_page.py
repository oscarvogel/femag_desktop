"""Pantalla de envío de lista de precios (#705, Fase B, etapa 3)."""

from __future__ import annotations


def _cliente(nombre, cuit, lista=1, phone=None):
    from app.models.masters import Client

    return Client.create(
        name=nombre,
        cuit=cuit,
        iva_condition="RI",
        phone=phone,
        lista_precios=lista,
    )


def _pagina():
    from PyQt5.QtWidgets import QApplication

    from app.ui.price_list_send_page import PriceListSendPage

    app = QApplication.instance() or QApplication([])
    pagina = PriceListSendPage(user=None, current_user="prueba-763")
    app.processEvents()
    return app, pagina


def test_la_pagina_calcula_los_destinatarios_de_la_lista(db):
    _cliente("Con celular", "30705000016", 1, "011 15 53088679")
    _cliente("Posible", "30705000017", 1, "011 3511 1221")
    _cliente("Sin telefono", "30705000018", 1, None)
    _cliente("De otra lista", "30705000019", 2, "011 15 53088680")
    app, pagina = _pagina()

    pagina._calcular_destinatarios()
    app.processEvents()

    assert pagina.destinatarios_table.rowCount() == 3
    assert "3 clientes de la lista" in pagina.contadores_label.text()
    assert "1 marcados para enviar" in pagina.contadores_label.text()
    # La columna "Número a enviar" muestra el número normalizado, no el de la base.
    assert pagina.destinatarios_table.item(0, 3).text() == "5491153088679"
    assert pagina.destinatarios_table.item(0, 1).text() == "Con celular"


def test_los_posibles_no_van_marcados(db):
    from PyQt5.QtCore import Qt

    _cliente("Con celular", "30705000016", 1, "011 15 53088679")
    _cliente("Posible", "30705000017", 1, "011 3511 1221")
    app, pagina = _pagina()

    pagina._calcular_destinatarios()
    app.processEvents()

    marcas = [
        pagina.destinatarios_table.item(fila, 0).checkState()
        for fila in range(pagina.destinatarios_table.rowCount())
    ]
    assert Qt.Checked in marcas
    assert marcas.count(Qt.Unchecked) == 1


def test_el_boton_de_enviar_pide_confirmacion_y_pdf(db, tmp_path):
    from PyQt5.QtCore import Qt

    _cliente("Con celular", "30705000016", 1, "011 15 53088679")
    app, pagina = _pagina()
    pagina._calcular_destinatarios()
    app.processEvents()

    # Sin el tilde de confirmación, el botón no se habilita.
    assert pagina.enviar_button.isEnabled() is False

    pagina.confirmacion_check.setChecked(True)
    app.processEvents()
    # Tampoco sin el PDF de la lista.
    assert pagina.enviar_button.isEnabled() is False

    pdf = tmp_path / "lista1.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    pagina.pdf_input.setText(str(pdf))
    pagina._refrescar_boton_enviar()
    app.processEvents()

    assert pagina.enviar_button.isEnabled() is True


def test_el_mensaje_de_la_lista_se_guarda_y_se_recupera(db, tmp_path):
    pdf = tmp_path / "lista1.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    app, pagina = _pagina()
    pagina.mensaje_input.setPlainText("Hola {cliente}, lista {lista} de {empresa}.")
    pagina.pdf_input.setText(str(pdf))

    pagina._guardar_configuracion()
    app.processEvents()

    from app.services.price_list_campaign_service import PriceListCampaignService

    config = PriceListCampaignService.config(1)
    assert config.mensaje == "Hola {cliente}, lista {lista} de {empresa}."
    assert config.pdf_path == str(pdf.resolve())
    assert config.mensaje_para("BAREIRO") == "Hola BAREIRO, lista 1 de FEMAG."


def test_la_pagina_no_se_comprime_en_pantallas_bajas(db):
    from app.ui.desktop_app import _scrollable_page

    app, pagina = _pagina()
    scroll = _scrollable_page(pagina, "priceListSendScrollArea")
    scroll.resize(1366, 700)
    app.processEvents()

    # El contenido conserva su alto y el scroll area es el que deja recorrido.
    assert scroll.widget().height() >= scroll.viewport().height()
    assert pagina.destinatarios_table.height() > 0
    assert pagina.enviar_button.height() > 0


def test_el_boton_de_modo_prueba_baja_el_intervalo(db):
    app, pagina = _pagina()

    pagina._usar_velocidad_de_prueba()
    app.processEvents()

    assert pagina.intervalo_spin.value() == 10
