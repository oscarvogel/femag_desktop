from __future__ import annotations

from datetime import date, datetime, time

from app.models.audit import AuditLog


class AuditQueryService:
    """Consulta de solo lectura sobre AuditLog para la pantalla general."""

    def filter_options(self) -> dict[str, list[str]]:
        return {
            "modules": self._distinct_values(AuditLog.module),
            "users": self._distinct_values(AuditLog.user),
            "actions": self._distinct_values(AuditLog.action),
        }

    def search(
        self,
        *,
        module: str | None = None,
        user: str | None = None,
        action: str | None = None,
        reference: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 500,
    ) -> list[AuditLog]:
        query = AuditLog.select()
        if module:
            query = query.where(AuditLog.module == module)
        if user:
            query = query.where(AuditLog.user == user)
        if action:
            query = query.where(AuditLog.action == action)
        if date_from:
            query = query.where(
                AuditLog.occurred_at >= datetime.combine(date_from, time.min)
            )
        if date_to:
            query = query.where(
                AuditLog.occurred_at <= datetime.combine(date_to, time.max)
            )
        rows = list(
            query.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            .limit(max(int(limit), 1))
        )
        needle = (reference or "").strip().casefold()
        if needle:
            rows = [
                row
                for row in rows
                if needle in self.display_reference(row).casefold()
                or needle in str(row.record_ref or "").casefold()
            ]
        return rows

    @staticmethod
    def _distinct_values(field) -> list[str]:
        values = []
        query = (
            AuditLog.select(field)
            .where(field.is_null(False))
            .distinct()
            .order_by(field)
        )
        for row in query:
            value = getattr(row, field.name)
            if value:
                values.append(str(value))
        return values

    @staticmethod
    def display_reference(row: AuditLog) -> str:
        old_value = row.old_value if isinstance(row.old_value, dict) else {}
        new_value = row.new_value if isinstance(row.new_value, dict) else {}
        values = {**old_value, **new_value}

        receipt = values.get("receipt_number")
        if receipt:
            return str(receipt)

        budget_number = values.get("budget_number")
        if budget_number is not None:
            try:
                return f"PRES-{int(budget_number):06d}"
            except (TypeError, ValueError):
                return str(budget_number)

        number = values.get("number")
        if number:
            return str(number)

        order_number = values.get("order_number")
        if order_number is not None:
            try:
                return f"OC-{int(order_number):06d}"
            except (TypeError, ValueError):
                return str(order_number)

        return str(row.record_ref or "")

    @staticmethod
    def transition(row: AuditLog) -> str:
        old_value = row.old_value if isinstance(row.old_value, dict) else {}
        new_value = row.new_value if isinstance(row.new_value, dict) else {}
        old_status = old_value.get("status")
        new_status = new_value.get("status")
        if old_status or new_status:
            return f"{old_status or '—'} → {new_status or '—'}"
        return ""

    @staticmethod
    def reason_or_summary(row: AuditLog) -> str:
        new_value = row.new_value if isinstance(row.new_value, dict) else {}
        if row.observation:
            return str(row.observation)
        for key in ("reason", "annulment_reason", "reference"):
            value = new_value.get(key)
            if value:
                return str(value)
        amount = new_value.get("total_amount", new_value.get("amount"))
        if amount is not None:
            try:
                return f"$ {abs(float(amount)):,.2f}"
            except (TypeError, ValueError):
                pass
        return ""
