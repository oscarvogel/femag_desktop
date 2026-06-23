import shutil
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import load_settings
from app.models.base import utc_now
from app.models.system import BackupLog
from app.services.audit_service import AuditService


@dataclass(frozen=True)
class BackupResult:
    status: str
    file_path: str
    message: str


class BackupService:
    def __init__(
        self,
        backup_dir: Path | None = None,
        extra_dir: Path | None = None,
        dump_runner=None,
        audit_service: AuditService | None = None,
    ):
        settings = load_settings()
        self.backup_dir = Path(backup_dir or settings.backup_dir)
        self.extra_dir = Path(extra_dir) if extra_dir else settings.backup_extra_dir
        self.dump_runner = dump_runner or self._default_dump_runner
        self.audit_service = audit_service or AuditService()

    def _default_dump_runner(self, destination: Path):
        destination.write_text("Configure mysqldump for production backups.\n", encoding="utf-8")

    def run_manual_backup(self, user: str) -> BackupResult:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        filename = f"femag-backup-{utc_now().strftime('%Y%m%d-%H%M%S')}.sql"
        destination = self.backup_dir / filename
        log = BackupLog.create(status="running", file_path=str(destination))
        try:
            self.dump_runner(destination)
            if self.extra_dir:
                self.extra_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, self.extra_dir / filename)
            log.status = "success"
            log.finished_at = utc_now()
            log.message = "Backup manual generado"
            log.save()
            self.audit_service.record(
                user=user,
                module="Sistema",
                action="backup manual",
                record_ref=f"BackupLog:{log.id}",
                new_value={"file_path": str(destination), "status": "success"},
            )
            return BackupResult("success", str(destination), log.message)
        except Exception as exc:
            log.status = "error"
            log.finished_at = utc_now()
            log.message = str(exc)
            log.save()
            raise
