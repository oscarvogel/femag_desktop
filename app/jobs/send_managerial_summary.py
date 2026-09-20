from __future__ import annotations

from datetime import date

from peewee import IntegrityError

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


def run(*, as_of: date | None = None) -> dict[str, str]:
    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)

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


def main() -> int:
    result = run()
    print(result)
    failed = any(str(value).startswith("failed:") for value in result.values())
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
