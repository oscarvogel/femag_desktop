"""Resumen de cuenta corriente por vendedor, version detallada.

Genera el PDF con la composicion del saldo de cada cliente:
`VENDEDOR > CLIENTE > MOVIMIENTOS` (fecha, tipo, referencia, descripcion, debe,
haber, saldo acumulado y vencimiento).

No recalcula saldos: el detalle sale de `client_statement_detail()`, que a su vez
consume `movements_for_client()` y `running_balance_decimals()`, las mismas
funciones que alimentan la grilla de Cuenta Corriente. Las etiquetas de tipo,
referencia y descripcion se toman del extracto de cuenta corriente, para que el
detalle use las mismas reglas y no una segunda version.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.masters import Salesperson
from app.services.account_statement_print_service import (
    BRAND_ACCENT,
    BRAND_DARK,
    BRAND_LIGHT,
    INK,
    LINE,
    MUTED,
    ROW_ALT,
    WHITE,
    _balance_block,
    _canvas_factory,
    _description,
    _format_money,
    _money_decimal,
    _movement_date,
    _movement_type_label,
    _reference,
    _safe_filename_component,
)
from app.services.ledger_statement_detail import (
    ClientStatementDetail,
    client_statement_detail,
    detail_total,
)
from app.services.salesperson_portfolio_print_service import (
    ALL_SELLERS_SLUG,
    FILENAME_PREFIX,
    _document_header,
    _sorted_rows,
    _styles,
    _summary_table,
    portfolio_label,
    portfolio_totals,
)


REPORT_MARK = "detallado"
UNASSIGNED_LABEL = "Sin asignar"
DOCUMENT_TITLE = "RESUMEN DE CUENTA CORRIENTE - DETALLADO"
EMPTY_MESSAGE = "No hay clientes para los filtros seleccionados."

# 182 mm utiles con margenes de 14 mm en A4. Los anchos estan calculados para
# que ni un importe con miles ("$ 92.407.600,00") ni una referencia de pago
# ("REC-00000117") ni el rotulo "VENCIMIENTO" se partan en dos lineas.
COLUMN_WIDTHS = [16 * mm, 23 * mm, 22 * mm, 33 * mm, 22 * mm, 22 * mm, 23 * mm, 21 * mm]
COLUMN_LABELS = [
    ("FECHA", False),
    ("TIPO", False),
    ("REFERENCIA", False),
    ("DESCRIPCIÃ“N", False),
    ("DEBE", True),
    ("HABER", True),
    ("SALDO", True),
    ("VENCIMIENTO", True),
]


@dataclass(frozen=True)
class SalespersonGroup:
    """Los clientes de un vendedor dentro del reporte."""

    salesperson_id: int | None
    salesperson_name: str
    rows: list[dict]


def portfolio_detail_filename(
    salesperson: Salesperson | None,
    generated_at: datetime,
    *,
    slug: str | None = None,
) -> str:
    """Nombre del PDF detallado.

    Lleva un marca propia para que generar el resumen y el detalle el mismo dia
    no se pisen entre si.
    """
    if not slug:
        slug = (
            ALL_SELLERS_SLUG
            if salesperson is None
            else _safe_filename_component(salesperson.name, fallback="vendedor")
        )
    return f"{FILENAME_PREFIX}_{slug.lower()}_{REPORT_MARK}_{generated_at:%Y%m%d}.pdf"


def _salesperson_names(rows: list[dict]) -> dict[int, str]:
    """Nombre de cada vendedor en una sola consulta."""
    ids = {
        row.get("salesperson_id")
        for row in rows
        if row.get("salesperson_id") is not None
    }
    if not ids:
        return {}
    return {
        seller.id: (seller.name or "Vendedor")
        for seller in Salesperson.select().where(Salesperson.id << ids)
    }


def _group_total(rows: list[dict]) -> Decimal:
    return sum((_money_decimal(row.get("balance")) for row in rows), Decimal("0.00"))


def group_rows_by_salesperson(rows: list[dict]) -> list[SalespersonGroup]:
    """Agrupa las filas de la pantalla por vendedor, con los clientes del resumen.

    El agrupado es solo presentacion: el `salesperson_id` sale de la fila que ya
    armo `client_portfolio_rows()`. No se recalcula ningun saldo.
    """
    names = _salesperson_names(rows)
    buckets: dict[int | None, list[dict]] = {}
    for row in _sorted_rows(rows):
        buckets.setdefault(row.get("salesperson_id"), []).append(row)

    groups = [
        SalespersonGroup(
            salesperson_id=salesperson_id,
            salesperson_name=names.get(salesperson_id) or UNASSIGNED_LABEL,
            rows=bucket,
        )
        for salesperson_id, bucket in buckets.items()
    ]
    # Vendedor con mayor cartera primero; desempate por nombre para que sea estable.
    groups.sort(key=lambda group: (-_group_total(group.rows), group.salesperson_name))
    return groups


def _detail_styles() -> dict[str, ParagraphStyle]:
    """Estilos del resumen mas los propios de la tabla de movimientos."""
    styles = _styles()
    styles.update(
        {
            "seller_heading": ParagraphStyle(
                "portfolio_detail_seller",
                parent=styles["section"],
                fontSize=11,
                leading=14,
                spaceBefore=4,
                spaceAfter=1,
            ),
            "client_band": ParagraphStyle(
                "portfolio_detail_client_band",
                parent=styles["cell"],
                fontName="Helvetica-Bold",
                fontSize=8.4,
                leading=11,
                textColor=INK,
            ),
            "detail_cell": ParagraphStyle(
                "portfolio_detail_cell",
                parent=styles["cell"],
                fontSize=6.2,
                leading=8,
            ),
            "detail_cell_right": ParagraphStyle(
                "portfolio_detail_cell_right",
                parent=styles["cell"],
                fontSize=6.2,
                leading=8,
                alignment=TA_RIGHT,
            ),
            "balance_label": ParagraphStyle(
                "portfolio_detail_balance_label",
                parent=styles["cell"],
                fontName="Helvetica-Bold",
                fontSize=7.2,
                leading=9,
                textColor=WHITE,
            ),
            "balance_value": ParagraphStyle(
                "portfolio_detail_balance_value",
                parent=styles["cell"],
                fontName="Helvetica-Bold",
                fontSize=10.5,
                leading=13,
                textColor=WHITE,
                alignment=TA_RIGHT,
            ),
        }
    )
    return styles


def _client_band(detail: ClientStatementDetail, styles: dict) -> Paragraph:
    """Encabezado del cliente con su saldo actual.

    Viaja dentro de la tabla (`repeatRows`), asi que se repite en cada pagina:
    nunca queda un cliente separado de sus movimientos.
    """
    client = detail.client
    balance = _format_money(detail.balance)
    movement_word = "movimiento" if detail.movements_count == 1 else "movimientos"
    return Paragraph(
        f"<b>{escape(client.name or '-')}</b> Â· CUIT {escape(client.cuit or '-')} Â· "
        f"{detail.movements_count} {movement_word} Â· Saldo actual: {balance}",
        styles["client_band"],
    )


def _movements_table(detail: ClientStatementDetail, styles: dict) -> Table:
    band = _client_band(detail, styles)
    # Fila 0 = banda del cliente, fila 1 = columnas; ambas se repiten.
    data: list[list] = [
        [band] + [""] * (len(COLUMN_LABELS) - 1),
        [
            Paragraph(label, styles["table_header_right"] if right else styles["table_header"])
            for label, right in COLUMN_LABELS
        ],
    ]

    for row in detail.movements:
        movement = row.movement
        due = row.due_date.strftime("%d/%m/%Y") if row.due_date else ""
        data.append(
            [
                Paragraph(_movement_date(movement), styles["detail_cell"]),
                Paragraph(escape(_movement_type_label(movement)), styles["detail_cell"]),
                Paragraph(escape(_reference(movement)), styles["detail_cell"]),
                Paragraph(escape(_description(movement)), styles["detail_cell"]),
                Paragraph(_format_money(row.debit) if row.debit else "", styles["detail_cell_right"]),
                Paragraph(_format_money(row.credit) if row.credit else "", styles["detail_cell_right"]),
                Paragraph(_format_money(row.balance), styles["detail_cell_right"]),
                Paragraph(due, styles["detail_cell_right"]),
            ]
        )

    table = Table(
        data,
        colWidths=COLUMN_WIDTHS,
        repeatRows=2,
        hAlign="LEFT",
    )
    commands = [
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_LIGHT),
        ("LINEBEFORE", (0, 0), (0, 0), 3, BRAND_ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 1), (-1, 1), BRAND_DARK),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("TOPPADDING", (0, 0), (-1, 0), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2 * mm),
        ("TOPPADDING", (0, 1), (-1, -1), 1.8 * mm),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 1.8 * mm),
        ("LINEBELOW", (0, 1), (-1, -1), 0.35, LINE),
    ]
    for index in range(3, len(data), 2):
        commands.append(("BACKGROUND", (0, index), (-1, index), ROW_ALT))
    table.setStyle(TableStyle(commands))
    return table


def _seller_block(group: SalespersonGroup, details: list[ClientStatementDetail], styles: dict) -> list:
    """Encabezado de vendedor, clientes y total del vendedor."""
    story: list = [Paragraph(f"VENDEDOR: {escape(group.salesperson_name)}", styles["seller_heading"])]
    for detail in details:
        story.append(Spacer(1, 2 * mm))
        story.append(_movements_table(detail, styles))
    story.append(Spacer(1, 2 * mm))
    story.append(
        _balance_block(
            detail_total(details),
            styles,
            label=f"TOTAL {escape(group.salesperson_name).upper()}",
        )
    )
    return story


def export_salesperson_portfolio_detailed(
    *,
    salesperson: Salesperson | None,
    rows: list[dict],
    output_dir: str | Path,
    generated_at: datetime | None = None,
    label: str | None = None,
    slug: str | None = None,
) -> Path:
    """Genera el PDF detallado del vendedor y devuelve la ruta del archivo.

    `rows` son las filas de `client_portfolio_rows()` ya filtradas por la pantalla:
    el detalle respeta exactamente lo que el usuario esta viendo.
    """
    moment = generated_at or datetime.now()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    ordered = _sorted_rows(rows)
    totals = portfolio_totals(ordered)
    styles = _detail_styles()
    target = destination / portfolio_detail_filename(salesperson, moment, slug=slug)

    details_by_client = {
        row["client"].id: client_statement_detail(row["client"]) for row in ordered
    }

    document = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=20 * mm,
        title=DOCUMENT_TITLE,
        author="GRAEF HERMANOS S.R.L.",
    )

    story = [
        _document_header(
            salesperson,
            moment,
            styles,
            label=f"{portfolio_label(salesperson, label=label)} Â· Detallado",
        ),
        Spacer(1, 7 * mm),
        Paragraph("Resumen de cartera", styles["section"]),
        _summary_table(totals, styles),
        Spacer(1, 7 * mm),
        Paragraph("Detalle por vendedor y cliente", styles["section"]),
    ]

    if ordered:
        for group in group_rows_by_salesperson(ordered):
            story.extend(
                _seller_block(
                    group,
                    [details_by_client[row["client"].id] for row in group.rows],
                    styles,
                )
            )
            story.append(Spacer(1, 4 * mm))
        # Mismo numero que el TOTAL NETO del reporte resumido: la conciliacion
        # entre las dos versiones es visible en el propio PDF.
        story.append(
            _balance_block(totals["balance"], styles, label="TOTAL NETO CARTERA")
        )
    else:
        story.append(Paragraph(EMPTY_MESSAGE, styles["empty"]))

    document.build(story, canvasmaker=_canvas_factory(moment))
    return target
