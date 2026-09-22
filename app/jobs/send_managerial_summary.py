from __future__ import annotations

import argparse
import json
from datetime import date

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.services.managerial_summary_service import (
    ManagerialDeliveryConfig,
    ManagerialSummaryService,
)


def _already_sent(run_key: str) -> bool:
    from app.models.system import ManagerialSummaryDelivery

    return (
        ManagerialSummaryDelivery.select()
        .where(ManagerialSummaryDelivery.run_key == run_key)
        .exists()
    )


def _open_database():
    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    return database


def run(*, as_of: date | None = None) -> dict[str, str]:
    """Ejecución diaria idempotente para Programador de tareas."""
    database = _open_database()
    try:
        config = ManagerialDeliveryConfig.from_env()
        if not config.auto_enabled:
            return {"status": "disabled"}

        service = ManagerialSummaryService()
        summary = service.build(as_of=as_of)
        results: dict[str, str] = {}

        if config.email:
            key = f"managerial:{summary.as_of.isoformat()}:email"
            if _already_sent(key):
                results["email"] = "duplicate"
            else:
                try:
                    service.send_email(summary, recipient=config.email)
                    service.record_delivery(
                        mode="automatic",
                        channel="email",
                        recipient=config.email,
                        status="sent",
                        run_key=key,
                    )
                    results["email"] = "sent"
                except Exception as exc:
                    service.record_delivery(
                        mode="automatic",
                        channel="email",
                        recipient=config.email,
                        status="failed",
                        error=str(exc),
                    )
                    results["email"] = f"failed: {exc}"

        if config.phone and config.whatsapp_instance_id:
            key = f"managerial:{summary.as_of.isoformat()}:whatsapp"
            if _already_sent(key):
                results["whatsapp"] = "duplicate"
            else:
                try:
                    response = service.send_whatsapp(
                        summary,
                        phone=config.phone,
                        instance_id=config.whatsapp_instance_id,
                    )
                    service.record_delivery(
                        mode="automatic",
                        channel="whatsapp",
                        recipient=config.phone,
                        status=str(response.get("status") or "accepted"),
                        provider_message_id=response.get("messageId"),
                        run_key=key,
                    )
                    results["whatsapp"] = "sent"
                except Exception as exc:
                    service.record_delivery(
                        mode="automatic",
                        channel="whatsapp",
                        recipient=config.phone,
                        status="failed",
                        error=str(exc),
                    )
                    results["whatsapp"] = f"failed: {exc}"

        return results or {"status": "no_channels"}
    finally:
        if not database.is_closed():
            database.close()


def send_now(*, as_of: date | None = None) -> dict[str, str]:
    """Envío manual de prueba; no exige AUTO_ENABLED ni aplica deduplicación."""
    database = _open_database()
    try:
        config = ManagerialDeliveryConfig.from_env()
        service = ManagerialSummaryService()
        summary = service.build(as_of=as_of)
        results: dict[str, str] = {}

        if config.email:
            try:
                service.send_email(summary, recipient=config.email)
                service.record_delivery(
                    mode="manual_cli",
                    channel="email",
                    recipient=config.email,
                    status="sent",
                )
                results["email"] = "sent"
            except Exception as exc:
                service.record_delivery(
                    mode="manual_cli",
                    channel="email",
                    recipient=config.email,
                    status="failed",
                    error=str(exc),
                )
                results["email"] = f"failed: {exc}"

        if config.phone and config.whatsapp_instance_id:
            try:
                response = service.send_whatsapp(
                    summary,
                    phone=config.phone,
                    instance_id=config.whatsapp_instance_id,
                )
                service.record_delivery(
                    mode="manual_cli",
                    channel="whatsapp",
                    recipient=config.phone,
                    status=str(response.get("status") or "accepted"),
                    provider_message_id=response.get("messageId"),
                )
                results["whatsapp"] = "sent"
            except Exception as exc:
                service.record_delivery(
                    mode="manual_cli",
                    channel="whatsapp",
                    recipient=config.phone,
                    status="failed",
                    error=str(exc),
                )
                results["whatsapp"] = f"failed: {exc}"

        return results or {"status": "no_channels"}
    finally:
        if not database.is_closed():
            database.close()


def health_check() -> dict[str, str]:
    """Valida DB y configuración de canales sin enviar mensajes."""
    result: dict[str, str] = {}
    database = None
    try:
        database = _open_database()
        database.execute_sql("SELECT 1")
        result["database"] = "ok"

        config = ManagerialDeliveryConfig.from_env()
        if config.phone:
            if not config.whatsapp_instance_id:
                result["whatsapp"] = "failed: falta FEMAG_MANAGERIAL_WHATSAPP_INSTANCE"
            else:
                try:
                    from app.services.whatsapp_api_client import WhatsAppApiClient

                    status = WhatsAppApiClient().get_instance_status(
                        config.whatsapp_instance_id
                    )
                    state = (
                        status.get("status")
                        or status.get("state")
                        or status.get("connectionStatus")
                        or "reachable"
                    )
                    result["whatsapp"] = f"ok: {state}"
                except Exception as exc:
                    result["whatsapp"] = f"failed: {exc}"
        else:
            result["whatsapp"] = "disabled"

        if config.email:
            try:
                from app.services.account_statement_mail_service import SmtpSettings

                smtp = SmtpSettings.from_env()
                result["email"] = f"ok: {smtp.host}:{smtp.port}"
            except Exception as exc:
                result["email"] = f"failed: {exc}"
        else:
            result["email"] = "disabled"

        result["auto"] = "enabled" if config.auto_enabled else "disabled"
        return result
    except Exception as exc:
        result["database"] = f"failed: {exc}"
        return result
    finally:
        if database is not None and not database.is_closed():
            database.close()


def _has_failures(result: dict[str, str]) -> bool:
    return any(str(value).startswith("failed:") for value in result.values())


def _print_result(result: dict[str, str]) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="FEMAG_Managerial_Summary",
        description="Resumen gerencial automático de FEMAG.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--health-check",
        action="store_true",
        help="Verifica DB, WhatsApp y correo sin enviar.",
    )
    mode.add_argument(
        "--send-now",
        action="store_true",
        help="Envía ahora por los canales configurados, sin deduplicación.",
    )
    mode.add_argument(
        "--daily",
        action="store_true",
        help="Ejecuta el envío diario idempotente para el Programador de tareas.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.health_check:
        result = health_check()
    elif args.send_now:
        result = send_now()
    else:
        # --daily y la ejecución sin argumentos hacen lo mismo para simplificar
        # el Programador de tareas.
        result = run()

    _print_result(result)
    return 1 if _has_failures(result) else 0


if __name__ == "__main__":
    raise SystemExit(main())
