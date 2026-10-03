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
        ProductionContrastService.receipt_lines(DAY)
        ProductionContrastService.part_lines(DAY)

    assert (
        RawMaterialReceipt.select().count(),
        ProductionPart.select().count(),
    ) == antes


def test_detalles_de_recepciones_y_partes(db):
    _receipt(DAY, "41043", "22.54", "9249.00", comp="000000046238", proveedor="KLEM JORGE")
    product = _product()
    _confirmed_part(product, 60, shift="Tarde")

    receipts = ProductionContrastService.receipt_lines(DAY)
    assert len(receipts) == 1
    assert receipts[0][0] == "KLEM JORGE"
    assert receipts[0][2] == Decimal("41043")

    partes = ProductionContrastService.part_lines(DAY)
    assert len(partes) == 1
    assert partes[0][0] == "Tarde"
    assert partes[0][1] == "Confirmado"
    assert partes[0][3] == 60
    assert partes[0][4] == Decimal("1500.00")


_QAPP = None


def _page(db):
    """Construye la pantalla real.

    Importa y construye la pagina a proposito: un error en su constructor
    (por ejemplo pasarle el widget padre a FormFeedback en vez de un nombre)
    revienta la ventana entera y se lleva por delante dozens de tests de la
    barra lateral que construyen la app entera.
    """
    global _QAPP
    from PyQt5.QtCore import QDate
    from PyQt5.QtWidgets import QApplication

    from app.ui.production_contrast import ProductionContrastPage

    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    page = ProductionContrastPage()
    page.day.setDate(QDate(DAY.year, DAY.month, DAY.day))
    page.refresh()
    return page


def test_la_pantalla_se_construye_y_muestra_el_contraste(db):
    _receipt(DAY, "41043", "22.54", "9249.00", proveedor="KLEM JORGE")
    product = _product()
    _confirmed_part(product, 60)

    page = _page(db)

    resumen = page.summary.text()
    assert "41,043" in resumen
    assert "9,249.00" in resumen
    assert "1,500.00" in resumen
    assert "3.65" in resumen
    assert page.receipts_table.rowCount() == 1
    assert page.parts_table.rowCount() == 1
    assert "no registra cuantos kilos entraron al proceso" in page.assumption_note.text()


def test_la_pantalla_avisa_cuando_no_hay_que_comparar(db):
    page = _page(db)

    assert "sin tickets importados" in page.summary.text()
    assert "No hay tickets importados" in page.assumption_note.text()
    assert page.receipts_table.rowCount() == 0


def test_la_pantalla_avisa_los_borradores_que_no_cuentan(db):
    _receipt(DAY, "41043", "22.54", "9249.00")
    product = _product()
    ProductionPartService.create(
        production_date=DAY, shift="Mañana", lines=[(product, 60)]
    )

    page = _page(db)

    assert "1 parte(s) en borrador" in page.assumption_note.text()
    assert "1,500.00" not in page.summary.text()
