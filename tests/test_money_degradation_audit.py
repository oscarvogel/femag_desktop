"""Inventario de degradaciones Decimal -> float que quedan tras la migración.

No las corrige: las documenta y las clasifica. La migración de columnas es el
cambio de fondo; convertir a mano cada reporte es otro trabajo, con su propio
issue, y hacerlo a ciegas sería justo el tipo de refactorización que este
encargo pide evitar.

``CRITICO`` significa que el float vuelve a **escribir** dinero en la base.
``LECTURA`` significa que sólo afecta lo que se muestra o exporta.
"""

from decimal import Decimal

from app.models.accounting import ClientAccountMovement
from app.models.budgets import Budget
from app.models.payments import ClientPayment

# --- escriben dinero en la base a través de un float -----------------------
CRITICOS = [
    (
        "app/config/schema.py",
        "_repair_payment_movement_amounts",
        "usa quantize_money/Decimal (ya corregido en esta rama)",
    ),
    (
        "app/services/account_ledger_service.py",
        "generate_for_load_order",
        "totales del movimiento con money_to_decimal (ya corregido)",
    ),
    (
        "app/services/budget_service.py",
        "ensure_for_load_order_client / create_manual",
        "cabecera y renglones con money_to_decimal (ya corregido)",
    ),
]

# --- sólo lectura: no vuelven a escribir, pero pueden mostrar un float --------
LECTURA = [
    ("app/services/ledger_query_service.py", "88,200", "fn.ROUND(SUM) en SQL: exacto en DECIMAL"),
    ("app/services/ledger_query_service.py", "169", "round(overdue_exposure, 2): presentación"),
    ("app/services/load_order_closure_service.py", "196", "float(payment.amount) en un acumulado"),
    ("app/services/load_order_closure_service.py", "332", "round(float(movement.total_amount), 2)"),
    ("app/services/master_service.py", "375", "float(precio_lista_1) al derivar precio base"),
    ("app/reports/collection_due_report.py", "92-101", "round(float(total_amount), 2)"),
    ("app/services/client_payment_service.py", "108", "round(float(raw amount), 2) al normalizar un pago"),
    ("app/services/load_order_pallet_excel_export_service.py", "235", "float(quantity): cantidad, no dinero"),
]


def money_fields_of(model):
    from app.config.money_columns import MONEY_COLUMNS_BY_TABLE

    return {c.column for c in MONEY_COLUMNS_BY_TABLE.get(model._meta.table_name, ())}


def test_los_modelos_de_dinero_son_decimal():
    for model in (Budget, ClientAccountMovement, ClientPayment):
        campos = money_fields_of(model)
        assert campos, f"{model.__name__} no tiene columnas monetarias registradas"
        for nombre in campos:
            campo = model._meta.combined[nombre]
            assert campo.__class__.__name__ == "DecimalField", (
                f"{model.__name__}.{nombre} sigue siendo {campo.__class__.__name__}"
            )
            assert campo.decimal_places == 2
            assert campo.max_digits == 18


def test_las_cantidades_y_porcentajes_siguen_siendo_float():
    """Convertirlos rompería la semántica de fracciones y porcentajes."""
    from app.models.load_orders import LoadOrderProduct
    from app.models.masters import TipoIVA

    assert LoadOrderProduct.quantity.__class__.__name__ == "FloatField"
    assert LoadOrderProduct.descuento_porcentaje.__class__.__name__ == "FloatField"
    assert LoadOrderProduct.iva_porcentaje.__class__.__name__ == "FloatField"
    assert TipoIVA.porcentaje.__class__.__name__ == "FloatField"


def test_los_costos_unitarios_conservan_cuatro_decimales():
    """El negocio usa precisión sub-centavo en costos: no se toca."""
    from app.models.masters import Product, ProductCostHistory

    assert Product.costo_unitario.decimal_places == 4
    assert ProductCostHistory.new_cost.decimal_places == 4
    assert ProductCostHistory.previous_cost.decimal_places == 4


def test_el_inventario_de_degradaciones_esta_documentado():
    assert CRITICOS, "debe quedar registrado qué caminos de escritura se corrigieron"
    assert LECTURA, "debe quedar registrado qué lecturas degradan a float"
    for archivo, donde, nota in CRITICOS + LECTURA:
        assert archivo and donde and nota


def test_el_audit_log_serializa_decimal_sin_perder_precision():
    import json

    from app.models.audit import JSONTextField

    campo = JSONTextField()
    texto = campo.db_value({"total": Decimal("37511775.00")})
    assert json.loads(texto)["total"] == "37511775.00"
    # Si fuera float, el importe ya habría cambiado.
    assert "37511800" not in texto
