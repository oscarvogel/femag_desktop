"""Clasificación determinística de la auditoría de integridad monetaria.

Estos tests no tocan la base: verifican únicamente las reglas de clasificación
del auditor contra los casos documentados del incidente 000073 y contra las
reglas de cuenta corriente (pago no es deuda, reversión no es deuda, saldo no es
importe original).

Regla del proyecto: la auditoría es READ-ONLY. Nada de lo que se prueba aquí
escribe, migra, repara ni regenera importes.
"""

from decimal import Decimal

from app.services.monetary_audit import (
    BUDGET_HEADER_MISMATCH,
    COMPONENT_DISCOUNT,
    COMPONENT_NET,
    COMPONENT_TOTAL,
    COMPONENT_VAT,
    LEDGER_AMBIGUOUS,
    LEDGER_CANCELLED,
    LEDGER_MATCH_DETAIL,
    LEDGER_MATCH_DETAIL_AND_HEADER,
    LEDGER_MATCH_HEADER,
    LEDGER_MATCH_NEITHER,
    LEDGER_NONE,
    LEDGER_REVERSED,
    ORDER_DRIFT,
    ORDER_MATCH,
    ORDER_NO_ORDER,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    STATUS_OK,
    Amounts,
    BudgetAudit,
    BudgetIntegrity,
    LedgerBucket,
    LedgerCandidate,
    classify_budget_integrity,
    classify_ledger,
    classify_order_comparison,
    classify_severity,
    potential_financial_difference,
)


# ---------------------------------------------------------------------------
# Helpers de construcción
# ---------------------------------------------------------------------------


def _audit(
    *,
    header,
    detail,
    ledger=None,
    order=None,
    budget_id=1,
    budget_number=73,
    client_id=10,
    order_id=51,
):
    integrity = classify_budget_integrity(header=header, detail=detail)
    order_comparison = classify_order_comparison(
        budget_detail_total=detail.total,
        order_amounts=(None if order is None else Amounts.build(total=order)),
    )
    ledger_view = classify_ledger(
        detail_total=detail.total,
        header_total=header.total,
        candidates=[] if ledger is None else ledger,
        cancelled=False,
    )
    return BudgetAudit(
        budget_id=budget_id,
        budget_number=budget_number,
        client_id=client_id,
        client_name="CARDOZO MAURICIO GUSTAVO",
        order_id=order_id if order is not None else None,
        order_number=51 if order is not None else None,
        budget_date=None,
        budget_status="active",
        budget_origin="load_order",
        integrity=integrity,
        order=order_comparison,
        ledger=ledger_view,
    )


def _original(movement_id=900, total="100", *, net=None, reversal="0", movement_type="load_order_documental"):
    total_d = Decimal(total)
    net_d = total_d if net is None else Decimal(net)
    return LedgerCandidate(
        movement_id=movement_id,
        movement_type=movement_type,
        net=Amounts.build(net=net_d).net,
        discount=Decimal("0.00"),
        vat=Decimal("0.00"),
        total=Amounts.build(total=total_d).total,
        reversal_total=Amounts.build(total=reversal).total,
    )


# ---------------------------------------------------------------------------
# A) TODO CONSISTENTE
# ---------------------------------------------------------------------------


def test_caso_a_todo_consistente_es_ok_sin_riesgo():
    audit = _audit(
        header=Amounts.build(net=100, total=100),
        detail=Amounts.build(net=100, total=100),
        ledger=[_original(total="100")],
        order=100,
    )

    assert audit.budget_integrity == STATUS_OK
    assert audit.order_budget == ORDER_MATCH
    assert audit.ledger_integrity == LEDGER_MATCH_DETAIL_AND_HEADER
    assert audit.severity == SEVERITY_INFO
    assert audit.potential_financial_difference == Decimal("0.00")


# ---------------------------------------------------------------------------
# B) CASO 000073 REAL: detalle 37.511.775, cabecera 37.511.800, ledger 37.511.800
# ---------------------------------------------------------------------------


def test_caso_b_000073_header_mismatch_y_ledger_coincide_con_cabecera():
    detail = Amounts.build(net="37511775", total="37511775")
    header = Amounts.build(net="37511800", total="37511800")

    audit = _audit(
        header=header,
        detail=detail,
        ledger=[_original(movement_id=4242, total="37511800", net="37511800")],
        order="37511775",
    )

    assert audit.budget_integrity == BUDGET_HEADER_MISMATCH
    assert audit.integrity.components == (COMPONENT_NET, COMPONENT_TOTAL)
    assert audit.ledger_integrity == LEDGER_MATCH_HEADER
    assert audit.severity == SEVERITY_CRITICAL
    assert audit.integrity.differences.total == Decimal("25.00")
    assert audit.budget_header_difference == Decimal("25.00")
    assert audit.ledger.ledger_matches_header is True
    assert audit.ledger.ledger_matches_detail is False
    assert audit.ledger.ledger_detail_difference == Decimal("25.00")
    assert audit.ledger.ledger_header_difference == Decimal("0.00")
    assert audit.potential_financial_difference == Decimal("25.00")


# ---------------------------------------------------------------------------
# C) MISMO 000073 PERO CON LEDGER EN EL IMPORTE DEL DETALLE: no hay riesgo
# ---------------------------------------------------------------------------


def test_caso_c_header_mismatch_con_ledger_en_detalle_es_warning_sin_diferencia():
    detail = Amounts.build(net="37511775", total="37511775")
    header = Amounts.build(net="37511800", total="37511800")

    audit = _audit(
        header=header,
        detail=detail,
        ledger=[_original(movement_id=4242, total="37511775", net="37511775")],
        order="37511775",
    )

    assert audit.budget_integrity == BUDGET_HEADER_MISMATCH
    assert audit.ledger_integrity == LEDGER_MATCH_DETAIL
    assert audit.severity == SEVERITY_WARNING
    assert audit.potential_financial_difference == Decimal("0.00")


# ---------------------------------------------------------------------------
# D) ORDEN EDITADA DESPUES DEL SNAPSHOT
# ---------------------------------------------------------------------------


def test_caso_d_orden_actual_distinta_es_drift_y_no_error_financiero():
    audit = _audit(
        header=Amounts.build(net=100, total=100),
        detail=Amounts.build(net=100, total=100),
        ledger=[_original(total="100")],
        order=150,
    )

    assert audit.order_budget == ORDER_DRIFT
    assert audit.order.order_total_current == Decimal("150.00")
    assert audit.order.budget_detail_total == Decimal("100.00")
    assert audit.order.difference == Decimal("50.00")
    assert audit.order.possible_post_budget_change is True
    # El drift NO se reporta como error contable.
    assert audit.budget_integrity == STATUS_OK
    assert audit.ledger_integrity == LEDGER_MATCH_DETAIL_AND_HEADER
    assert audit.severity == SEVERITY_INFO
    assert audit.potential_financial_difference == Decimal("0.00")


# ---------------------------------------------------------------------------
# E) DEUDA PARCIALMENTE PAGADA: el pago NO genera falso positivo
# ---------------------------------------------------------------------------


def test_caso_e_pago_parcial_no_es_inconsistencia():
    audit = _audit(
        header=Amounts.build(net=100, total=100),
        detail=Amounts.build(net=100, total=100),
        ledger=[_original(total="100")],
        order=100,
    )
    audit = _with_payments(audit, payment_total="60", payment_count=1)

    assert audit.ledger_integrity == LEDGER_MATCH_DETAIL_AND_HEADER
    assert audit.ledger.payments == LedgerBucket(amount=Decimal("60.00"), count=1)
    assert audit.severity == SEVERITY_INFO
    assert audit.potential_financial_difference == Decimal("0.00")


def _with_payments(audit, *, payment_total, payment_count):
    from dataclasses import replace

    return replace(
        audit,
        ledger=replace(
            audit.ledger,
            payments=LedgerBucket(amount=Amounts.build(total=payment_total).total, count=payment_count),
        ),
    )


def test_caso_e_saldo_restante_no_se_interpreta_como_importe_original():
    """Deuda 100, pago 60, saldo 40: el importe original sigue siendo 100."""
    audit = _audit(
        header=Amounts.build(net=100, total=100),
        detail=Amounts.build(net=100, total=100),
        ledger=[_original(total="100")],
        order=100,
    )

    audit = _with_payments(audit, payment_total="60", payment_count=1)

    remaining = audit.ledger.original_total - audit.ledger.payments.amount

    assert remaining == Decimal("40.00")
    assert audit.ledger.original_total == Decimal("100.00")
    assert audit.ledger_integrity == LEDGER_MATCH_DETAIL_AND_HEADER
    assert audit.severity == SEVERITY_INFO


# ---------------------------------------------------------------------------
# F) OPERACION REVERSADA
# ---------------------------------------------------------------------------


def test_caso_f_reversion_total_no_es_deuda_incorrecta():
    audit = _audit(
        header=Amounts.build(net=100, total=100),
        detail=Amounts.build(net=100, total=100),
        ledger=[_original(total="100", reversal="-100")],
        order=100,
    )

    assert audit.ledger_integrity == LEDGER_REVERSED
    assert audit.ledger.reversals == LedgerBucket(amount=Decimal("-100.00"), count=1)
    assert audit.severity == SEVERITY_INFO
    assert audit.potential_financial_difference == Decimal("0.00")


def test_reversion_parcial_se_reporta_como_warning():
    audit = _audit(
        header=Amounts.build(net=100, total=100),
        detail=Amounts.build(net=100, total=100),
        ledger=[_original(total="100", reversal="-40")],
        order=100,
    )

    assert audit.ledger_integrity == LEDGER_MATCH_DETAIL_AND_HEADER
    assert audit.ledger.is_partially_reversed is True
    assert audit.severity == SEVERITY_WARNING
    assert audit.potential_financial_difference == Decimal("0.00")


# ---------------------------------------------------------------------------
# G) LEDGER AMBIGUO / MULTIPLE
# ---------------------------------------------------------------------------


def test_caso_g_varios_movimientos_originales_no_se_suman():
    audit = _audit(
        header=Amounts.build(net=100, total=100),
        detail=Amounts.build(net=100, total=100),
        ledger=[_original(movement_id=1, total="100"), _original(movement_id=2, total="100")],
        order=100,
    )

    assert audit.ledger_integrity == LEDGER_AMBIGUOUS
    assert audit.ledger.movement_ids == (1, 2)
    assert audit.severity == SEVERITY_WARNING
    # No se inventa una suma de 200 ni se cuenta como diferencia real.
    assert audit.potential_financial_difference == Decimal("0.00")


# ---------------------------------------------------------------------------
# H) PRESUPUESTO MANUAL SIN ORDEN
# ---------------------------------------------------------------------------


def test_caso_h_presupuesto_manual_sin_orden_se_audita_sin_fallar():
    detail = Amounts.build(net=100, total=100)
    header = Amounts.build(net=100, total=100)

    integrity = classify_budget_integrity(header=header, detail=detail)
    order = classify_order_comparison(budget_detail_total=detail.total, order_amounts=None)
    ledger = classify_ledger(
        detail_total=detail.total,
        header_total=header.total,
        candidates=[_original(movement_id=7, total="100", movement_type="budget_manual")],
    )

    assert order.status == ORDER_NO_ORDER
    assert order.order_total_current is None
    assert order.difference is None
    assert order.possible_post_budget_change is False
    assert integrity.status == STATUS_OK
    assert ledger.status == LEDGER_MATCH_DETAIL_AND_HEADER


# ---------------------------------------------------------------------------
# I) PRESUPUESTO SIN MOVIMIENTO DE CUENTA CORRIENTE
# ---------------------------------------------------------------------------


def test_caso_i_sin_movimiento_no_se_asume_error():
    audit = _audit(
        header=Amounts.build(net=100, total=100),
        detail=Amounts.build(net=100, total=100),
        ledger=[],
        order=100,
    )

    assert audit.ledger_integrity == LEDGER_NONE
    assert audit.budget_integrity == STATUS_OK
    assert audit.severity == SEVERITY_INFO
    assert audit.potential_financial_difference == Decimal("0.00")


def test_sin_movimiento_pero_con_cabecera_incoherente_es_warning():
    audit = _audit(
        header=Amounts.build(net="37511800", total="37511800"),
        detail=Amounts.build(net="37511775", total="37511775"),
        ledger=[],
        order="37511775",
    )

    assert audit.budget_integrity == BUDGET_HEADER_MISMATCH
    assert audit.ledger_integrity == LEDGER_NONE
    assert audit.severity == SEVERITY_WARNING
    assert audit.potential_financial_difference == Decimal("0.00")


# ---------------------------------------------------------------------------
# J) CENTAVOS / DECIMAL
# ---------------------------------------------------------------------------


def test_caso_j_comparacion_exacta_despues_de_quantizar():
    detail = Amounts.build(net="100.004", discount="0", vat="0", total="100.004")

    assert detail.total == Decimal("100.00")

    consistent = classify_budget_integrity(
        header=Amounts.build(net="100.00", total="100.00"), detail=detail
    )
    assert consistent.status == STATUS_OK

    inconsistent = classify_budget_integrity(
        header=Amounts.build(net="100.005", total="100.005"), detail=detail
    )
    assert inconsistent.status == BUDGET_HEADER_MISMATCH
    assert inconsistent.differences.total == Decimal("0.01")


def test_caso_j_ningun_componente_se_compara_con_float():
    detail = Amounts.build(net="0.1", discount="0", vat="0", total="0.1")
    header = Amounts.build(net="0.3", discount="0", vat="0", total="0.3")

    result = classify_budget_integrity(header=header, detail=detail)

    assert isinstance(result.differences.net, Decimal)
    assert result.status == BUDGET_HEADER_MISMATCH
    assert result.components == (COMPONENT_NET, COMPONENT_TOTAL)


def test_componentes_independientes_se_reportan_por_separado():
    detail = Amounts.build(net="100", discount="1", vat="0", total="99")
    header = Amounts.build(net="100", discount="2", vat="0", total="98")

    result = classify_budget_integrity(header=header, detail=detail)

    assert result.status == BUDGET_HEADER_MISMATCH
    assert result.components == (COMPONENT_DISCOUNT, COMPONENT_TOTAL)


def test_iva_se_compara_como_componente_independiente():
    detail = Amounts.build(net="100", discount="0", vat="21", total="121")
    header = Amounts.build(net="100", discount="0", vat="20", total="120")

    result = classify_budget_integrity(header=header, detail=detail)

    assert result.components == (COMPONENT_VAT, COMPONENT_TOTAL)
    assert result.differences.vat == Decimal("-1.00")


# ---------------------------------------------------------------------------
# DETERMINISMO Y AISLAMIENTO ENTRE PRESUPUESTOS
# ---------------------------------------------------------------------------


def test_la_clasificacion_es_determinista():
    detail = Amounts.build(net="37511775", total="37511775")
    header = Amounts.build(net="37511800", total="37511800")
    candidates = [_original(movement_id=4242, total="37511800", net="37511800")]

    first = _audit(header=header, detail=detail, ledger=candidates)
    second = _audit(header=header, detail=detail, ledger=candidates)

    assert first == second


def test_la_diferencia_potencial_no_cuenta_dos_veces_el_mismo_movimiento():
    detail = Amounts.build(net="37511775", total="37511775")
    header = Amounts.build(net="37511800", total="37511800")
    shared = [_original(movement_id=4242, total="37511800", net="37511800")]

    primero = _audit(
        header=header,
        detail=detail,
        ledger=shared,
        budget_id=73,
        budget_number=73,
    )
    segundo = _audit(
        header=header,
        detail=detail,
        ledger=shared,
        budget_id=74,
        budget_number=74,
    )

    assert primero.potential_financial_difference == Decimal("25.00")
    assert segundo.potential_financial_difference == Decimal("25.00")
    assert potential_financial_difference([primero, segundo]) == Decimal("25.00")


def test_la_diferencia_potencial_suma_casos_independientes():
    detalle_73 = Amounts.build(net="37511775", total="37511775")
    cabecera_73 = Amounts.build(net="37511800", total="37511800")
    caso_73 = _audit(
        header=cabecera_73,
        detail=detalle_73,
        ledger=[_original(movement_id=1, total="37511800", net="37511800")],
        budget_id=73,
    )

    detalle_90 = Amounts.build(net="1000", total="1000")
    cabecera_90 = Amounts.build(net="1010", total="1010")
    caso_90 = _audit(
        header=cabecera_90,
        detail=detalle_90,
        ledger=[_original(movement_id=2, total="1010", net="1010")],
        budget_id=90,
        budget_number=90,
    )

    assert potential_financial_difference([caso_73, caso_90]) == Decimal("35.00")


def test_ledger_match_neither_es_critical():
    audit = _audit(
        header=Amounts.build(net=100, total=100),
        detail=Amounts.build(net=100, total=100),
        ledger=[_original(total="90")],
        order=100,
    )

    assert audit.ledger_integrity == LEDGER_MATCH_NEITHER
    assert audit.ledger.ledger_matches_detail is False
    assert audit.ledger.ledger_matches_header is False
    assert audit.severity == SEVERITY_CRITICAL
    assert audit.potential_financial_difference == Decimal("10.00")


def test_operacion_anulada_tiene_precedencia_sobre_reversion():
    detail = Amounts.build(net=100, total=100)
    ledger = classify_ledger(
        detail_total=detail.total,
        header_total=detail.total,
        candidates=[_original(total="100", reversal="-100")],
        cancelled=True,
    )

    # El estado de dominio manda: una operación anulada no es deuda vigente.
    assert ledger.status == LEDGER_CANCELLED
    assert ledger.original_total == Decimal("100.00")
    # Los importes sí coinciden, pero eso no genera evidencia de riesgo.
    assert ledger.has_financial_evidence is False


def test_severity_es_la_mas_alta_entre_las_reglas_aplicables():
    integrity = classify_budget_integrity(
        header=Amounts.build(net=101, total=101),
        detail=Amounts.build(net=100, total=100),
    )
    ledger = classify_ledger(
        detail_total=Decimal("100.00"),
        header_total=Decimal("101.00"),
        candidates=[_original(total="101")],
    )

    # Ledger con cabecera y cabecera incoherente => CRITICAL, aunque además
    # exista deriva de la orden (la deriva no baja ni sube la severidad).
    assert classify_severity(integrity=integrity, ledger=ledger) == SEVERITY_CRITICAL


def test_la_deriva_de_la_orden_nunca_sube_la_severidad():
    integrity = classify_budget_integrity(
        header=Amounts.build(net=100, total=100),
        detail=Amounts.build(net=100, total=100),
    )
    ledger = classify_ledger(
        detail_total=Decimal("100.00"),
        header_total=Decimal("100.00"),
        candidates=[_original(total="100")],
    )
    order = classify_order_comparison(
        budget_detail_total=Decimal("100.00"), order_amounts=Amounts.build(total=150)
    )

    assert order.status == ORDER_DRIFT
    assert classify_severity(integrity=integrity, ledger=ledger) == SEVERITY_INFO


def test_presupuesto_sin_items_no_se_reporta_como_ok_falso():
    integrity = classify_budget_integrity(
        header=Amounts.build(net=0, total=0),
        detail=Amounts.build(net=0, total=0),
    )
    assert integrity.status == STATUS_OK

    vacio_con_cabecera = classify_budget_integrity(
        header=Amounts.build(net=100, total=100),
        detail=Amounts.build(net=0, total=0),
    )
    assert vacio_con_cabecera.status == BUDGET_HEADER_MISMATCH


def test_budget_integrity_expone_diferencias_por_componente():
    detail = Amounts.build(net="100", discount="2", vat="21", total="119")
    header = Amounts.build(net="100", discount="2", vat="22", total="120")

    result = classify_budget_integrity(header=header, detail=detail)

    assert result.differences.net == Decimal("0.00")
    assert result.differences.discount == Decimal("0.00")
    assert result.differences.vat == Decimal("1.00")
    assert result.differences.total == Decimal("1.00")
    assert result.is_consistent is False
    assert isinstance(result, BudgetIntegrity)
