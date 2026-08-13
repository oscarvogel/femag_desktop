from __future__ import annotations

import os
import smtplib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path


class MailConfigurationError(ValueError):
    pass


class AccountStatementMailError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str
    sender: str
    use_tls: bool

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SmtpSettings":
        values = os.environ if env is None else env
        required = (
            "FEMAG_SMTP_HOST",
            "FEMAG_SMTP_USER",
            "FEMAG_SMTP_PASSWORD",
            "FEMAG_SMTP_FROM",
        )
        missing = [name for name in required if not values.get(name, "").strip()]
        if missing:
            raise MailConfigurationError(
                "Falta configurar el correo en .env: " + ", ".join(missing)
            )
        try:
            port = int(values.get("FEMAG_SMTP_PORT", "587"))
        except ValueError as exc:
            raise MailConfigurationError("FEMAG_SMTP_PORT debe ser un numero valido.") from exc
        use_tls = values.get("FEMAG_SMTP_USE_TLS", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return cls(
            host=values["FEMAG_SMTP_HOST"].strip(),
            port=port,
            username=values["FEMAG_SMTP_USER"].strip(),
            password=values["FEMAG_SMTP_PASSWORD"],
            sender=values["FEMAG_SMTP_FROM"].strip(),
            use_tls=use_tls,
        )


def build_account_statement_message(
    *,
    client_name: str,
    recipient: str | None = None,
    recipients: Iterable[str] | None = None,
    sender: str,
    pdf_path: str | Path,
    subject: str | None = None,
) -> EmailMessage:
    addresses = _normalize_recipients(recipient=recipient, recipients=recipients)
    if not addresses:
        raise ValueError("El cliente no tiene un correo electronico configurado.")
    path = Path(pdf_path)
    if not path.is_file():
        raise ValueError("No se encontro el PDF del extracto para adjuntar.")

    message = EmailMessage()
    message["Subject"] = (subject or "").strip() or f"Extracto de cuenta corriente - {client_name}"
    message["From"] = sender
    message["To"] = ", ".join(addresses)
    message.set_content(
        f"Hola {client_name},\n\n"
        "Adjuntamos su extracto de cuenta corriente.\n\n"
        "Saludos.\nGRAEF HERMANOS S.R.L."
    )
    message.add_attachment(
        path.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=path.name,
    )
    return message


def send_account_statement(
    *,
    client_name: str,
    recipient: str | None = None,
    recipients: Iterable[str] | None = None,
    pdf_path: str | Path,
    subject: str | None = None,
    settings: SmtpSettings | None = None,
    smtp_factory=smtplib.SMTP,
) -> None:
    config = settings or SmtpSettings.from_env()
    message = build_account_statement_message(
        client_name=client_name,
        recipient=recipient,
        recipients=recipients,
        sender=config.sender,
        pdf_path=pdf_path,
        subject=subject,
    )
    try:
        with smtp_factory(config.host, config.port, timeout=20) as smtp:
            if config.use_tls:
                smtp.starttls()
            smtp.login(config.username, config.password)
            smtp.send_message(message)
    except Exception as exc:
        raise AccountStatementMailError(
            "No se pudo enviar el correo. Revise la configuracion SMTP y la conexion."
        ) from exc


def _normalize_recipients(
    *, recipient: str | None, recipients: Iterable[str] | None
) -> list[str]:
    values = list(recipients or [])
    if recipient:
        values.append(recipient)
    normalized: list[str] = []
    for value in values:
        address = (value or "").strip().lower()
        if address and address not in normalized:
            normalized.append(address)
    return normalized
