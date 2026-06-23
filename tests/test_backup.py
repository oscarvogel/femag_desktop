from pathlib import Path


def test_backup_service_records_manual_backup_and_audit(db, tmp_path):
    from app.models.audit import AuditLog
    from app.models.system import BackupLog
    from app.services.backup_service import BackupService

    backup_dir = tmp_path / "backups"
    extra_dir = tmp_path / "extra"
    result = BackupService(
        backup_dir=backup_dir,
        extra_dir=extra_dir,
        dump_runner=lambda destination: Path(destination).write_text("dump", encoding="utf-8"),
    ).run_manual_backup(user="admin")

    assert result.status == "success"
    assert Path(result.file_path).exists()
    assert (extra_dir / Path(result.file_path).name).exists()
    assert BackupLog.select().count() == 1
    assert AuditLog.select().where(AuditLog.action == "backup manual").count() == 1
