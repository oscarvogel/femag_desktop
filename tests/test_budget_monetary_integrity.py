"""Regresión de integridad monetaria de presupuestos (hotfix 000073).

Caso reportado en producción: PRES-000073 / OC-000051.

El PDF mostraba un detalle cuya suma era 37.511.775 y un TOTAL de
37.511.800: $25 de diferencia entre lo que el usuario puede calcular a
partir de los renglones visibles y el total del documento.

Invariante que no se negocia:

    TOTAL_DOCUMENTO == SUM(TOTAL_RENGLON)

y cada total de renglón debe ser coherente con los valores visibles
(cantidad, precio unitario, descuento, IVA, total).

Regla: LO MOSTRADO = LO CALCULADO = LO PERSISTIDO = LO COBRADO.
"""

from decimal import Decimal

import pytest
from pytest import approx

from app.models.accounting import ClientAccountMovement
from app.models.budgets import Budget, BudgetItem
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
from app.services.account_ledger_service import AccountLedgerService
from app.services.budget_print_service import BudgetPrintService
from app.services.budget_service import BudgetService
from app.services.ledger_query_service import client_balance
from app.services.load_order_service import LoadOrderService
from app.services.money import MonetaryIntegrityError

# Detalle exacto del presupuesto 000073 reportado en producción.
CASO_000073 = [
    ("PACK 10 UNID. ALM. MAIZ X 1/2 KG", 5, "9639.00", "48195.00"),
    ("BOLSAS DE FECULA NATIVA", 840, "37485.00", "31487400.00"),
    ("PACK 10 UNID. FECULA X 1 KG", 310, "19278.00", "5976180.00"),
]
SUMA_DETALLE_000073 = Decimal("37511775.00")
TOTAL_IMPRESO_000073 = Decimal("37511800.00")


def _money_iva(porcentaje="0"):
    return TipoIVA.create(nombre=f"IVA {porcentaje}", porcentaje=porcentaje)


def _base_data(iva_porcentaje="0", descuento_cliente="0"):
    iva = _money_iva(iva_porcentaje)
    carrier = Carrier.create(name="Transportista 73", cuit="30777777770")
    driver = Driver.create(name="Chofer 73", carrier=carrier)
    truck = Truck.create(domain="PRES73", carrier=carrier)
    client = Client.create(
        name="CARDOZO MAURICIO GUSTAVO",
        cuit="30712345678",
        iva_condition="RI",
        lista_precios=1,
        descuento_porcentaje=descuento_cliente,
    )
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12",
        is_primary=True,
    )
    return iva, carrier, driver, truck, client, address


def _make_order(client, address, carrier, driver, truck, iva, lines):
    """Crea una orden con los renglones indicados.

    ``lines`` es una lista de tuplas ``(nombre, cantidad, precio, iva,
    descuento_porcentaje)`` donde ``iva`` es un ``TipoIVA``. Si el descuento se
    omite se usa 0.
    """
    products = []
    payloads = []
    for line in lines:
        name, quantity, price, product_iva = line[:4]
        discount = line[4] if len(line) > 4 else "0"
        products.append(
            Product.create(
                name=name,
                unit="bolsa",
                precio_neto_base=float(Decimal(price)),
                tipo_iva=product_iva or iva,
            )
        )
        payloads.append(
            {
                "product": None,
                "quantity": float(Decimal(quantity)),
                "descuento_porcentaje": float(Decimal(discount)),
            }
        )
    for payload, product in zip(payloads, products):
        payload["product"] = product
    return LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": payloads,
            }
        ],
        pallets=[],
    )


def _order_000073(iva_porcentaje="0"):
    iva, carrier, driver, truck, client, address = _base_data(iva_porcentaje)
    lines = [
        (name, quantity, price, iva)
        for name, quantity, price, _shown in CASO_000073
    ]
    order = _make_order(client, address, carrier, driver, truck, iva, lines)
    return order, client


def _sum_item_totals(budget):
    return sum((Decimal(str(item.total)) for item in budget.items), Decimal("0.00"))


# ---------------------------------------------------------------------------
# 1) CASO REPORTADO: 000073
# ---------------------------------------------------------------------------


def test_budget_000073_detalle_y_total_coinciden(db):
    """El detalle del 000073 debe sumar exactamente el total del documento.

    Nunca 37.511.800 para ese detalle visible.
    """
    order, _client = _order_000073()
    budget = BudgetService(current_user="admin").ensure_for_load_order(order)[0]

    assert _sum_item_totals(budget) == SUMA_DETALLE_000073
    assert budget.total_amount == SUMA_DETALLE_000073
    assert budget.total_amount != TOTAL_IMPRESO_000073


def test_budget_000073_cada_renglon_es_consistente_con_cantidad_y_precio(db):
    """Cada renglón debe cumplir total == cantidad * precio visible."""
    order, _client = _order_000073()
    budget = BudgetService(current_user="admin").ensure_for_load_order(order)[0]
    items = list(budget.items.order_by(BudgetItem.id))
    assert len(items) == 3
    for item, (name, quantity, price, shown_total) in zip(items, CASO_000073):
        assert item.product.name == name
        assert Decimal(str(item.quantity)) == Decimal(str(quantity))
        assert Decimal(str(item.unit_price)) == Decimal(price)
        assert Decimal(str(item.total)) == Decimal(shown_total)


def _presupuesto_historico_inconsistente(db):
    """Reproduce el presupuesto 000073 ya persistido e inconsistente.

    Cabecera almacenada 37.511.800,00 contra un detalle que suma
    37.511.775,00. La inconsistencia queda en la base: la impresión no debe
    corregirla, solo dejar de bloquearla.
    """
    order, client = _order_000073()
    AccountLedgerService(current_user="admin").generate_for_load_order(order)
    budget = BudgetService(current_user="admin").ensure_for_load_order(order)[0]

    budget.total_amount = float(TOTAL_IMPRESO_000073)
    budget.net_amount = float(TOTAL_IMPRESO_000073)
    budget.save(only=[Budget.total_amount, Budget.net_amount])
    return order, client, Budget.get_by_id(budget.id)


def test_historico_inconsistente_se_imprime_con_totales_del_detalle(db, tmp_path):
    """Un presupuesto histórico inconsistente DEBE poder imprimirse.

    El PDF usa como fuente de verdad los BudgetItem que se imprimen, así que
    el TOTAL visible es la suma exacta del detalle, no la cabecera almacenada.
    """
    _order, _client, budget = _presupuesto_historico_inconsistente(db)

    path = BudgetPrintService(current_user="admin").export_pdf(budget, tmp_path)

    assert path.exists(), "El presupuesto histórico no debe quedar bloqueado"
    assert path.stat().st_size > 0


def _pdf_text(path) -> str:
    """Extrae el texto visible del PDF.

    ReportLab comprime y codifica los streams, así que no alcanza con buscar
    bytes crudos. Se decodifica ASCII85 y luego FlateDecode para leer los
    operandos de texto reales que se imprimen.
    """
    import base64
    import re
    import zlib

    raw = path.read_bytes()
    chunks = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        payload = match.group(1).strip()
        decoded = None
        for decoder in (
            lambda data: zlib.decompress(base64.a85decode(data, adobe=True)),
            lambda data: zlib.decompress(data),
            lambda data: base64.a85decode(data, adobe=True),
        ):
            try:
                decoded = decoder(payload)
                break
            except Exception:
                continue
        chunks.append(
            (decoded if decoded is not None else payload).decode("latin-1", errors="ignore")
        )
    return "\n".join(chunks)


def test_historico_inconsistente_muestra_total_del_detalle_en_el_pdf(db, tmp_path):
    """El TOTAL del PDF debe ser 37.511.775,00 y no 37.511.800,00."""
    _order, _client, budget = _presupuesto_historico_inconsistente(db)

    path = BudgetPrintService(current_user="admin").export_pdf(budget, tmp_path)
    contenido = _pdf_text(path)

    assert "37,511,775.00" in contenido, f"No se encontró el total del detalle: {contenido}"
    assert "37,511,800.00" not in contenido, "No debe imprimirse la cabecera inconsistente"


def test_historico_inconsistente_no_modifica_la_base(db, tmp_path):
    """Imprimir un histórico no debe repararlo ni alterar la cuenta corriente."""
    order, client, budget = _presupuesto_historico_inconsistente(db)
    movimiento = ClientAccountMovement.get(ClientAccountMovement.budget == budget)
    total_movimiento = movimiento.total_amount
    saldo = client_balance(client)

    BudgetPrintService(current_user="admin").export_pdf(budget, tmp_path)

    budget_reload = Budget.get_by_id(budget.id)
    assert budget_reload.total_amount == approx(float(TOTAL_IMPRESO_000073), abs=0.005)
    assert budget_reload.net_amount == approx(float(TOTAL_IMPRESO_000073), abs=0.005)

    movimiento_reload = ClientAccountMovement.get(ClientAccountMovement.budget == budget)
    assert movimiento_reload.total_amount == approx(total_movimiento, abs=0.0001)
    assert client_balance(client) == approx(saldo, abs=0.0001)

    # El detalle tampoco se toca.
    assert _sum_item_totals(budget_reload) == SUMA_DETALLE_000073


def test_historico_inconsistente_registra_auditoria_con_diagnostico(db, tmp_path):
    """La impresión tolerada deja rastro con los importes de la diferencia."""
    from app.models.audit import AuditLog

    order, _client, budget = _presupuesto_historico_inconsistente(db)

    BudgetPrintService(current_user="admin").export_pdf(budget, tmp_path)

    registro = (
        AuditLog.select()
        .where(AuditLog.record_ref == f"Budget:{budget.id}")
        .where(AuditLog.action == "imprimir_historico_inconsistente")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert registro is not None
    assert "Presupuesto histórico inconsistente impreso usando totales derivados del detalle" in (
        registro.observation or ""
    )
    nuevo = registro.new_value or {}
    assert nuevo["budget_number"] == budget.budget_number
    assert nuevo["stored_total"] == approx(float(TOTAL_IMPRESO_000073), abs=0.005)
    assert nuevo["detail_total"] == approx(float(SUMA_DETALLE_000073), abs=0.005)
    # diferencia = detalle - almacenado = 37511775 - 37511800 = -25
    assert nuevo["difference"] == approx(-25.0, abs=0.005)
    assert nuevo["order_number"] == order.order_number


def test_historico_inconsistente_se_imprime_tambien_en_el_lote(db, tmp_path):
    """El bundle por orden tampoco debe bloquearse por un histórico inconsistente."""
    order, _client, budget = _presupuesto_historico_inconsistente(db)

    target = BudgetPrintService(current_user="admin").export_bundle_for_load_order(
        order, tmp_path
    )

    assert target.exists()
    assert target.stat().st_size > 0
    contenido = target.read_bytes().decode("latin-1", errors="ignore")
    assert "37511800" not in contenido


def test_guard_de_dominio_sigue_bloqueando_la_emision_de_datos_nuevos(db):
    """El guard NO se toca: sigue rechazando datos nuevos inconsistentes."""
    order, _client = _order_000073()
    budget = BudgetService(current_user="admin").ensure_for_load_order(order)[0]

    budget.total_amount = float(TOTAL_IMPRESO_000073)
    budget.save(only=[Budget.total_amount])

    with pytest.raises(MonetaryIntegrityError):
        BudgetService(current_user="admin").assert_monetary_integrity(budget)


def test_presupuesto_nuevo_consistente_se_imprime_sin_auditoria_de_historico(db, tmp_path):
    """Un presupuesto nuevo y consistente se imprime normal, sin marcarlo histórico."""
    from app.models.audit import AuditLog

    order, _client = _order_000073()
    budget = BudgetService(current_user="admin").ensure_for_load_order(order)[0]

    path = BudgetPrintService(current_user="admin").export_pdf(budget, tmp_path)

    assert path.exists()
    marcados = (
        AuditLog.select()
        .where(AuditLog.record_ref == f"Budget:{budget.id}")
        .where(AuditLog.action == "imprimir_historico_inconsistente")
        .count()
    )
    assert marcados == 0


# ---------------------------------------------------------------------------
# 2) PRECISIÓN MONETARIA: centavos, cantidades decimales, descuentos, IVA
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nombre,cantidad,precio,descuento,iva",
    [
        ("Precio con centavos", "3", "10.05", "0", "0"),
        ("Precio con centavos y 21%", "3", "10.05", "0", "21"),
        ("Cantidad decimal", "2.5", "100.11", "0", "21"),
        ("Cantidad decimal sin IVA", "2.5", "100.11", "0", "0"),
        ("Descuento 10 y IVA 21", "4", "1234.56", "10", "21"),
        ("Descuento 33.33", "7", "999.99", "33.33", "21"),
        ("Medio centavo", "1", "0.125", "0", "0"),
        ("Medio centavo con IVA", "1", "0.125", "0", "21"),
        ("Fraccion 1/3", "3", "0.01", "0", "21"),
        ("Cero con IVA", "5", "0", "0", "21"),
    ],
)
def test_total_siempre_igual_a_suma_de_renglones(db, nombre, cantidad, precio, descuento, iva):
    """Invariante central con precios, cantidades, descuentos e IVA variety."""
    iva_row, carrier, driver, truck, client, address = _base_data(iva)
    product = Product.create(
        name=nombre,
        unit="bolsa",
        precio_neto_base=float(Decimal(precio)),
        tipo_iva=iva_row,
    )
    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [
                    {
                        "product": product,
                        "quantity": float(Decimal(cantidad)),
                        "descuento_porcentaje": float(Decimal(descuento)),
                        "iva_porcentaje": float(Decimal(iva)),
                    }
                ],
            }
        ],
        pallets=[],
    )
    budget = BudgetService(current_user="admin").ensure_for_load_order(order)[0]

    assert _sum_item_totals(budget) == budget.total_amount
    assert sum((item.net_subtotal for item in budget.items), Decimal('0.00')) == budget.net_amount
    assert sum((item.vat_amount for item in budget.items), Decimal('0.00')) == budget.vat_amount


def test_multiples_renglones_con_precios_y_descuentos_distintos(db):
    """Varios renglones heterogéneos: el total debe ser la suma exacta."""
    iva, carrier, driver, truck, client, address = _base_data("21")
    lineas = [
        ("Producto A", "3", "1000.55", iva, "0"),
        ("Producto B", "7", "250.10", iva, "15"),
        ("Producto C", "12.5", "99.99", iva, "0"),
        ("Producto D", "1", "12345.67", iva, "5"),
    ]
    order = _make_order(
        client, address, carrier, driver, truck, iva, lineas
    )
    budget = BudgetService(current_user="admin").ensure_for_load_order(order)[0]

    assert len(list(budget.items)) == 4
    assert _sum_item_totals(budget) == budget.total_amount


# ---------------------------------------------------------------------------
# 3) FUENTE UNICA: orden de carga, presupuesto y cuenta corriente
# ---------------------------------------------------------------------------


def test_orden_presupuesto_y_cuenta_corriente_coinciden(db):
    """Lo persistido en la orden es lo mismo que va al presupuesto y al ledger."""
    order, client = _order_000073(iva_porcentaje="21")
    service = AccountLedgerService(current_user="admin")
    movements = service.generate_for_load_order(order)

    budget = Budget.get(Budget.client == client)
    assert len(movements) == 1
    movement = movements[0]
    # Con DECIMAL la comparación es exacta: no hace falta tolerancia.
    assert movement.total_amount == budget.total_amount
    assert movement.net_amount == budget.net_amount
    assert movement.vat_amount == budget.vat_amount
    assert client_balance(client) == approx(float(budget.total_amount), abs=0.005)


def test_presupuesto_manual_respeta_la_invariante(db):
    """El presupuesto manual usa la misma rutina de cálculo."""
    iva, _c, _d, _t, client, _a = _base_data("21")
    product = Product.create(
        name="Producto manual 73", unit="bolsa", precio_neto_base=1000.0, tipo_iva=iva
    )
    budget = BudgetService(current_user="admin").create_manual(
        client=client,
        items=[
            {
                "product": product,
                "quantity": 3,
                "unit": "bolsa",
                "unit_price": "9639.00",
                "discount_percentage": "0",
                "vat_percentage": "21",
            },
            {
                "product": product,
                "quantity": "2.5",
                "unit": "bolsa",
                "unit_price": "37485.55",
                "discount_percentage": "7.5",
                "vat_percentage": "21",
            },
        ],
    )

    assert float(_sum_item_totals(budget)) == approx(float(budget.total_amount), abs=0.005)
    movement = ClientAccountMovement.get(ClientAccountMovement.budget == budget)
    assert movement.total_amount == budget.total_amount
    assert client_balance(client) == approx(float(budget.total_amount), abs=0.005)


# ---------------------------------------------------------------------------
# 4) GUARD DE INTEGRIDAD
# ---------------------------------------------------------------------------


def test_guard_detecta_inconsistencia_y_reporta_identificadores(db):
    """El guard debe nombrar presupuesto, orden y ambos importes."""
    order, client = _order_000073()
    budget = BudgetService(current_user="admin").ensure_for_load_order(order)[0]
    suma = _sum_item_totals(budget)

    budget.total_amount = float(suma) + 25.0
    budget.save(only=[Budget.total_amount])

    with pytest.raises(MonetaryIntegrityError) as excinfo:
        BudgetService(current_user="admin").assert_monetary_integrity(budget)

    mensaje = str(excinfo.value)
    assert f"{budget.budget_number:06d}" in mensaje
    assert f"OC-{order.order_number:06d}" in mensaje
    assert client.name in mensaje
    assert "37511775.00" in mensaje
    assert "37511800.00" in mensaje


def test_guard_pasa_con_documento_consistente(db):
    order, _client = _order_000073()
    budget = BudgetService(current_user="admin").ensure_for_load_order(order)[0]
    BudgetService(current_user="admin").assert_monetary_integrity(budget)