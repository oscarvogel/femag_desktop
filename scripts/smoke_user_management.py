r"""Smoke del flujo de gestión de usuarios en producción.

Crea una DB SQLite temporal, levanta el esquema runtime, ejecuta el ciclo:
  - crear administrador inicial,
  - crear usuarios operativos,
  - login / cambio de clave / reset,
  - deshabilitar y rehabilitar,
  - regla del último administrador,
  - matriz de permisos por perfil,
  - auditoría de seguridad.

Sirve como validación manual. Se ejecuta con:

    .venv/Scripts/python.exe scripts/smoke_user_management.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

# Forzar DB SQLite limpia antes de importar modelos
_tmp = Path(tempfile.mkdtemp(prefix="femag_smoke_users_"))
os.environ["FEMAG_DB_BACKEND"] = "sqlite"
os.environ["FEMAG_SQLITE_PATH"] = str(_tmp / "smoke.sqlite")
os.environ["FEMAG_DEMO"] = "1"

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.models.audit import AuditLog  # noqa: E402
from app.models.security import (  # noqa: E402
    MenuItem,
    Permission,
    User,
    UserProfile,
)
from app.services.auth_service import AuthService  # noqa: E402
from app.services.permission_service import ACTIONS, PermissionService  # noqa: E402


def _check(label: str, condition: bool, detail: str = "") -> None:
    color = "\033[32m" if condition else "\033[31m"
    mark = "OK" if condition else "FAIL"
    print(f"{color}[{mark}] {label}\033[0m")
    if detail:
        print(f"    {detail}")
    if not condition:
        raise SystemExit(1)


def main() -> int:
    from app.config.database import bind_database
    from app.models import ALL_MODELS
    from peewee import SqliteDatabase

    db = SqliteDatabase(os.environ["FEMAG_SQLITE_PATH"])
    bind_database(db)
    db.connect(reuse_if_open=True)
    db.create_tables(ALL_MODELS)

    auth = AuthService()
    perms = PermissionService()

    print(f"DB temporal: {os.environ['FEMAG_SQLITE_PATH']}")
    print(f"Backend: {db.__class__.__name__}")
    print("")

    # 1) Estado inicial: sin usuarios
    _check("1. La base arranca sin usuarios", not User.select().exists())

    # 2) Crear administrador inicial
    admin = auth.create_initial_admin("admin", "Admin#2026", display_name="Administrador")
    _check(
        "2. Administrador inicial creado",
        admin.username == "admin" and admin.active and admin.profile.name == "Administrador",
        f"id={admin.id}, profile={admin.profile.name}, active={admin.active}",
    )

    # 3) No se puede crear otro admin inicial
    try:
        auth.create_initial_admin("otro", "x")
        _check("3. Rechaza segundo administrador inicial", False, "No lanzó ValueError")
    except ValueError as exc:
        _check("3. Rechaza segundo administrador inicial", True, f"mensaje: {exc}")

    # 4) Crear perfiles y usuarios operativos
    sec = auth.create_user(
        "secretaria",
        "Sec#2026",
        "Secretaría",
        display_name="Ana Secretaría",
        actor=admin,
    )
    viewer = auth.create_user("consulta", "Ver#2026", "Solo consulta", actor=admin)
    _check(
        "4. Usuarios operativos creados",
        sec.active and viewer.active,
        f"secretaria.id={sec.id}, consulta.id={viewer.id}",
    )

    # 5) Login funciona
    logged = auth.authenticate("secretaria", "Sec#2026")
    _check("5. Login del usuario secretaría", logged == sec)

    # 6) Login con clave incorrecta falla
    _check("6. Login con clave incorrecta", auth.authenticate("secretaria", "WRONG") is None)

    # 7) Cambio de clave propio
    auth.change_password(sec, "Nueva#2026", "Nueva#2026", actor=sec)
    _check(
        "7. Cambio de clave propio deshabilita la anterior",
        auth.authenticate("secretaria", "Sec#2026") is None
        and auth.authenticate("secretaria", "Nueva#2026") == sec,
    )

    # 8) Reset por administrador
    auth.change_password(sec, "Reset#2026", "Reset#2026", actor=admin, reset=True)
    _check(
        "8. Reset por admin deja activa la nueva clave",
        auth.authenticate("secretaria", "Reset#2026") == sec,
    )

    # 9) Usuario no admin no puede resetear a otro
    try:
        auth.change_password(viewer, "X", "X", actor=sec, reset=True)
        _check("9. No admin no puede resetear claves ajenas", False)
    except PermissionError as exc:
        _check("9. No admin no puede resetear claves ajenas", True, f"mensaje: {exc}")

    # 10) Deshabilitar usuario operativo funciona
    auth.set_active(sec, False, actor=admin)
    _check(
        "10. Usuario deshabilitado no puede loguearse",
        auth.authenticate("secretaria", "Reset#2026") is None,
    )
    auth.set_active(sec, True, actor=admin)
    _check(
        "11. Usuario rehabilitado vuelve a poder loguearse",
        auth.authenticate("secretaria", "Reset#2026") == sec,
    )

    # 12) Regla del último administrador: no se puede deshabilitar
    try:
        auth.set_active(admin, False, actor=admin)
        _check("12. Bloquea deshabilitar al último admin", False)
    except ValueError as exc:
        _check("12. Bloquea deshabilitar al último admin", True, f"mensaje: {exc}")

    # 13) No se puede cambiar perfil del último admin a uno no admin
    try:
        auth.update_user(
            admin,
            username=admin.username,
            profile_name="Secretaría",
            display_name=admin.display_name,
            active=admin.active,
            actor=admin,
        )
        _check("13. Bloquea degradar al último admin", False)
    except ValueError as exc:
        _check("13. Bloquea degradar al último admin", True, f"mensaje: {exc}")

    # 14) Crear segundo admin y deshabilitar al primero
    admin2 = auth.create_user("admin2", "Admin2#2026", "Administrador", actor=admin)
    _check(
        "14. Segundo admin creado",
        admin2.active and admin2.profile.name == "Administrador",
        f"admin2.id={admin2.id}",
    )
    try:
        auth.set_active(admin, False, actor=admin2)
    except Exception as exc:
        _check(
            "15. Primer admin se deshabilita porque existe otro",
            False,
            f"excepcion: {exc}",
        )
    # Refrescar desde DB para no quedar con cache vieja
    admin_fresh = User.get_by_id(admin.id)
    _check(
        "15. Primer admin se deshabilita porque existe otro",
        not admin_fresh.active,
        f"admin.active en DB={admin_fresh.active}, admin2.id={admin2.id}",
    )

    # 16) Rehabilitar primero
    auth.set_active(admin, True, actor=admin2)
    admin_fresh = User.get_by_id(admin.id)
    _check("16. Primer admin rehabilitado", admin_fresh.active)

    # 17) Admin no puede deshabilitar su propia sesión
    try:
        auth.set_active(admin2, False, actor=admin2)
        _check("17. No permite deshabilitar la sesión actual", False)
    except ValueError as exc:
        _check("17. No permite deshabilitar la sesión actual", True, f"mensaje: {exc}")

    # 18) Admin no puede cambiar su propio perfil
    try:
        auth.update_user(
            admin2,
            username=admin2.username,
            profile_name="Secretaría",
            display_name=admin2.display_name,
            active=admin2.active,
            actor=admin2,
        )
        _check("18. No permite cambiar el perfil de la sesión actual", False)
    except ValueError as exc:
        _check("18. No permite cambiar el perfil de la sesión actual", True, f"mensaje: {exc}")

    # 19) Usuario no admin no puede crear usuarios
    try:
        auth.create_user("intruso", "x", "Solo consulta", actor=sec)
        _check("19. Usuario no admin no puede crear usuarios", False)
    except PermissionError as exc:
        _check("19. Usuario no admin no puede crear usuarios", True, f"mensaje: {exc}")

    # 20) Matriz de permisos sembrada
    seeded_profiles = [p.name for p in UserProfile.select().order_by(UserProfile.name)]
    _check(
        "20. Perfiles por defecto sembrados",
        {"Administrador", "Secretaría", "Solo consulta"}.issubset(set(seeded_profiles)),
        f"perfiles: {seeded_profiles}",
    )
    menu_items = list(MenuItem.select())
    perms_count = Permission.select().count()
    _check(
        "21. Permisos por perfil sembrados",
        perms_count >= len(seeded_profiles) * len(menu_items) * len(ACTIONS),
        f"permisos: {perms_count}, items: {len(menu_items)}, perfiles: {len(seeded_profiles)}",
    )

    # 22) Admin tiene permiso total, secretaria no
    _check(
        "22. Administrador tiene permiso 'ver' en Clientes",
        perms.has_permission(admin, "Maestros", "ver", "Clientes"),
    )
    _check(
        "23. Secretaria tiene permiso 'ver' en Clientes",
        perms.has_permission(sec, "Maestros", "ver", "Clientes"),
    )
    _check(
        "24. Secretaria NO tiene permiso 'eliminar' en Clientes",
        not perms.has_permission(sec, "Maestros", "eliminar", "Clientes"),
    )
    _check(
        "25. Secretaria NO tiene permiso en Sistema -> Usuarios",
        not perms.has_permission(sec, "Sistema", "ver", "Usuarios"),
    )

    # 26) Admin puede actualizar permisos, secretaria no
    menu_item = MenuItem.get(MenuItem.title == "Clientes")
    changed = perms.update_profile_permissions(
        admin2,
        sec.profile,
        {(menu_item.id, "eliminar"): True},
    )
    _check(
        "26. Admin actualiza permisos del perfil",
        changed >= 1 and perms.has_permission(sec, "Maestros", "eliminar", "Clientes"),
    )

    # 27) Auditoría tiene los eventos clave
    actions = sorted({row.action for row in AuditLog.select()})
    must_have = {
        "crear usuario",
        "cambiar contraseña",
        "restablecer contraseña",
        "habilitar usuario",
        "deshabilitar usuario",
        "modificar permiso",
        "login exitoso",
        "login fallido",
    }
    missing = must_have - set(actions)
    _check(
        "27. Auditoría cubre los eventos de seguridad",
        not missing,
        f"acciones registradas: {actions}",
    )

    print("")
    print("\033[32mSMOKE OK: gestion de usuarios validada de punta a punta.\033[0m")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(1)
