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


def _localized_number(value: float, decimals: int = 2) -> str:
    return (
        f"{float(value or 0):,.{decimals}f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def _compact_money(value: float) -> str:
    amount = float(value or 0)
    if abs(amount) >= 1_000_000:
        return f"$ {_localized_number(amount / 1_000_000, 2)} M"
    if abs(amount) >= 1_000:
        return f"$ {_localized_number(amount / 1_000, 1)} mil"
    return _money(amount)


def _variation_text(metric, snapshot) -> str:
    """Variación contra el período equivalente, con el texto del Dashboard Gerencial.

    ``variation_percent`` es ``None`` cuando el período anterior fue 0 y el actual no:
    ahí no hay contra qué comparar y se dice, en vez de inventar un porcentaje.

    El rango comparado viaja explícito para que el número sea auditable: el
    resumen se lee por WhatsApp, sin la tarjeta del dashboard al lado.
    """
    variation = metric.variation_percent
    compared = snapshot.previous_period.describe_range()
    if variation is None:
        return "Sin base comparable" if metric.current else f"0,0% vs {compared}"
    prefix = "+" if variation > 0 else ""
    return f"{prefix}{_localized_number(variation, 1)}% vs {compared}"


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


@dataclass(frozen=True)
class CommercialAlert:
    product_id: int
    product_name: str
    variation_percent: float | None
    lost_count: int
    lost_tonnes: float
    top_client_name: str
    top_client_tonnes: float
    current_range: str
    previous_range: str


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
            overdue_top=tuple(overdue_rows[:10]),
            attention_lines=tuple(attention),
        )

    def commercial_followup(
        self,
        summary: ManagerialSummary,
        *,
        min_drop_percent: float = 15.0,
        min_lost_tonnes: float = 1.0,
        top_n_products: int = 10,
        max_alerts: int = 3,
    ) -> list[CommercialAlert]:
        """Alertas de recompra para el resumen diario, sin proceso de envío propio.

        Criterio configurable: caída de TN >= ``min_drop_percent`` frente al
        período equivalente **y** al menos un cliente sin recompra con
        referencia >= ``min_lost_tonnes``. Si no hay datos o no se cumple el
        criterio, devuelve [] y el render no inventa conclusiones.
        """
        period = summary.month_snapshot.period
        previous = summary.month_snapshot.previous_period
        try:
            current_tops = self.dashboard_service.top_products(period, limit=top_n_products)
            previous_tops = self.dashboard_service.top_products(previous, limit=top_n_products)
        except Exception:
            return []
        # Un producto que se fugó por completo tiene 0 TN actual y nunca entra
        # al top del período actual: hay que unir ambos tops por product_id.
        tops: dict[int, dict] = {}
        for top in (*current_tops, *previous_tops):
            tops.setdefault(int(top["product_id"]), top)
        ordered = sorted(
            tops.values(),
            key=lambda t: -max(float(t.get("tonnes") or 0), float(t.get("previous_tonnes") or 0)),
        )[:top_n_products]
        alerts: list[CommercialAlert] = []
        for top in ordered:
            pid = int(top["product_id"])
            rep = self.dashboard_service.product_repurchase_summary(period, previous, product_id=pid)
            var = rep["variation_percent"]
            if var is None or var > -abs(min_drop_percent):
                continue
            if rep["count_sin_recompra"] <= 0 or rep["lost_tonnes"] < min_lost_tonnes:
                continue
            rows = self.dashboard_service.product_client_repurchase(period, previous, product_id=pid)
            lost = sorted(
                [r for r in rows if r["status"] == "sin_recompra"],
                key=lambda r: -r["previous_kilos"],
            )
            top_client = lost[0] if lost else None
            alerts.append(
                CommercialAlert(
                    product_id=pid,
                    product_name=top["name"],
                    variation_percent=var,
                    lost_count=rep["count_sin_recompra"],
                    lost_tonnes=rep["lost_tonnes"],
                    top_client_name=top_client["client_name"] if top_client else "",
                    top_client_tonnes=top_client["previous_tonnes"] if top_client else 0.0,
                    current_range=period.describe_range(),
                    previous_range=previous.describe_range(),
                )
            )
        alerts.sort(key=lambda a: -a.lost_tonnes)
        return alerts[:max_alerts]

    def render_whatsapp(self, summary: ManagerialSummary) -> str:
        t = summary.today_snapshot
        m = summary.month_snapshot
        r = summary.risk_result.totals
        activity_line = (
            "🚚 Sin despachos registrados hoy"
            if float(t.tonnes.current or 0) == 0 and int(t.orders.current or 0) == 0
            else (
                f"🚚 Hoy: {_localized_number(t.tonnes.current, 3)} TN · "
                f"{int(t.orders.current)} carga(s)"
            )
        )
        lines = [
            "📊 *FEMAG · Resumen gerencial*",
            summary.as_of.strftime("%d/%m/%Y"),
            "",
            "*Actividad*",
            f"💰 Despachos hoy: {_compact_money(t.valued_dispatches.current)}",
            f"📅 Acumulado del mes: {_compact_money(m.valued_dispatches.current)} "
            f"({_variation_text(m.valued_dispatches, m)})",
            activity_line,
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
        for alert in self.commercial_followup(summary):
            var = f"{alert.variation_percent:.1f}%".replace(".", ",")
            lines += [
                "",
                "📉 *Seguimiento comercial*",
                f"{alert.product_name}: {var} en TN vs. período equivalente "
                f"({alert.previous_range} → {alert.current_range}).",
                f"{alert.lost_count} cliente(s) sin recompra "
                f"({_localized_number(alert.lost_tonnes, 2)} TN de referencia).",
                f"Mayor oportunidad: {alert.top_client_name} — "
                f"{_localized_number(alert.top_client_tonnes, 2)} TN.",
                "Consultar informe completo en FEMAG.",
            ]
            break  # una sola alerta en WhatsApp para no sobrecargar el mensaje
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
            f"<td style='padding:8px;text-align:right;border-bottom:1px solid #e2e8f0'>{html.escape(_money(row['balance']))}</td>"
            f"<td style='padding:8px;text-align:right;border-bottom:1px solid #e2e8f0'>{html.escape(_money(row['overdue']))}</td>"
            f"<td style='padding:8px;text-align:right;border-bottom:1px solid #e2e8f0'>{html.escape(_money(row['due_future']))}</td>"
            f"<td style='padding:8px;text-align:right;border-bottom:1px solid #e2e8f0'>{int(row['max_days_overdue'] or 0)} días</td>"
            f"<td style='padding:8px;text-align:right;border-bottom:1px solid #e2e8f0'>{row['oldest_unpaid_due'].strftime('%d/%m/%Y') if row.get('oldest_unpaid_due') else '—'}</td>"
            "</tr>"
            for row in summary.overdue_top
        ) or "<tr><td colspan='6' style='padding:12px;color:#64748b'>Sin deuda vencida.</td></tr>"
        attention = "".join(
            f"<li style='margin:6px 0'>{html.escape(line)}</li>" for line in summary.attention_lines
        )
        alerts = self.commercial_followup(summary)
        commercial_blocks = []
        for alert in alerts:
            rows = self.dashboard_service.product_client_repurchase(
                summary.month_snapshot.period,
                summary.month_snapshot.previous_period,
                product_id=alert.product_id,
            )
            lost = sorted(
                [r for r in rows if r["status"] == "sin_recompra"],
                key=lambda r: -r["previous_kilos"],
            )[:5]
            items = "".join(
                f"<li style='margin:4px 0'>{html.escape(r['client_name'])} — "
                f"{r['previous_tonnes']:.3f} TN de referencia "
                f"(últ. {r['previous_last_date'] or '—'})</li>"
                for r in lost
            ) or "<li>Sin detalle.</li>"
            var = f"{alert.variation_percent:.1f}%".replace(".", ",")
            commercial_blocks.append(
                f"<h3 style='font-size:14px;margin:12px 0 6px'>{html.escape(alert.product_name)} · {var} TN</h3>"
                f"<p style='color:#64748b;margin:0 0 6px'>{html.escape(alert.previous_range)} → "
                f"{html.escape(alert.current_range)} · {alert.lost_count} sin recompra "
                f"({alert.lost_tonnes:.3f} TN). Ver informe completo en FEMAG.</p>"
                f"<ul style='padding-left:20px;margin:0'>{items}</ul>"
            )
        commercial_section = (
            "<div style='background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:18px;margin-top:12px'>"
            "<h2 style='font-size:17px;margin:0 0 10px'>Seguimiento comercial (recompra)</h2>"
            + ("".join(commercial_blocks) if commercial_blocks else "<p style='color:#64748b'>Sin alertas de recompra con el criterio actual.</p>")
            + "</div>"
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
{metric("Cartera vencida", f"{summary.overdue_ratio:.1f}%")}
</tr></table>
<div style="background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:18px;margin-top:12px">
<h2 style="font-size:17px;margin:0 0 10px">Cuenta corriente y deuda vencida</h2>
<p style="color:#64748b;margin-top:0">Fecha de corte: <strong>{summary.as_of:%d/%m/%Y}</strong></p>
<table role="presentation" width="100%" style="border-spacing:4px;margin:0 0 12px"><tr>
{metric("Clientes con deuda", str(int(r.clients_with_debt)))}
{metric("Clientes vencidos", str(int(r.clients_overdue)))}
{metric("Vence en 7 días", _money(r.due_7))}
{metric("Vence en 15 días", _money(r.due_15))}
</tr><tr>
{metric("Vence en 30 días", _money(r.due_30))}
<td colspan="3"></td>
</tr></table>
<h3 style="font-size:14px;margin:14px 0 8px">10 mayores deudas vencidas</h3>
<table width="100%" style="border-collapse:collapse;font-size:13px">
<thead><tr><th style="text-align:left;padding:8px">Cliente</th><th style="text-align:right;padding:8px">Saldo</th><th style="text-align:right;padding:8px">Vencido</th><th style="text-align:right;padding:8px">A vencer</th><th style="text-align:right;padding:8px">Días atraso</th><th style="text-align:right;padding:8px">Venc. más antiguo</th></tr></thead>
<tbody>{top_rows}</tbody></table>
</div>
<div style="background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:18px;margin-top:12px">
<h2 style="font-size:17px;margin:0 0 10px">Situaciones que requieren atención</h2>
<ul style="padding-left:20px;margin:0">{attention}</ul>
</div>
{commercial_section}
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
