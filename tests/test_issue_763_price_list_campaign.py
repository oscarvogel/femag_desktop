"""Configuración y audiencia de la campaña de lista de precios (#705 Fase B, issue #763)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _cliente(nombre="Cliente 763", cuit="30705000016", lista=1, phone=None, activo=True):
    from app.models.masters import Client

    return Client.create(
        name=nombre,
        cuit=cuit,
        iva_condition="RI",
        phone=phone,
        lista_precios=lista,
        active=activo,
    )


def _pdf(tmp_path, nombre="lista1.pdf"):
    """Un PDF falso pero con el tamaño de un PDF de verdad."""
    ruta = tmp_path / nombre
    ruta.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return ruta


def _servicio():
    from app.services.price_list_campaign_service import PriceListCampaignService

    return PriceListCampaignService


# ------------------------------------------------------------------ configuración


def test_sin_configurar_no_hay_pdf_ni_mensaje(db):
    config = _servicio().config(1)

    assert config.lista == 1
    assert config.pdf_path == ""
    assert config.tiene_pdf is False
    assert config.empresa == "FEMAG"


def test_el_pdf_y_el_mensaje_va_por_lista(db, tmp_path):
    servicio = _servicio()
    pdf = _pdf(tmp_path, "lista1.pdf")

    servicio.guardar(1, pdf_path=str(pdf), mensaje="Mensaje para la lista 1")

    assert servicio.config(1).pdf_path == str(pdf.resolve())
    assert servicio.config(1).mensaje == "Mensaje para la lista 1"
    # La lista 2 no tiene PDF: el PDF de otra lista no se puede mandar por accidente.
    assert servicio.config(2).tiene_pdf is False
    assert servicio.config(2).mensaje == ""


def test_guardar_sin_pdf_deja_la_configuracion_parcial(db, tmp_path):
    servicio = _servicio()

    config = servicio.guardar(2, mensaje="Solo el mensaje")

    assert config.tiene_pdf is False
    assert config.mensaje == "Solo el mensaje"


def test_el_pdf_invalido_se_rechaza_con_motivo(db, tmp_path):
    from app.services.price_list_campaign_service import CampaignConfigError

    servicio = _servicio()
    no_existe = tmp_path / "no-existe.pdf"
    planilla = tmp_path / "lista.xlsx"
    planilla.write_text("no soy un pdf", encoding="utf-8")
    vacio = tmp_path / "vacio.pdf"
    vacio.write_bytes(b"")

    for ruta, motivo in (
        (no_existe, "No existe el PDF"),
        (planilla, "tiene que ser un PDF"),
        (vacio, "está vacío"),
        (tmp_path, "no es un archivo"),
    ):
        with pytest.raises(CampaignConfigError) as error:
            servicio.validar_pdf(ruta)
        assert motivo in str(error.value)

    with pytest.raises(CampaignConfigError) as error:
        servicio.validar_pdf("")
    assert "Elegí el PDF" in str(error.value)


def test_la_lista_tiene_que_ser_de_1_a_4(db):
    from app.services.price_list_campaign_service import CampaignConfigError

    with pytest.raises(CampaignConfigError):
        _servicio().config(5)
    with pytest.raises(CampaignConfigError):
        _servicio().guardar(0, mensaje="x")


def test_el_mensaje_sustituye_las_variables(db, tmp_path):
    servicio = _servicio()
    servicio.guardar(
        1,
        pdf_path=str(_pdf(tmp_path)),
        mensaje="Hola {cliente}, aqui va la lista {lista} de {empresa}. Gracias.",
    )

    mensaje = servicio.config(1).mensaje_para("BAREIRO JAVIER")

    assert mensaje == "Hola BAREIRO JAVIER, aqui va la lista 1 de FEMAG. Gracias."


def test_sin_mensaje_propio_se_usa_el_default(db):
    mensaje = _servicio().config(2).mensaje_para("GIMENEZ ROMINA JAQUELINE")

    assert "{cliente}" not in mensaje
    assert "GIMENEZ ROMINA JAQUELINE" in mensaje
    assert "lista de precios 2" in mensaje


def test_la_empresa_se_puede_cambiar(db):
    servicio = _servicio()

    servicio.guardar(1, mensaje="Hola {cliente}, de {empresa}.", empresa="FEMAG S.A.")

    config = servicio.config(1)
    assert config.empresa == "FEMAG S.A."
    assert config.mensaje_para("Un Cliente") == "Hola Un Cliente, de FEMAG S.A.."


# ---------------------------------------------------------------------- audiencia


def test_la_audiencia_toma_solo_la_lista_elegida(db):
    servicio = _servicio()
    _cliente(nombre="De la lista 1", cuit="30705000016", lista=1, phone="011 15 53088679")
    _cliente(nombre="De la lista 2", cuit="30705000017", lista=2, phone="011 15 53088680")
    _cliente(nombre="De la lista 3", cuit="30705000018", lista=3, phone="011 15 53088681")

    audiencia = servicio.calcular_audiencia(1)

    assert [d.nombre for d in audiencia.destinatarios] == ["De la lista 1"]
    assert audiencia.lista == 1


def test_solo_los_celulares_van_marcados(db):
    servicio = _servicio()
    _cliente(nombre="Celular", cuit="30705000016", lista=1, phone="011 15 53088679")
    _cliente(nombre="Posible", cuit="30705000017", lista=1, phone="011 3511 1221")
    _cliente(nombre="Fijo con letras", cuit="30705000018", lista=1, phone="TTE.SERVIBAIRES LARRAZABAL2562")
    _cliente(nombre="Sin telefono", cuit="30705000019", lista=1, phone=None)

    audiencia = servicio.calcular_audiencia(1)
    por_nombre = {d.nombre: d for d in audiencia.destinatarios}

    assert por_nombre["Celular"].marcado is True
    assert por_nombre["Celular"].telefono_normalizado == "5491153088679"
    # El "posible" se ve, con el número que se mandaría, pero NO se manda solo.
    assert por_nombre["Posible"].marcado is False
    assert por_nombre["Posible"].telefono_normalizado == "5491135111221"
    assert por_nombre["Fijo con letras"].marcado is False
    assert por_nombre["Sin telefono"].marcado is False

    assert audiencia.a_enviar == 1
    assert audiencia.contadores()["celulares"] == 1
    assert audiencia.contadores()["posibles"] == 1
    assert audiencia.contadores()["invalidos"] == 1
    assert audiencia.contadores()["sin_telefono"] == 1
    assert audiencia.contadores()["total"] == 4


def test_los_posibles_se_marcan_si_el_operador_lo_pide(db):
    servicio = _servicio()
    _cliente(nombre="Posible", cuit="30705000017", lista=1, phone="011 3511 1221")

    audiencia = servicio.calcular_audiencia(1, marcar_posibles=True)

    assert audiencia.a_enviar == 1
    assert audiencia.destinatarios[0].marcado is True


def test_los_omitidos_traen_el_motivo(db):
    servicio = _servicio()
    _cliente(nombre="Sin telefono", cuit="30705000016", lista=1, phone="")
    _cliente(nombre="Dos numeros", cuit="30705000017", lista=1, phone="3404 633133 - 3404 634132")

    audiencia = servicio.calcular_audiencia(1)
    por_nombre = {d.nombre: d for d in audiencia.destinatarios}

    assert "no tiene teléfono" in por_nombre["Sin telefono"].motivo
    assert "más de un teléfono" in por_nombre["Dos numeros"].motivo
    assert por_nombre["Dos numeros"].enviable is False


def test_los_inactivos_se_cuentan_como_omitidos(db):
    servicio = _servicio()
    _cliente(nombre="Activo", cuit="30705000016", lista=1, phone="011 15 53088679")
    _cliente(nombre="Inactivo", cuit="30705000017", lista=1, phone="011 15 53088680", activo=False)

    audiencia = servicio.calcular_audiencia(1)

    assert [d.nombre for d in audiencia.destinatarios] == ["Activo"]
    assert audiencia.inactivos_omitidos == 1
    assert audiencia.contadores()["inactivos_omitidos"] == 1


def test_la_audiencia_de_una_lista_vacia_no_falla(db):
    audiencia = _servicio().calcular_audiencia(3)

    assert audiencia.total == 0
    assert audiencia.a_enviar == 0
    assert audiencia.contadores()["total"] == 0
