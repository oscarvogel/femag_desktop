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


def _sin_password(mensaje: str | None, password: str) -> str:
    """Quita la contrasena de un mensaje de error antes de guardarlo.

    El mensaje de un ``mysqldump`` fallido viene de su stderr y queda escrito en
    ``BackupLog.message`` y en el log. ``mysqldump`` recibe la contrasena por
    ``MYSQL_PWD`` y no deberia imprimirla, pero "no deberia" no es una garantia
    y una contrasena en la base es un incidente, no un detalle de formato.
    """
    texto = (mensaje or "").strip() or "Fallo el respaldo de la base."
    if password and password in texto:
        texto = texto.replace(password, "***")
    return texto


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
        """Respalda la base de verdad, o falla. Nunca un archivo de mentira.

        Antes escribia un texto que decia "Configure mysqldump for production
        backups." y devolvia exito: el operador se llevaba un ``.sql`` que no
        era un dump, y el dashboard y la barra de estado mostraban "Ultimo
        backup: success". Eso es peor que no tener respaldo, porque da
        confianza falsa justo cuando alguien necesita recuperar.

        Asi que aca no hay camino que "funcione" sin respaldar: si MySQL no esta
        configurado, si no hay forma de volcar la base, o si el volcado falla,
        se levanta el error y ``run_manual_backup`` deja el ``BackupLog`` en
        ``error``.

        El motor se elige con ``pick_dump_runner``: usa ``mysqldump`` si el
        puesto lo tiene y, si no --que es el caso normal en un equipo con la
        app congelada-- cae al exportador en Python, que no necesita el cliente
        de MySQL instalado.
        """
        from app.config.secure_credentials import RuntimeConnection
        from app.config.settings import resolve_effective_connection_settings
        from app.services.mysql_dump import pick_dump_runner

        resolve_effective_connection_settings()
        settings = load_settings()
        if settings.db_engine != "mysql":
            raise RuntimeError(
                "El respaldo manual necesita MySQL y la configuracion efectiva dice "
                f"{settings.db_engine!r}. No se escribe ningun archivo."
            )
        connection = RuntimeConnection(
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
        )
        resultado = pick_dump_runner(dump_engine="auto")(
            connection, settings.db_name, destination
        )
        if not resultado.ok:
            raise RuntimeError(_sin_password(resultado.message, connection.password))

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
