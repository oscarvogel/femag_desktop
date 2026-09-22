from __future__ import annotations

import html
import os
import smtplib
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

from app.reports.managerial_account_risk import AccountRiskFilters, ManagerialAccountRiskService
from app.reports.managerial_dashboard import ManagerialDashboardService, ReportPeriod
from app.services.whatsapp_api_client import WhatsAppApiClient, WhatsAppApiConfig


def _money(value: float) -> str:
    return f"$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _compact_money(value: float) -> str:
    amount = float(value or 0)
    if abs(amount) >= 1_000_000:
        return f"$ {amount / 1_000_000:.2f} M".replace(".", ",")
    if abs(amount) >= 1_000:
        return f"$ {amount / 1_000:.1f} mil".replace(".", ",")
    return _money(amount)


@dataclass(frozen=True)
class ManagerialSummary:
    as_of: date
    today_snapshot: object
    month_snapshot: object
    risk_result: object
    overdue_top: tuple[dict, ...]
    attention_lines: tuple[str, ...]

    @property
    def overdue_ratio(self) -> float:
        total = float(self.risk_result.totals.balance or 0)
        return round((float(self.risk_result.totals.overdue or 0) / total) * 100, 1) if total else 0.0


@dataclass(frozen=True)
class ManagerialDeliveryConfig:
    email: str = ""
    phone: str = ""
    whatsapp_instance_id: str = ""
    whatsapp_api_url: str = ""
    whatsapp_api_key: str = ""
    whatsapp_api_timeout: float = 15.0
    auto_enabled: bool = False

    @classmethod
    def from_env(cls) -> "ManagerialDeliveryConfig":
        enabled = os.getenv("FEMAG_MANAGERIAL_AUTO_ENABLED", "false").strip().lower() in {
            "1", "true", "yes", "si", "sí", "on"
        }
        try:
            timeout = float(os.getenv("FEMAG_MANAGERIAL_WHATSAPP_API_TIMEOUT", "15"))
        except ValueError as exc:
            raise ValueError(
                "FEMAG_MANAGERIAL_WHATSAPP_API_TIMEOUT debe ser un número válido."
            ) from exc
        return cls(
            email=os.getenv("FEMAG_MANAGERIAL_EMAIL", "").strip(),
            phone=os.getenv("FEMAG_MANAGERIAL_WHATSAPP", "").strip(),
            whatsapp_instance_id=os.getenv("FEMAG_MANAGERIAL_WHATSAPP_INSTANCE", "").strip(),
            whatsapp_api_url=os.getenv("FEMAG_MANAGERIAL_WHATSAPP_API_URL", "").strip().rstrip("/"),
            whatsapp_api_key=os.getenv("FEMAG_MANAGERIAL_WHATSAPP_API_KEY", "").strip(),
            whatsapp_api_timeout=timeout,
            auto_enabled=enabled,
        )

    def whatsapp_client(self) -> WhatsAppApiClient:
        if not self.whatsapp_api_url:
            raise ValueError("Falta FEMAG_MANAGERIAL_WHATSAPP_API_URL.")
        if not self.whatsapp_api_key:
            raise ValueError("Falta FEMAG_MANAGERIAL_WHATSAPP_API_KEY.")
        if not self.whatsapp_instance_id:
            raise ValueError("Falta FEMAG_MANAGERIAL_WHATSAPP_INSTANCE.")
        return WhatsAppApiClient(
            WhatsAppApiConfig(
                base_url=self.whatsapp_api_url,
                api_key=self.whatsapp_api_key,
                instance_id=self.whatsapp_instance_id,
                timeout_seconds=self.whatsapp_api_timeout,
                enabled=True,
            )
        )


class ManagerialSummaryService:
    def __init__(
        self,
        *,
        dashboard_service: ManagerialDashboardService | None = None,
        risk_service: ManagerialAccountRiskService | None = None,
    ) -> None:
        self.dashboard_service = dashboard_service or ManagerialDashboardService()
        self.risk_service = risk_service or ManagerialAccountRiskService()

    def build(self, *, as_of: date | None = None) -> ManagerialSummary:
        target = as_of or date.today()
        today = self.dashboard_service.snapshot(ReportPeriod(target, target, "Hoy"))
        month = self.dashboard_service.snapshot(
            ReportPeriod(target.replace(day=1), target, "Este mes")
        )
        risk = self.risk_service.report(AccountRiskFilters(as_of=target))
        overdue_rows = [row for row in risk.rows if float(row["overdue"] or 0) > 0]
        overdue_rows.sort(
            key=lambda row: (float(row["overdue"] or 0), int(row["max_days_overdue"] or 0)),
            reverse=True,
        )
        attention: list[str] = []
        over_30 = [row for row in overdue_rows if int(row["max_days_overdue"] or 0) > 30]
        if over_30:
            attention.append(
                f"{len(over_30)} cliente(s) poseen deuda vencida con más de 30 días de atraso."
            )
        if float(risk.totals.due_7 or 0) > 0:
            attention.append(
                f"{_money(risk.totals.due_7)} vencen durante los próximos 7 días."
            )
        exceeded = [row for row in risk.rows if row.get("credit_exceeded")]
        if exceeded:
            attention.append(f"{len(exceeded)} cliente(s) superan su límite de crédito.")
        if not attention:
            attention.append("Sin situaciones críticas detectadas con las reglas actuales.")
        return ManagerialSummary(
            as_of=target,
            today_snapshot=today,
            month_snapshot=month,
            risk_result=risk,
            overdue_top=tuple(overdue_rows[:5]),
            attention_lines=tuple(attention),
        )

    def render_whatsapp(self, summary: ManagerialSummary) -> str:
        t = summary.today_snapshot
        m = summary.month_snapshot
        r = summary.risk_result.totals
        lines = [
            "📊 *FEMAG · Resumen gerencial*",
            summary.as_of.strftime("%d/%m/%Y"),
            "",
            "*Actividad*",
            f"💰 Despachos hoy: {_compact_money(t.valued_dispatches.current)}",
            f"📅 Acumulado mes: {_compact_money(m.valued_dispatches.current)}",
            f"🚚 Hoy: {t.tonnes.current:,.3f} TN · {int(t.orders.current)} carga(s)".replace(",", "X").replace(".", ",").replace("X", "."),
            "",
            "*Cartera*",
            f"🧾 Saldo clientes: {_compact_money(r.balance)}",
            f"🔴 Vencido: {_compact_money(r.overdue)} ({summary.overdue_ratio:.1f}%)".replace(".", ","),
            f"⏳ Próx. 7 días: {_compact_money(r.due_7)}",
        ]
        if summary.overdue_top:
            top = summary.overdue_top[0]
            lines += [
                "",
                "*Atención*",
                f"🔴 Mayor deuda vencida: {top['client_name']} · {_compact_money(top['overdue'])}",
                f"   Atraso máximo: {int(top['max_days_overdue'] or 0)} días",
            ]
        elif summary.attention_lines:
            lines += ["", "*Atención*", f"🟢 {summary.attention_lines[0]}"]
        lines += ["", "_FEMAG · Información gerencial_"]
        return "\n".join(lines)

    def render_email_html(self, summary: ManagerialSummary) -> str:
        t = summary.today_snapshot
        m = summary.month_snapshot
        r = summary.risk_result.totals

        def metric(label: str, value: str) -> str:
            return (
                '<td style="padding:8px;width:25%"><div style="background:#fff;border:1px solid #e2e8f0;'
                'border-radius:12px;padding:14px"><div style="font-size:11px;text-transform:uppercase;'
                f'color:#64748b;font-weight:700">{html.escape(label)}</div><div style="font-size:20px;'
                f'font-weight:800;color:#172033;margin-top:8px">{html.escape(value)}</div></div></td>'
            )

        top_rows = "".join(
            "<tr>"
            f"<td style='padding:8px;border-bottom:1px solid #e2e8f0'>{html.escape(str(row['client_name']))}</td>"
            f"<td style='padding:8px;text-align:right;border-bottom:1px solid #e2e8f0'>{html.escape(_money(row['overdue']))}</td>"
            f"<td style='padding:8px;text-align:right;border-bottom:1px solid #e2e8f0'>{int(row['max_days_overdue'] or 0)} días</td>"
            "</tr>"
            for row in summary.overdue_top
        ) or "<tr><td colspan='3' style='padding:12px;color:#64748b'>Sin deuda vencida.</td></tr>"
        attention = "".join(
            f"<li style='margin:6px 0'>{html.escape(line)}</li>" for line in summary.attention_lines
        )
        return f"""<!doctype html>
<html lang="es"><body style="margin:0;background:#f4f7fb;font-family:Arial,sans-serif;color:#172033">
<div style="max-width:900px;margin:auto;padding:24px">
<div style="background:#1559d6;color:#fff;border-radius:16px;padding:22px">
<div style="font-size:12px;font-weight:700;letter-spacing:.08em">FEMAG · INFORMACIÓN GERENCIAL</div>
<h1 style="margin:8px 0 0;font-size:26px">Resumen gerencial · {summary.as_of:%d/%m/%Y}</h1>
</div>
<table role="presentation" width="100%" style="border-spacing:4px;margin-top:12px"><tr>
{metric("Despachos hoy", _money(t.valued_dispatches.current))}
{metric("Despachos mes", _money(m.valued_dispatches.current))}
{metric("TN hoy", f"{t.tonnes.current:.3f} TN")}
{metric("Cargas hoy", str(int(t.orders.current)))}
</tr><tr>
{metric("Ticket promedio mes", _money(m.average_ticket.current))}
{metric("Saldo clientes", _money(r.balance))}
{metric("Saldo vencido", _money(r.overdue))}
{metric("Vence en 7 días", _money(r.due_7))}
</tr></table>
<div style="background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:18px;margin-top:12px">
<h2 style="font-size:17px;margin:0 0 10px">Cartera y vencimientos</h2>
<p>Vencido sobre saldo total: <strong>{summary.overdue_ratio:.1f}%</strong></p>
<table width="100%" style="border-collapse:collapse;font-size:13px">
<thead><tr><th style="text-align:left;padding:8px">Cliente</th><th style="text-align:right;padding:8px">Vencido</th><th style="text-align:right;padding:8px">Atraso máx.</th></tr></thead>
<tbody>{top_rows}</tbody></table>
</div>
<div style="background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:18px;margin-top:12px">
<h2 style="font-size:17px;margin:0 0 10px">Situaciones que requieren atención</h2>
<ul style="padding-left:20px;margin:0">{attention}</ul>
</div>
<div style="color:#64748b;font-size:11px;margin-top:16px">Generado automáticamente por FEMAG. Los indicadores usan la misma lógica del Dashboard Gerencial.</div>
</div></body></html>"""

    def write_preview(self, summary: ManagerialSummary) -> Path:
        path = Path(tempfile.gettempdir()) / "femag_resumen_gerencial_preview.html"
        path.write_text(self.render_email_html(summary), encoding="utf-8")
        return path

    @staticmethod
    def record_delivery(
        *,
        mode: str,
        channel: str,
        recipient: str,
        status: str,
        run_key: str | None = None,
        provider_message_id: str | None = None,
        error: str | None = None,
    ):
        from app.models.system import ManagerialSummaryDelivery
        from app.models.base import utc_now

        return ManagerialSummaryDelivery.create(
            run_key=run_key,
            mode=mode,
            channel=channel,
            recipient=recipient,
            status=status,
            provider_message_id=provider_message_id,
            error=error,
            finished_at=utc_now(),
        )

    def send_email(
        self,
        summary: ManagerialSummary,
        *,
        recipient: str,
        smtp_factory=smtplib.SMTP,
    ) -> None:
        from app.services.account_statement_mail_service import SmtpSettings

        config = SmtpSettings.from_env()
        address = (recipient or "").strip()
        if not address:
            raise ValueError("Indique el email del destinatario.")
        message = EmailMessage()
        message["Subject"] = f"FEMAG · Resumen gerencial · {summary.as_of:%d/%m/%Y}"
        message["From"] = config.sender
        message["To"] = address
        message.set_content("Resumen gerencial FEMAG. Este mensaje contiene una versión HTML.")
        message.add_alternative(self.render_email_html(summary), subtype="html")
        with smtp_factory(config.host, config.port, timeout=20) as smtp:
            if config.use_tls:
                smtp.starttls()
            smtp.login(config.username, config.password)
            smtp.send_message(message)

    def send_whatsapp(
        self,
        summary: ManagerialSummary,
        *,
        phone: str,
        instance_id: str,
        client: WhatsAppApiClient | None = None,
    ) -> dict:
        target_phone = "".join(ch for ch in (phone or "") if ch.isdigit())
        if not target_phone:
            raise ValueError("Indique el WhatsApp del destinatario.")
        resolved_instance = (instance_id or "").strip()
        if not resolved_instance:
            raise ValueError("Indique la instancia de WhatsApp gerencial.")
        api = client or ManagerialDeliveryConfig.from_env().whatsapp_client()
        return api.send_text(
            phone=target_phone,
            message=self.render_whatsapp(summary),
            instance_id=resolved_instance,
            external_ref=f"femag:managerial-summary:{summary.as_of.isoformat()}:{datetime.now().strftime('%H%M%S')}",
            actor_name="FEMAG resumen gerencial",
        )
