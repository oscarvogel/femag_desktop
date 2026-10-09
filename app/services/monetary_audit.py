"""Clasificación de la auditoría de integridad monetaria histórica.

Este módulo es **puro**: no importa peewee, no abre conexiones y no escribe
nada. Solo decide, a partir de importes ya leídos, si un presupuesto es
monetariamente consistente y con qué severidad.

Las tres fuentes de verdad que se cruzan son independientes y todas existen
históricamente en FEMAG:

1. ``Budget`` (cabecera): los totales persistidos del presupuesto.
2. ``BudgetItem`` (detalle): los renglones que se imprimen.
3. ``ClientAccountMovement`` (cuenta corriente): el débito original.

Reglas de la auditoría
----------------------

* Todo importe se cuantiza a 2 decimales con ``ROUND_HALF_UP`` (la política de
  ``app.services.money``). La comparación es igualdad exacta de ``Decimal``
  cuantizado: nunca se decide con ``float``.
* ``differences`` es siempre ``cabecera - detalle``. Para el incidente 000073
  eso da ``+25`` (``37.511.800 - 37.511.775``).
* El saldo del cliente no es el importe original de una operación. Un pago
  nunca se suma al débito original y nunca genera una inconsistencia.
* Un movimiento de la cuenta corriente que no sea el débito original de la
  operación (pago, reversión, ajuste, nota de crédito) no se compara contra el
  presupuesto: se contabiliza aparte y solo se informa.
* La deriva entre la orden actual y el presupuesto no se marca como error
  contable: una orden puede editarse después de emitir el presupuesto.

Severidad
---------

``INFO``     orden editada sin impacto contable demostrado, presupuesto
             consistente, sin movimiento de cuenta corriente, operación
             anulada o revertida.
``WARNING``  cabecera incoherente contra el detalle pero sin evidencia de deuda
             incorrecta, ledger ambiguo, reversión parcial.
``CRITICAL``  el débito original de la cuenta corriente no coincide con el
             detalle, o coincide con una cabecera que a su vez difiere del
             detalle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Sequence

from app.services.money import MONEY_TOLERANCE, ZERO_MONEY, quantize_money

# ---------------------------------------------------------------------------
# Estados
# ---------------------------------------------------------------------------

STATUS_OK = "OK"
BUDGET_HEADER_MISMATCH = "BUDGET_HEADER_MISMATCH"

COMPONENT_NET = "NET"
COMPONENT_DISCOUNT = "DISCOUNT"
COMPONENT_VAT = "VAT"
COMPONENT_TOTAL = "TOTAL"

ORDER_NO_ORDER = "NO_ORDER"
ORDER_MATCH = "ORDER_BUDGET_MATCH"
ORDER_DRIFT = "ORDER_BUDGET_DRIFT"

LEDGER_MATCH_DETAIL_AND_HEADER = "LEDGER_MATCH_DETAIL_AND_HEADER"
LEDGER_MATCH_DETAIL = "LEDGER_MATCH_DETAIL"
LEDGER_MATCH_HEADER = "LEDGER_MATCH_HEADER"
LEDGER_MATCH_NEITHER = "LEDGER_MATCH_NEITHER"
LEDGER_AMBIGUOUS = "LEDGER_MULTIPLE_OR_AMBIGUOUS"
LEDGER_NONE = "NO_LEDGER_MOVEMENT"
LEDGER_REVERSED = "REVERSED_OPERATION"
LEDGER_CANCELLED = "CANCELLED_OPERATION"

SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_CRITICAL = "CRITICAL"

#: Estados en los que existe evidencia de que el débito original de la cuenta
#: corriente difiere del detalle del presupuesto. Solo estos aportan a la
#: "diferencia financiera potencial".
LEDGER_FINANCIAL_EVIDENCE = (LEDGER_MATCH_HEADER, LEDGER_MATCH_NEITHER)


# ---------------------------------------------------------------------------
# Importes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Amounts:
    """Importes monetarios ya cuantizados a la precisión de FEMAG."""

    net: Decimal = ZERO_MONEY
    discount: Decimal = ZERO_MONEY
    vat: Decimal = ZERO_MONEY
    total: Decimal = ZERO_MONEY

    @classmethod
    def build(cls, *, net="0", discount="0", vat="0", total=None) -> "Amounts":
        """Construye importes cuantizados. Si no se pasa ``total``, se deriva.

        El total por defecto respeta la aritmética del circuito de presupuestos:
        ``total = neto_subtotal - descuento + iva``.
        """
        net_d = quantize_money(net)
        discount_d = quantize_money(discount)
        vat_d = quantize_money(vat)
        total_d = (
            quantize_money(net_d - discount_d + vat_d)
            if total is None
            else quantize_money(total)
        )
        return cls(net=net_d, discount=discount_d, vat=vat_d, total=total_d)

    @property
    def components(self) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        return (self.net, self.discount, self.vat, self.total)

    def as_dict(self) -> dict[str, Decimal]:
        return {
            "net": self.net,
            "discount": self.discount,
            "vat": self.vat,
            "total": self.total,
        }

    def __add__(self, other: "Amounts") -> "Amounts":
        return Amounts(
            net=quantize_money(self.net + other.net),
            discount=quantize_money(self.discount + other.discount),
            vat=quantize_money(self.vat + other.vat),
            total=quantize_money(self.total + other.total),
        )

    def __sub__(self, other: "Amounts") -> "Amounts":
        return Amounts(
            net=quantize_money(self.net - other.net),
            discount=quantize_money(self.discount - other.discount),
            vat=quantize_money(self.vat - other.vat),
            total=quantize_money(self.total - other.total),
        )


@dataclass(frozen=True)
class LedgerBucket:
    """Total acumulado de un grupo de movimientos, con su cantidad."""

    amount: Decimal = ZERO_MONEY
    count: int = 0

    def __add__(self, other: "LedgerBucket") -> "LedgerBucket":
        return LedgerBucket(
            amount=quantize_money(self.amount + other.amount),
            count=self.count + other.count,
        )


# ---------------------------------------------------------------------------
# Presupuesto: cabecera vs detalle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetIntegrity:
    """Resultado de comparar la cabecera persistida contra el detalle."""

    header: Amounts
    detail: Amounts

    @property
    def differences(self) -> Amounts:
        """``cabecera - detalle``. Para 000073 el total da ``+25``."""
        return self.header - self.detail

    @property
    def budget_header_difference(self) -> Decimal:
        return self.differences.total

    @property
    def components(self) -> tuple[str, ...]:
        diff = self.differences
        found = []
        for name, value in (
            (COMPONENT_NET, diff.net),
            (COMPONENT_DISCOUNT, diff.discount),
            (COMPONENT_VAT, diff.vat),
            (COMPONENT_TOTAL, diff.total),
        ):
            if abs(value) > MONEY_TOLERANCE:
                found.append(name)
        return tuple(found)

    @property
    def status(self) -> str:
        return BUDGET_HEADER_MISMATCH if self.components else STATUS_OK

    @property
    def is_consistent(self) -> bool:
        return self.status == STATUS_OK


def classify_budget_integrity(*, header: Amounts, detail: Amounts) -> BudgetIntegrity:
    """Compara cabecera y detalle con la política monetaria de ``money.py``."""
    return BudgetIntegrity(header=header, detail=detail)


# ---------------------------------------------------------------------------
# Orden de carga vs presupuesto
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderComparison:
    """Estado actual de la orden frente al snapshot del presupuesto."""

    budget_detail_total: Decimal
    order_amounts: Amounts | None = None
    order_updated_at: object | None = None
    item_updated_at: object | None = None
    budget_created_at: object | None = None

    @property
    def order_total_current(self) -> Decimal | None:
        return None if self.order_amounts is None else self.order_amounts.total

    @property
    def difference(self) -> Decimal | None:
        current = self.order_total_current
        if current is None:
            return None
        return quantize_money(current - self.budget_detail_total)

    @property
    def possible_post_budget_change(self) -> bool:
        """``True`` cuando la orden difiere del snapshot del presupuesto.

        Evidencia de que la orden cambió después de emitir el presupuesto. No
        es por sí misma un error contable.
        """
        return self.status == ORDER_DRIFT

    @property
    def status(self) -> str:
        if self.order_amounts is None:
            return ORDER_NO_ORDER
        if abs(self.difference or ZERO_MONEY) <= MONEY_TOLERANCE:
            return ORDER_MATCH
        return ORDER_DRIFT


def classify_order_comparison(
    *,
    budget_detail_total: Decimal,
    order_amounts: Amounts | None,
    order_updated_at=None,
    item_updated_at=None,
    budget_created_at=None,
) -> OrderComparison:
    """Compara la orden vigente contra el detalle histórico del presupuesto.

    ``order_amounts=None`` significa presupuesto manual: sin orden no hay
    deriva que auditar y eso NO es un error.
    """
    return OrderComparison(
        budget_detail_total=quantize_money(budget_detail_total),
        order_amounts=order_amounts,
        order_updated_at=order_updated_at,
        item_updated_at=item_updated_at,
        budget_created_at=budget_created_at,
    )


# ---------------------------------------------------------------------------
# Cuenta corriente
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerCandidate:
    """Un movimiento que se presenta como débito original de la operación.

    ``reversal_total`` es la suma de los movimientos de reversión que apuntan a
    este original (``reverses_id``). Siempre es negativo o cero.
    """

    movement_id: int
    movement_type: str
    net: Decimal = ZERO_MONEY
    discount: Decimal = ZERO_MONEY
    vat: Decimal = ZERO_MONEY
    total: Decimal = ZERO_MONEY
    reversal_total: Decimal = ZERO_MONEY
    movement_date: object | None = None
    source_ref: str | None = None
    reference: str | None = None

    @property
    def amounts(self) -> Amounts:
        return Amounts(
            net=quantize_money(self.net),
            discount=quantize_money(self.discount),
            vat=quantize_money(self.vat),
            total=quantize_money(self.total),
        )

    @property
    def net_after_reversals(self) -> Decimal:
        return quantize_money(quantize_money(self.total) + quantize_money(self.reversal_total))

    @property
    def is_fully_reversed(self) -> bool:
        return (
            abs(quantize_money(self.total)) > MONEY_TOLERANCE
            and abs(self.net_after_reversals) <= MONEY_TOLERANCE
        )

    @property
    def is_partially_reversed(self) -> bool:
        if self.is_fully_reversed:
            return False
        return abs(quantize_money(self.reversal_total)) > MONEY_TOLERANCE


@dataclass(frozen=True)
class LedgerView:
    """Clasificación del circuito de cuenta corriente para un presupuesto."""

    detail_total: Decimal
    header_total: Decimal
    status: str
    candidates: tuple[LedgerCandidate, ...] = ()
    movement_ids: tuple[int, ...] = ()
    original_amounts: Amounts | None = None
    original_total: Decimal | None = None
    reversals: LedgerBucket = field(default_factory=LedgerBucket)
    payments: LedgerBucket = field(default_factory=LedgerBucket)
    payment_reversals: LedgerBucket = field(default_factory=LedgerBucket)
    adjustments: LedgerBucket = field(default_factory=LedgerBucket)
    adjustment_reversals: LedgerBucket = field(default_factory=LedgerBucket)

    @property
    def ledger_matches_detail(self) -> bool:
        """``True`` si el importe del débito original iguala al detalle.

        Compara **solo importes**, no el estado de dominio: una operación
        anulada o revertida puede tener importes que coinciden y aun así no
        representar deuda vigente. Para eso está ``status`` y
        ``has_financial_evidence``.
        """
        return bool(
            self.original_total is not None
            and abs(quantize_money(self.original_total) - self.detail_total) <= MONEY_TOLERANCE
        )

    @property
    def ledger_matches_header(self) -> bool:
        return bool(
            self.original_total is not None
            and abs(quantize_money(self.original_total) - self.header_total) <= MONEY_TOLERANCE
        )

    @property
    def ledger_detail_difference(self) -> Decimal | None:
        if self.original_total is None:
            return None
        return quantize_money(quantize_money(self.original_total) - self.detail_total)

    @property
    def ledger_header_difference(self) -> Decimal | None:
        if self.original_total is None:
            return None
        return quantize_money(quantize_money(self.original_total) - self.header_total)

    @property
    def is_partially_reversed(self) -> bool:
        return any(candidate.is_partially_reversed for candidate in self.candidates)

    @property
    def has_financial_evidence(self) -> bool:
        """``True`` cuando el débito original difiere del detalle del presupuesto."""
        return self.status in LEDGER_FINANCIAL_EVIDENCE and self.original_total is not None


def classify_ledger(
    *,
    detail_total: Decimal,
    header_total: Decimal,
    candidates: Sequence[LedgerCandidate] = (),
    cancelled: bool = False,
    payments: LedgerBucket = LedgerBucket(),
    payment_reversals: LedgerBucket = LedgerBucket(),
    adjustments: LedgerBucket = LedgerBucket(),
    adjustment_reversals: LedgerBucket = LedgerBucket(),
) -> LedgerView:
    """Clasifica el movimiento original de la cuenta corriente.

    Precedencia determinista:

    1. ``CANCELLED_OPERATION`` si el presupuesto u la orden están anulados.
    2. ``NO_LEDGER_MOVEMENT`` si no hay ningún candidato.
    3. ``LEDGER_MULTIPLE_OR_AMBIGUOUS`` si hay más de un candidato: no se
       inventa una suma.
    4. ``REVERSED_OPERATION`` si el único original está cancelado por su
       reversión.
    5. Comparación contra detalle y cabecera.
    """
    detail_d = quantize_money(detail_total)
    header_d = quantize_money(header_total)
    ordered = tuple(candidates)
    single = ordered[0] if len(ordered) == 1 else None

    if cancelled:
        status = LEDGER_CANCELLED
    elif not ordered:
        status = LEDGER_NONE
    elif len(ordered) > 1:
        status = LEDGER_AMBIGUOUS
    elif single.is_fully_reversed:
        status = LEDGER_REVERSED
    else:
        original = quantize_money(single.total)
        matches_detail = abs(original - detail_d) <= MONEY_TOLERANCE
        matches_header = abs(original - header_d) <= MONEY_TOLERANCE
        if matches_detail and matches_header:
            status = LEDGER_MATCH_DETAIL_AND_HEADER
        elif matches_detail:
            status = LEDGER_MATCH_DETAIL
        elif matches_header:
            status = LEDGER_MATCH_HEADER
        else:
            status = LEDGER_MATCH_NEITHER

    reversal_bucket = LedgerBucket()
    if single is not None and abs(single.reversal_total) > MONEY_TOLERANCE:
        reversal_bucket = LedgerBucket(
            amount=single.reversal_total, count=1
        )

    return LedgerView(
        detail_total=detail_d,
        header_total=header_d,
        status=status,
        candidates=ordered,
        movement_ids=tuple(candidate.movement_id for candidate in ordered),
        original_amounts=single.amounts if single is not None else None,
        original_total=quantize_money(single.total) if single is not None else None,
        reversals=reversal_bucket,
        payments=payments,
        payment_reversals=payment_reversals,
        adjustments=adjustments,
        adjustment_reversals=adjustment_reversals,
    )


# ---------------------------------------------------------------------------
# Severidad
# ---------------------------------------------------------------------------


def classify_severity(*, integrity: BudgetIntegrity, ledger: LedgerView) -> str:
    """Devuelve la severidad según la primera regla que aplica.

    Las reglas están ordenadas de más a menos grave y no hay heurísticas ni
    umbrales flotantes:

    1. ``CRITICAL``  el débito original no coincide ni con el detalle ni con
       la cabecera, o coincide con una cabecera que difiere del detalle.
    2. ``WARNING``   no se puede afirmar que la deuda sea incorrecta, pero hay
       algo que revisar: ledger ambiguo, reversión parcial o cabecera
       incoherente con el detalle.
    3. ``INFO``      presupuesto consistente, sin movimiento de cuenta
       corriente, operación anulada o revertida.

    ``ORDER_BUDGET_DRIFT`` no aparece a propósito: una orden puede editarse
    después de emitir el presupuesto sin que la deuda sea incorrecta, así que
    la deriva nunca sube la severidad por sí sola.
    """
    if ledger.status == LEDGER_MATCH_NEITHER:
        return SEVERITY_CRITICAL
    if ledger.status == LEDGER_MATCH_HEADER and integrity.components:
        return SEVERITY_CRITICAL
    if ledger.status == LEDGER_AMBIGUOUS:
        return SEVERITY_WARNING
    if ledger.is_partially_reversed:
        return SEVERITY_WARNING
    if integrity.components:
        return SEVERITY_WARNING
    return SEVERITY_INFO


# ---------------------------------------------------------------------------
# Auditoría completa de un presupuesto
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetAudit:
    """Auditoría de un presupuesto, cruzando las tres fuentes históricas."""

    budget_id: int
    budget_number: int
    client_id: int | None
    client_name: str | None
    order_id: int | None
    order_number: int | None
    budget_date: object | None
    budget_status: str | None
    budget_origin: str | None
    integrity: BudgetIntegrity
    order: OrderComparison
    ledger: LedgerView

    @property
    def budget_integrity(self) -> str:
        return self.integrity.status

    @property
    def order_budget(self) -> str:
        return self.order.status

    @property
    def ledger_integrity(self) -> str:
        return self.ledger.status

    @property
    def severity(self) -> str:
        return classify_severity(integrity=self.integrity, ledger=self.ledger)

    @property
    def budget_header_difference(self) -> Decimal:
        return self.integrity.budget_header_difference

    @property
    def potential_financial_difference(self) -> Decimal:
        """Diferencia con evidencia contable, para este presupuesto.

        Solo cuenta cuando existe un único débito original en la cuenta
        corriente y ese importe difiere del detalle del presupuesto. Los pagos,
        reversiones y ajustes no aportan.
        """
        if not self.ledger.has_financial_evidence:
            return ZERO_MONEY
        difference = self.ledger.ledger_detail_difference
        return ZERO_MONEY if difference is None else abs(quantize_money(difference))


def potential_financial_difference(audits: Iterable[BudgetAudit]) -> Decimal:
    """Suma las diferencias con evidencia contable sin duplicar movimientos.

    Un mismo movimiento de cuenta corriente se contabiliza una sola vez: si dos
    presupuestos lo reclaman (colisión de trazabilidad histórica), se suma solo
    el primero en orden de ``budget_id`` y el resto se descarta en lugar de
    inventar un importe.
    """
    counted: set[int] = set()
    total = ZERO_MONEY
    for audit in sorted(audits, key=lambda entry: entry.budget_id):
        if not audit.ledger.has_financial_evidence:
            continue
        movement_ids = audit.ledger.movement_ids
        if not movement_ids:
            continue
        if any(movement_id in counted for movement_id in movement_ids):
            continue
        counted.update(movement_ids)
        total = quantize_money(total + audit.potential_financial_difference)
    return total
