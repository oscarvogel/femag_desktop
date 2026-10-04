"""Contraste entre fecula teorica y fecula real (#572, slice 3).

La pregunta que responde: entramos X kilos de mandioca, el legacy estima que
rendiran Y kilos de fecula, y cuanto se embolso de verdad.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.masters import Product
from app.models.production import ProductionPart, RawMaterialReceipt
from app.services.production_contrast_service import ProductionContrastService
from app.services.production_part_service import ProductionPartService

DAY = date(2026, 10, 2)


def _receipt(day, payable, rinde_pct, teorica, comp="000000046238", proveedor="KLEM JORGE"):
    return RawMaterialReceipt.create(
        source_key=f"femagfab:{comp}", source_comp=comp,
        source_hash="a" * 64, received_at=datetime.combine(day, datetime.min.time()),
        supplier_code="0999", supplier_name=proveedor, product_code="01",
        product_name="MANDIOCA 1 AÃ‘O BLANCA",
        gross_kg=Decimal(payable) + Decimal("2000"), tare_kg=Decimal("2000"),
        net_kg=Decimal(payable), payable_kg=Decimal(payable),
        yield_average=Decimal(rinde_pct), theoretical_starch_kg=Decimal(teorica),
        source_payload="{}",
    )


def _product(name="BOLSAS DE FECULA NATIVA", weight="25.000"):
    return Product.create(
        name=name, unit="unidad", peso_unitario_kg=Decimal(weight), active=True
    )


def _confirmed_part(product, bags, shift="MaÃ±ana"):
    part = ProductionPartService.create(
        production_date=DAY, shift=shift, lines=[(product, bags)]
    )
    return ProductionPartService.confirm(part, current_user="operador1")


def test_contraste_completo(db):
    """El caso delå±: se recibio, se estimo y se embolso."""
    _receipt(DAY, "41043", "22.54", "9249.00")
    product = _product()
    _confirmed_part(product, 60, shift="MaÃ±ana")  # 60 x 25 = 1500 kg

    c = ProductionContrastService.for_day(DAY)

    assert c.received_tickets == 1
    assert c.received_kg == Decimal("41043")
    assert c.theoretical_yield_pct == Decimal("22.54")
    assert c.theoretical_starch_kg == Decimal("9249.00")
    assert c.real_starch_kg == Decimal("1500.00")
    assert c.real_bags == 60
    assert c.real_parts == 1
    assert c.real_yield_pct == Decimal("3.65")
    assert c.deviation_kg == Decimal("-7749.00")
    assert c.deviation_pct == Decimal("-83.78")


def test_el_rinde_teorico_se_pondera_por_kilos(db):
    """No es el promedio simple: pesa mas el ticket que mas kilos trajo."""
    _receipt(DAY, "1000", "10.00", "100.00", comp="1")
    _receipt(DAY, "9000", "30.00", "2700.00", comp="2")

    c = ProductionContrastService.for_day(DAY)

    # (1000x10 + 9000x30) / 10000 = 28.00
    assert c.received_kg == Decimal("10000")
    assert c.theoretical_yield_pct == Decimal("28.00")
    assert c.theoretical_starch_kg == Decimal("2800.00")


def test_sin_recepciones_no_hay_teoria_ni_rinde_real(db):
    product = _product()
    _confirmed_part(product, 10)

    c = ProductionContrastService.for_day(DAY)

    assert c.received_kg == Decimal("0.00")
    assert c.theoretical_starch_kg == Decimal("0.00")
    assert c.theoretical_yield_pct == Decimal("0.00")
    assert c.real_starch_kg == Decimal("250.00")
    # Sin mandioca recibida no se puede decir que rinde: mejor no inventar.
    assert c.real_yield_pct is None
    assert c.deviation_kg is None
    assert not c.has_receipts


def test_sin_produccion_confirmada_no_hay_rinde_real(db):
    _receipt(DAY, "41043", "22.54", "9249.00")

    c = ProductionContrastService.for_day(DAY)

    assert c.has_receipts
    assert not c.has_confirmed_production
    assert c.real_yield_pct == Decimal("0.00")


def test_un_parte_en_borrador_no_cuenta_como_real(db):
    """Un borrador se puede seguir modificando: no es produccion real todavia."""
    _receipt(DAY, "41043", "22.54", "9249.00")
    product = _product()
    borrador = ProductionPartService.create(
        production_date=DAY, shift="MaÃ±ana", lines=[(product, 60)]
    )

    c = ProductionContrastService.for_day(DAY)

    assert c.real_starch_kg == Decimal("0.00")
    assert c.pending_parts == 1
    assert c.real_parts == 0

    ProductionPartService.confirm(borrador, current_user="operador1")
    assert ProductionContrastService.for_day(DAY).real_starch_kg == Decimal("1500.00")


def test_un_parte_anulado_no_cuenta(db):
    _receipt(DAY, "41043", "22.54", "9249.00")
    product = _product()
    parte = _confirmed_part(product, 60)
    ProductionPartService.annul(parte, current_user="supervisor", reason="Error")

    c = ProductionContrastService.for_day(DAY)

    assert c.real_starch_kg == Decimal("0.00")
    assert c.real_parts == 0
    assert c.pending_parts == 0


def test_el_contraste_es_de_solo_lectura(db):
    """Consultar el contraste no puede crear ni modificar nada."""
    _receipt(DAY, "41043", "22.54", "9249.00")
    product = _product()
    _confirmed_part(product, 60)
    antes = (
        RawMaterialReceipt.select().count(),
        ProductionPart.select().count(),
    )

    for _ in range(3):
        ProductionContrastService.for_day(DAY)
        ProductionContrastService.for_month(DAY)
        ProductionContrastService.receipt_lines(DAY, DAY)
        ProductionContrastService.part_lines(DAY, DAY)

    assert (
        RawMaterialReceipt.select().count(),
        ProductionPart.select().count(),
    ) == antes


def test_detalles_de_recepciones_y_partes(db):
    _receipt(DAY, "41043", "22.54", "9249.00", comp="000000046238", proveedor="KLEM JORGE")
    product = _product()
    _confirmed_part(product, 60, shift="Tarde")

    receipts = ProductionContrastService.receipt_lines(DAY, DAY)
    assert len(receipts) == 1
    assert receipts[0][0] == "KLEM JORGE"
    assert receipts[0][2] == Decimal("41043")

    partes = ProductionContrastService.part_lines(DAY, DAY)
    assert len(partes) == 1
    assert partes[0][0] == DAY
    assert partes[0][1] == "Tarde"
    assert partes[0][2] == "Confirmado"
    assert partes[0][4] == 60
    assert partes[0][5] == Decimal("1500.00")


def test_el_mes_agrega_todo_y_el_dia_no(db):
    """Decidido con el dueno: el mes es la media que sirve.

    Como no se sabe en que dia se proceso la mandioca, el detalle diario mezcla
    dias distintos. Sumando el mes el desfase se promedia.
    """
    _receipt(date(2026, 10, 1), "10000", "20.00", "2000.00", comp="1")
    _receipt(date(2026, 10, 15), "30000", "30.00", "9000.00", comp="2")
    _receipt(date(2026, 11, 3), "50000", "25.00", "12500.00", comp="3")
    product = _product()
    parte = ProductionPartService.create(
        production_date=date(2026, 10, 20), shift="Mañana", lines=[(product, 200)]
    )
    ProductionPartService.confirm(parte, current_user="operador1")

    mes = ProductionContrastService.for_month(date(2026, 10, 2))
    # El ticket de noviembre NO entra en el mes de octubre.
    assert mes.start == date(2026, 10, 1)
    assert mes.end == date(2026, 10, 31)
    assert mes.is_month
    assert mes.label == "10/2026"
    assert mes.received_kg == Decimal("40000")
    assert mes.received_tickets == 2
    assert mes.theoretical_starch_kg == Decimal("11000.00")
    assert mes.real_starch_kg == Decimal("5000.00")
    # (10000x20 + 30000x30) / 40000 = 27.50
    assert mes.theoretical_yield_pct == Decimal("27.50")
    assert mes.real_yield_pct == Decimal("12.50")
    assert mes.deviation_kg == Decimal("-6000.00")

    dia = ProductionContrastService.for_day(date(2026, 10, 20))
    assert not dia.is_month
    # El dia solo ve su parte: no hay tickets importados ese dia.
    assert dia.received_kg == Decimal("0.00")
    assert dia.real_starch_kg == Decimal("5000.00")
    assert dia.real_yield_pct is None


def test_los_limites_del_mes_son_correctos_en_diciembre(db):
    primero, fin = ProductionContrastService.month_bounds(date(2026, 12, 17))
    assert primero == date(2026, 12, 1)
    assert fin == date(2026, 12, 31)

    primero, fin = ProductionContrastService.month_bounds(date(2027, 1, 1))
    assert primero == date(2027, 1, 1)
    assert fin == date(2027, 1, 31)


_QAPP = None


def _page(db, periodo="Mes", dia=DAY):
    """Construye la pantalla real.

    Importa y construye la pagina a proposito: un error en su constructor
    (por ejemplo pasarle el widget padre a FormFeedback en vez de un nombre)
    revienta la ventana entera y se lleva por delante decenas de tests de la
    barra lateral que construyen la app entera.
    """
    global _QAPP
    from PyQt5.QtCore import QDate
    from PyQt5.QtWidgets import QApplication

    from app.ui.production_contrast import PERIODO_DIA, PERIODO_MES, ProductionContrastPage

    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    page = ProductionContrastPage()
    page.period.setCurrentText(PERIODO_DIA if periodo == "Dia" else PERIODO_MES)
    page.day.setDate(QDate(dia.year, dia.month, dia.day))
    page.refresh()
    return page


def _tarjeta(page, clave) -> tuple[str, str]:
    valor, ayuda = page.kpis[clave]
    return valor.text(), ayuda.text()


def test_la_pantalla_se_construye_y_muestra_el_contraste(db):
    _receipt(DAY, "41043", "22.54", "9249.00", proveedor="KLEM JORGE")
    product = _product()
    _confirmed_part(product, 60)

    page = _page(db, periodo="Dia")

    valor, ayuda = _tarjeta(page, "mandioca")
    assert valor == "41,043 kg"
    assert "1 ticket(s)" in ayuda

    valor, _ = _tarjeta(page, "teorica")
    assert valor == "9,249.00 kg"

    valor, _ = _tarjeta(page, "real")
    assert valor == "1,500.00 kg"

    valor, _ = _tarjeta(page, "rinde")
    assert valor == "3.65 %"

    valor, _ = _tarjeta(page, "desvio")
    assert valor == "-7,749.00 kg"

    assert page.receipts_table.rowCount() == 1
    assert page.parts_table.rowCount() == 1
    assert "no se procesa el mismo día que llega" in page.nota.text()


def test_la_pantalla_usa_el_mes_por_defecto(db):
    """El mes es el periodo que sirve: tiene que venir elegido.

    El texto que se verifica aca cambio en #639. Antes decia "el mes es la media
    que sirve", y era falso: medido sobre los tickets reales, el 7,2 % de la
    mandioca de cada mes entra en los ultimos dias y se procesa al mes siguiente,
    asi que el mes cierra subestimando su rinde. El texto nuevo lo dice y
    cuantifica.
    """
    page = _page(db, periodo="Mes")

    assert page.period.currentText() == "Mes"
    assert "no hay desfase de cierre" in page.nota.text()

def test_la_pantalla_avisa_cuando_no_hay_que_comparar(db):
    page = _page(db)

    valor, ayuda = _tarjeta(page, "rinde")
    assert valor == "-"
    assert "sin mandioca recibida" in ayuda
    valor, ayuda = _tarjeta(page, "desvio")
    assert valor == "-"
    assert "sin teoría" in ayuda
    assert "No hay tickets importados" in page.nota.text()
    assert page.receipts_table.rowCount() == 0


def test_la_pantalla_avisa_los_borradores_que_no_cuentan(db):
    _receipt(DAY, "41043", "22.54", "9249.00")
    product = _product()
    ProductionPartService.create(
        production_date=DAY, shift="Mañana", lines=[(product, 60)]
    )

    page = _page(db)

    assert "1 parte(s) en borrador" in page.nota.text()
    valor, _ = _tarjeta(page, "real")
    assert valor == "0.00 kg"


# --------------------------------------------------------------- #639 borde
# El material que entra los ultimos dias del mes se procesa al mes siguiente, asi
# que no se promedia dentro del mes: el mes cierra subestimando su rinde y el
# siguiente lo infla. Medido sobre los tickets reales (mar-oct 2026), es el 7,2 %
# de la recepcion mensual en promedio y el 26 % en abril.
#
# Abajo se reproduce esa magnitud con datos sinteticos. Las cifras estan en el
# issue #639.


ABRIL = date(2026, 4, 30)   # 30 dias: el borde son los dias 28, 29 y 30
MAYO = date(2026, 5, 20)    # 31 dias: el borde son los dias 29, 30 y 31


def test_el_borde_del_mes_suma_la_mandioca_de_los_ultimos_dias(db):
    """Abril: 30 % de lo recibido cae en los ultimos 3 dias."""
    _receipt(date(2026, 4, 1), "70000", "22.50", "15750.00", comp="A1")
    _receipt(ABRIL, "30000", "22.50", "6750.00", comp="A2")

    c = ProductionContrastService.for_month(ABRIL)

    assert c.received_kg == Decimal("100000")
    assert c.border_kg == Decimal("30000.00")
    assert c.border_pct == Decimal("30.0")
    assert c.border_days == 3


def test_un_mes_sin_material_de_borde_no_tiene_desfase_de_cierre(db):
    """Mayo: el material entra pronto y el mes cierra sin cola."""
    _receipt(date(2026, 5, 2), "80000", "22.50", "18000.00", comp="B1")
    _receipt(date(2026, 5, 20), "20000", "22.50", "4500.00", comp="B2")

    c = ProductionContrastService.for_month(MAYO)

    assert c.received_kg == Decimal("100000")
    assert c.border_kg == Decimal("0.00")
    assert c.border_pct == Decimal("0.0")


def test_el_borde_de_un_mes_de_31_dias_llega_hasta_el_31(db):
    """Mayo tiene 31 dias, asi que el borde arranca el 29 y no el 28."""
    _receipt(date(2026, 5, 28), "10000", "22.50", "2250.00", comp="C1")
    _receipt(date(2026, 5, 29), "40000", "22.50", "9000.00", comp="C2")

    c = ProductionContrastService.for_month(MAYO)

    assert c.border_kg == Decimal("40000.00")
    assert c.border_pct == Decimal("80.0")


def test_un_dia_no_tiene_material_de_borde(db):
    """En un dia todo el material es de borde, asi que el porcentaje no aplica."""
    _receipt(DAY, "41043", "22.54", "9249.00")

    c = ProductionContrastService.for_day(DAY)

    assert c.border_kg == Decimal("0.00")
    assert c.border_pct is None


def test_la_pantalla_cuantifica_el_material_de_borde(db):
    """La nota dice cuantos kg quedan para el mes siguiente, no solo que existen."""
    _receipt(date(2026, 4, 1), "70000", "22.50", "15750.00", comp="D1")
    _receipt(ABRIL, "30000", "22.50", "6750.00", comp="D2")

    page = _page(db, periodo="Mes", dia=ABRIL)

    nota = page.nota.text()
    assert "30,000 kg de mandioca" in nota
    assert "30.0 %" in nota
    assert "subestima su rinde" in nota
    # Y no puede decir que el mes promedia, porque no es asi (#639).
    assert "el mes es la media que sirve" not in nota
