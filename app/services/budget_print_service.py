from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.budgets import Budget
from app.models.load_orders import LoadOrder
from app.services.audit_service import AuditService
from app.services.budget_service import BudgetService


class BudgetPrintService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()
        self.budget_service = BudgetService(current_user, self.audit_service)
        self.styles = getSampleStyleSheet()

    def export_for_load_order(self, order: LoadOrder, output_dir: str | Path) -> list[Path]:
        budgets = self.budget_service.ensure_for_load_order(order)
        return [self.export_pdf(budget, output_dir) for budget in budgets]

    def export_pdf(self, budget: Budget, output_dir: str | Path) -> Path:
        budget = Budget.get_by_id(budget.id)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"presupuesto_{budget.budget_number:06d}.pdf"
        self._build_pdf(budget, target)
        self.audit_service.record(
            user=self.current_user,
            module="Presupuestos",
            action="imprimir",
            record_ref=f"Budget:{budget.id}",
            new_value={
                "budget_number": budget.budget_number,
                "client_id": budget.client_id,
                "load_order_id": budget.load_order_id,
                "file_path": str(target),
            },
        )
        return target

    def _build_pdf(self, budget: Budget, target: Path) -> None:
        doc = SimpleDocTemplate(
            str(target),
            pagesize=A4,
            rightMargin=14 * mm,
            leftMargin=14 * mm,
            topMargin=14 * mm,
            bottomMargin=14 * mm,
            title=f"Presupuesto {budget.display_number}",
        )
        story = [
            Paragraph("PRESUPUESTO", self.styles["Title"]),
            Spacer(1, 3 * mm),
            self._header_table(budget),
            Spacer(1, 6 * mm),
            self._client_table(budget),
            Spacer(1, 6 * mm),
            self._items_table(budget),
            Spacer(1, 5 * mm),
            self._totals_table(budget),
        ]
        if budget.observations:
            story.extend(
                [
                    Spacer(1, 6 * mm),
                    Paragraph(f"<b>Observaciones:</b> {budget.observations}", self.styles["BodyText"]),
                ]
            )
        doc.build(story)

    def _header_table(self, budget: Budget) -> Table:
        reference = budget.load_order_reference or "Presupuesto manual"
        data = [[
            f"Presupuesto N° {budget.budget_number:06d}",
            f"Fecha: {budget.issue_date:%d/%m/%Y}",
            f"Referencia: {reference}",
        ]]
        table = Table(data, colWidths=[58 * mm, 48 * mm, 72 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    def _client_table(self, budget: Budget) -> Table:
        client = budget.client
        rows = [
            ["Cliente", client.name],
            ["CUIT", getattr(client, "cuit", None) or "-"],
        ]
        table = Table(rows, colWidths=[30 * mm, 148 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return table

    def _items_table(self, budget: Budget) -> Table:
        rows = [["Producto", "Cantidad", "Unidad", "P. unitario", "Desc.", "IVA", "Total"]]
        for item in budget.items.order_by():
            rows.append(
                [
                    item.product.name,
                    self._quantity(item.quantity),
                    item.unit,
                    self._money(item.unit_price),
                    f"{item.discount_percentage:.2f}%",
                    f"{item.vat_percentage:.2f}%",
                    self._money(item.total),
                ]
            )
        table = Table(
            rows,
            colWidths=[58 * mm, 22 * mm, 17 * mm, 27 * mm, 18 * mm, 16 * mm, 26 * mm],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return table

    def _totals_table(self, budget: Budget) -> Table:
        rows = [
            ["Neto", self._money(budget.net_amount)],
            ["Descuentos", self._money(budget.discount_amount)],
            ["IVA", self._money(budget.vat_amount)],
            ["TOTAL", self._money(budget.total_amount)],
        ]
        table = Table(rows, colWidths=[45 * mm, 35 * mm], hAlign="RIGHT")
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
        return table

    @staticmethod
    def _money(value: float) -> str:
        return f"$ {float(value or 0):,.2f}"

    @staticmethod
    def _quantity(value: float) -> str:
        value = float(value or 0)
        return f"{value:.0f}" if value.is_integer() else f"{value:.3f}".rstrip("0").rstrip(".")
