"""Auditoría READ-ONLY de integridad monetaria histórica de FEMAG.

Responde una sola pregunta: **¿qué datos históricos de FEMAG son
monetariamente inconsistentes, cuánto riesgo financiero potencial existe y
dónde están?**

No repara nada. No migra, no hace backfill, no genera movimientos, no regenera
presupuestos, no cambia estados y no llama servicios con efectos laterales. El
acceso a la base está en ``app.services.monetary_audit_readonly`` y es
``SELECT`` solamente.

Uso
---

Resumen de todos los presupuestos::

    python -m scripts.audit_monetary_integrity

Detalle de un presupuesto (por número visible o por id interno)::

    python -m scripts.audit_monetary_integrity --budget-number 73
    python -m scripts.audit_monetary_integrity --budget 73

Exportación con una fila por presupuesto::

    python -m scripts.audit_monetary_integrity --csv monetary_audit.csv

La conexión se toma de la configuración del puesto (``.env``, DPAPI o variables
``DB_*``). ``--db`` permite apuntar a otra base del mismo servidor, por ejemplo
la copia local de producción.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from app.services.monetary_audit import (
    BUDGET_HEADER_MISMATCH,
    LEDGER_AMBIGUOUS,
    LEDGER_CANCELLED,
    LEDGER_MATCH_DETAIL,
    LEDGER_MATCH_DETAIL_AND_HEADER,
    LEDGER_MATCH_HEADER,
    LEDGER_MATCH_NEITHER,
    LEDGER_NONE,
    LEDGER_REVERSED,
    ORDER_DRIFT,
    SEVERITY_CRITICAL,
    STATUS_OK,
    Amounts,
    BudgetAudit,
    potential_financial_difference,
)
from app.services.monetary_audit_readonly import (
    AuditDatabaseTarget,
    MonetaryIntegrityAuditor,
    open_audit_database,
    resolve_audit_database,
)

SUMMARY_TITLE = "MONETARY INTEGRITY AUDIT"

LABEL_WIDTH = 36

CSV_COLUMNS = (
    "budget_id",
    "budget_number",
    "client_id",
    "client_name",
    "order_id",
    "order_number",
    "budget_date",
    "budget_status",
    "budget_origin",
    "header_net",
    "header_discount",
    "header_vat",
    "header_total",
    "detail_net",
    "detail_discount",
    "detail_vat",
    "detail_total",
    "diff_net",
    "diff_discount",
    "diff_vat",
    "diff_total",
    "current_order_total",
    "order_budget_difference",
    "ledger_movement_id",
    "ledger_original_total",
    "ledger_detail_difference",
    "ledger_header_difference",
    "budget_integrity",
    "order_budget_status",
    "ledger_integrity",
    "severity",
)


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditSummary:
    """Conteos del reporte. Cada categoría es disjunta y verificable."""

    budgets_analyzed: int = 0
    consistent: int = 0
    budget_header_mismatches: int = 0
    order_budget_drift: int = 0
    ledger_matches_detail: int = 0
    ledger_matches_header_only: int = 0
    ledger_matches_neither: int = 0
    ambiguous_ledger: int = 0
    no_ledger_movement: int = 0
    reversed_operations: int = 0
    cancelled_operations: int = 0
    critical_cases: int = 0
    potential_financial_difference: Decimal = Decimal("0.00")

    def as_lines(self) -> list[tuple[str, object]]:
        return [(label, getattr(self, attribute)) for label, attribute in SUMMARY_FIELDS]


#: Orden de las líneas del resumen. Fuente única de las etiquetas.
SUMMARY_FIELDS: tuple[tuple[str, str], ...] = (
    ("Budgets analyzed", "budgets_analyzed"),
    ("Consistent", "consistent"),
    ("Budget header mismatches", "budget_header_mismatches"),
    ("Order/Budget drift", "order_budget_drift"),
    ("Ledger matches detail", "ledger_matches_detail"),
    ("Ledger matches header only", "ledger_matches_header_only"),
    ("Ledger matches neither", "ledger_matches_neither"),
    ("Ambiguous ledger", "ambiguous_ledger"),
    ("No ledger movement", "no_ledger_movement"),
    ("Reversed operations", "reversed_operations"),
    ("Cancelled operations", "cancelled_operations"),
    ("Critical cases", "critical_cases"),
)

SUMMARY_LABELS: tuple[str, ...] = tuple(label for label, _ in SUMMARY_FIELDS)


def summarize(audits: Sequence[BudgetAudit]) -> AuditSummary:
    """Cuenta las clasificaciones del conjunto auditado.

    ``Ledger matches detail`` incluye los presupuestos donde el movimiento
    original coincide con el detalle (y también con la cabecera, cuando ambas
    coinciden). ``Ledger matches header only`` es el caso del incidente 000073.
    """
    items = list(audits)
    matches_detail = {
        LEDGER_MATCH_DETAIL,
        LEDGER_MATCH_DETAIL_AND_HEADER,
    }
    return AuditSummary(
        budgets_analyzed=len(items),
        consistent=sum(1 for a in items if a.budget_integrity == STATUS_OK),
        budget_header_mismatches=sum(
            1 for a in items if a.budget_integrity == BUDGET_HEADER_MISMATCH
        ),
        order_budget_drift=sum(1 for a in items if a.order_budget == ORDER_DRIFT),
        ledger_matches_detail=sum(1 for a in items if a.ledger_integrity in matches_detail),
        ledger_matches_header_only=sum(
            1 for a in items if a.ledger_integrity == LEDGER_MATCH_HEADER
        ),
        ledger_matches_neither=sum(
            1 for a in items if a.ledger_integrity == LEDGER_MATCH_NEITHER
        ),
        ambiguous_ledger=sum(1 for a in items if a.ledger_integrity == LEDGER_AMBIGUOUS),
        no_ledger_movement=sum(1 for a in items if a.ledger_integrity == LEDGER_NONE),
        reversed_operations=sum(1 for a in items if a.ledger_integrity == LEDGER_REVERSED),
        cancelled_operations=sum(
            1 for a in items if a.ledger_integrity == LEDGER_CANCELLED
        ),
        critical_cases=sum(1 for a in items if a.severity == SEVERITY_CRITICAL),
        potential_financial_difference=potential_financial_difference(items),
    )


def _money(value: Decimal | None) -> str:
    return "-" if value is None else f"{value:,.2f}"


def _plain(value: Decimal | None) -> str:
    return "" if value is None else f"{value:.2f}"


def _label(name: str) -> str:
    return f"{name + ':':<{LABEL_WIDTH}}"


def render_summary(
    summary: AuditSummary,
    *,
    protections: Iterable[str] = (),
) -> str:
    """Reporte general: conteos y diferencia financiera potencial."""
    lines = [SUMMARY_TITLE, "=" * len(SUMMARY_TITLE), ""]
    for name, value in summary.as_lines():
        lines.append(f"{_label(name)} {value}")
    lines.append("")
    lines.append(
        f"{_label('Potential financial difference')} "
        f"$ {_money(summary.potential_financial_difference)}"
    )
    lines.append("")
    lines.append(
        "Potential financial difference suma solo los presupuestos donde el "
        "movimiento"
    )
    lines.append(
        "ORIGINAL de cuenta corriente difiere del detalle del presupuesto, sin "
        "contar dos"
    )
    lines.append("veces el mismo movimiento. NO es la suma de todas las diferencias.")
    if protections:
        lines.append("")
        lines.append(f"READ-ONLY protections: {', '.join(protections)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------


def _section(title: str, lines: Sequence[tuple[str, object]]) -> list[str]:
    body = [f"{title}", "-" * len(title)]
    body.extend(f"{name + ':':<24} {value}" for name, value in lines)
    body.append("")
    return body


def _amounts_lines(prefix: str, amounts: Amounts) -> list[tuple[str, object]]:
    return [
        (f"{prefix}net", _money(amounts.net)),
        (f"{prefix}discount", _money(amounts.discount)),
        (f"{prefix}vat", _money(amounts.vat)),
        (f"{prefix}total", _money(amounts.total)),
    ]


def _bucket(amount: Decimal, count: int) -> str:
    return f"{_money(amount)} ({count} movement(s))"


def render_detail(audit: BudgetAudit) -> str:
    """Detalle de un presupuesto cruzando las tres fuentes históricas."""
    ledger = audit.ledger
    candidate = ledger.candidates[0] if ledger.candidates else None

    lines: list[str] = []
    lines.extend(
        _section(
            "BUDGET",
            [
                ("id", audit.budget_id),
                ("number", f"PRES-{audit.budget_number:06d}"),
                ("client", audit.client_name or "-"),
                ("order", f"OC-{audit.order_number:06d}" if audit.order_number else "-"),
                ("status", audit.budget_status or "-"),
                ("origin", audit.budget_origin or "-"),
                ("date", audit.budget_date or "-"),
            ],
        )
    )
    lines.extend(_section("HEADER", _amounts_lines("", audit.integrity.header)))
    lines.extend(_section("DETAIL", _amounts_lines("", audit.integrity.detail)))
    lines.extend(_section("DIFFERENCE", _amounts_lines("", audit.integrity.differences)))

    order = audit.order
    lines.extend(
        _section(
            "ORDER CURRENT STATE",
            [
                ("total", _money(order.order_total_current)),
                (
                    "difference_vs_budget_detail",
                    _money(order.difference) if order.difference is not None else "-",
                ),
                ("possible_post_budget_change", order.possible_post_budget_change),
                ("budget_created_at", order.budget_created_at or "-"),
                ("order_updated_at", order.order_updated_at or "-"),
                ("item_updated_at", order.item_updated_at or "-"),
            ],
        )
    )

    lines.extend(
        _section(
            "LEDGER",
            [
                ("movement_id", "|".join(str(i) for i in ledger.movement_ids) or "-"),
                (
                    "movement_type",
                    candidate.movement_type if candidate is not None else "-",
                ),
                ("date", (candidate.movement_date if candidate is not None else "-") or "-"),
                (
                    "reference",
                    (candidate.reference if candidate is not None else "-") or "-",
                ),
                ("source_ref", (candidate.source_ref if candidate is not None else "-") or "-"),
                ("original_amount", _money(ledger.original_total)),
                ("net", _money(ledger.original_amounts.net) if ledger.original_amounts else "-"),
                (
                    "discount",
                    _money(ledger.original_amounts.discount)
                    if ledger.original_amounts
                    else "-",
                ),
                ("vat", _money(ledger.original_amounts.vat) if ledger.original_amounts else "-"),
                ("total", _money(ledger.original_amounts.total) if ledger.original_amounts else "-"),
                (
                    "reversed",
                    f"{_money(ledger.reversals.amount)} "
                    f"({ledger.reversals.count} movement(s))",
                ),
                ("adjustments", _bucket(ledger.adjustments.amount, ledger.adjustments.count)),
                (
                    "adjustment_reversals",
                    _bucket(
                        ledger.adjustment_reversals.amount,
                        ledger.adjustment_reversals.count,
                    ),
                ),
                ("payments", _bucket(ledger.payments.amount, ledger.payments.count)),
                (
                    "payment_reversals",
                    _bucket(
                        ledger.payment_reversals.amount, ledger.payment_reversals.count
                    ),
                ),
                (
                    "payments_note",
                    "informativo: los pagos NO forman parte del importe original",
                ),
                ("ledger_matches_header", ledger.ledger_matches_header),
                ("ledger_matches_detail", ledger.ledger_matches_detail),
                (
                    "ledger_vs_detail_difference",
                    _money(ledger.ledger_detail_difference)
                    if ledger.ledger_detail_difference is not None
                    else "-",
                ),
                (
                    "ledger_vs_header_difference",
                    _money(ledger.ledger_header_difference)
                    if ledger.ledger_header_difference is not None
                    else "-",
                ),
            ],
        )
    )

    lines.extend(
        _section(
            "CLASSIFICATION",
            [
                ("budget_integrity", audit.budget_integrity),
                ("mismatched_components", "|".join(audit.integrity.components) or "-"),
                ("budget_header_difference", _money(audit.budget_header_difference)),
                ("order_budget", audit.order_budget),
                ("ledger_integrity", audit.ledger_integrity),
                ("severity", audit.severity),
                (
                    "potential_financial_difference",
                    _money(audit.potential_financial_difference),
                ),
            ],
        )
    )
    lines.append("No se realizo ninguna modificacion sobre la base.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def csv_row(audit: BudgetAudit) -> list[str]:
    """Una fila por presupuesto. Sin CUIT, descripciones ni datos de pago."""
    header = audit.integrity.header
    detail = audit.integrity.detail
    diff = audit.integrity.differences
    ledger = audit.ledger
    return [
        str(audit.budget_id),
        str(audit.budget_number),
        "" if audit.client_id is None else str(audit.client_id),
        audit.client_name or "",
        "" if audit.order_id is None else str(audit.order_id),
        "" if audit.order_number is None else str(audit.order_number),
        "" if audit.budget_date is None else str(audit.budget_date),
        audit.budget_status or "",
        audit.budget_origin or "",
        _plain(header.net),
        _plain(header.discount),
        _plain(header.vat),
        _plain(header.total),
        _plain(detail.net),
        _plain(detail.discount),
        _plain(detail.vat),
        _plain(detail.total),
        _plain(diff.net),
        _plain(diff.discount),
        _plain(diff.vat),
        _plain(diff.total),
        _plain(audit.order.order_total_current),
        _plain(audit.order.difference),
        "|".join(str(i) for i in ledger.movement_ids),
        _plain(ledger.original_total),
        _plain(ledger.ledger_detail_difference),
        _plain(ledger.ledger_header_difference),
        audit.budget_integrity,
        audit.order_budget,
        audit.ledger_integrity,
        audit.severity,
    ]


def write_csv(audits: Sequence[BudgetAudit], path) -> Path:
    """Escribe el CSV. Es la ÚNICA escritura del auditor y va al disco."""
    destino = Path(path)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for audit in audits:
            writer.writerow(csv_row(audit))
    return destino


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.audit_monetary_integrity",
        description=(
            "Auditoria READ-ONLY de integridad monetaria historica. No modifica "
            "la base: no repara, no migra y no genera movimientos."
        ),
    )
    parser.add_argument("--budget", type=int, help="Auditar un presupuesto por su id interno.")
    parser.add_argument(
        "--budget-number", type=int, help="Auditar un presupuesto por su numero visible (73 = PRES-000073)."
    )
    parser.add_argument("--csv", metavar="RUTA", help="Exportar una fila por presupuesto a CSV.")
    parser.add_argument(
        "--db", metavar="NOMBRE", help="Auditar otra base del mismo servidor (por ejemplo, la copia local)."
    )
    return parser


def _print_connection(target: AuditDatabaseTarget) -> None:
    """Informa a qué base se audita. Nunca imprime la contraseña."""
    for line in target.header_lines():
        print(line)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        target = resolve_audit_database(database_name=args.db)
    except Exception as exc:
        print(
            f"ERROR: no se pudo resolver la conexion de FEMAG: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    _print_connection(target)

    try:
        handle = open_audit_database(target=target)
    except Exception as exc:
        print(f"READ-ONLY protections: no aplicadas", file=sys.stderr)
        print(
            f"ERROR: no se pudo abrir la base en modo READ-ONLY: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "El auditor no cae a SQLite ni a otra base: se corrige la conexion y "
            "se vuelve a ejecutar.",
            file=sys.stderr,
        )
        return 2

    try:
        print(f"READ-ONLY protections: {', '.join(handle.protections)}")
        audits = MonetaryIntegrityAuditor(handle.database).run(
            budget_id=args.budget,
            budget_number=args.budget_number,
        )
        summary = summarize(audits)
        print()
        print(render_summary(summary))
        if audits:
            print()
        for audit in audits:
            print(render_detail(audit))
            print()
        if args.csv:
            destino = write_csv(audits, args.csv)
            print(f"CSV exportado: {destino} ({len(audits)} fila(s))")
    finally:
        handle.close()

    if (args.budget is not None or args.budget_number is not None) and not audits:
        print("No se encontro ningun presupuesto con ese criterio.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
