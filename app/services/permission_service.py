import unicodedata
from dataclasses import dataclass

from app.models.security import MenuItem, Permission, User, UserProfile
from app.services.audit_service import AuditService


ACTIONS = [
    "ver",
    "crear",
    "modificar",
    "anular",
    "eliminar",
    "imprimir",
    "reimprimir",
    "cerrar",
    "importar",
    "configurar",
]


MENU = {
    "Inicio": ["Dashboard", "Dashboard Gerencial", "Pendientes", "Accesos rápidos"],
    "Operaciones": ["Órdenes de carga", "Remitos", "Generar F150", "Hoja resumen / sobre de carga"],
    "Cuenta corriente": ["Clientes con saldo", "Movimientos", "Registrar pago", "Recibos", "Anulación de pagos"],
    "Maestros": [
        "Clientes",
        "Domicilios",
        "Productos",
        "Tipos de IVA",
        "Pallets / tipos de pallet",
        "Choferes",
        "Transportistas",
        "Camiones",
    ],
    "Importación": ["Importación"],
    "Sistema": ["Usuarios", "Perfiles", "Permisos por menú", "Parámetros", "Backups", "Auditoría"],
}

PROFILE_ACTIONS = {
    "Administrador": set(ACTIONS),
    "Gerencia": {"ver", "reimprimir"},
    "Secretaría": {"ver", "crear", "modificar", "imprimir", "reimprimir", "cerrar"},
    "Administración": {"ver", "crear", "modificar", "imprimir", "reimprimir", "cerrar"},
    "Solo consulta": {"ver", "reimprimir"},
}


def _profile_key(name: str) -> str:
    normalized = " ".join((name or "").strip().split()).casefold()
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.combining(character)
    )


_CANONICAL_PROFILE_BY_KEY = {_profile_key(name): name for name in PROFILE_ACTIONS}


def canonical_profile_name(name: str) -> str:
    """Return the official name for a built-in profile alias.

    Custom profiles are kept unchanged; only the built-in profiles are
    normalized so legacy names without accents cannot create duplicates.
    """
    normalized = " ".join((name or "").strip().split())
    return _CANONICAL_PROFILE_BY_KEY.get(_profile_key(normalized), normalized)


SENSITIVE_ACTIONS = {"anular remito", "modificar pago", "anular pago", "cambiar saldo inicial"}


@dataclass(frozen=True)
class MenuPermission:
    section: str
    title: str
    action: str


class PermissionService:
    def __init__(self, audit_service: AuditService | None = None):
        self.audit_service = audit_service or AuditService()

    def seed_defaults(self) -> None:
        database = UserProfile._meta.database
        with database.atomic():
            profiles = self._ensure_canonical_profiles()
            for section, titles in MENU.items():
                for order, title in enumerate(titles):
                    item, _ = MenuItem.get_or_create(
                        section=section,
                        title=title,
                        defaults={"sort_order": f"{order:03d}"},
                    )
                    for profile_name, allowed_actions in PROFILE_ACTIONS.items():
                        profile = profiles[profile_name]
                        for action in ACTIONS:
                            allowed = self._default_allowed(
                                profile_name=profile_name,
                                section=section,
                                title=title,
                                action=action,
                                allowed_actions=allowed_actions,
                            )
                            Permission.get_or_create(
                                profile=profile,
                                menu_item=item,
                                action=action,
                                defaults={"allowed": allowed},
                            )

    @staticmethod
    def _default_allowed(
        *,
        profile_name: str,
        section: str,
        title: str,
        action: str,
        allowed_actions: set[str],
    ) -> bool:
        if profile_name == "Administrador":
            return action in allowed_actions
        if profile_name == "Gerencia":
            return (
                action == "ver"
                and section == "Inicio"
                and title in {"Dashboard", "Dashboard Gerencial"}
            )
        if section == "Sistema":
            return False
        if section == "Inicio" and title == "Dashboard Gerencial":
            return False
        return action in allowed_actions

    def _ensure_canonical_profiles(self) -> dict[str, UserProfile]:
        """Create official profiles and consolidate legacy accent variants."""
        existing_profiles = list(UserProfile.select().order_by(UserProfile.id))
        profiles = {}
        for canonical_name in PROFILE_ACTIONS:
            candidates = [
                profile
                for profile in existing_profiles
                if canonical_profile_name(profile.name) == canonical_name
            ]
            target = next(
                (profile for profile in candidates if profile.name == canonical_name),
                None,
            )
            if target is None:
                target = candidates[0] if candidates else UserProfile.create(name=canonical_name)
                if target.name != canonical_name:
                    target.name = canonical_name
                    target.save()
            profiles[canonical_name] = target

            for duplicate in candidates:
                if duplicate.id != target.id:
                    self._merge_profile(duplicate, target)
        return profiles

    @staticmethod
    def _merge_profile(duplicate: UserProfile, target: UserProfile) -> None:
        """Move users and permissions before deleting a legacy profile."""
        for user in User.select().where(User.profile == duplicate):
            user.profile = target
            user.save()

        for permission in Permission.select().where(Permission.profile == duplicate):
            existing = Permission.get_or_none(
                (Permission.profile == target)
                & (Permission.menu_item == permission.menu_item_id)
                & (Permission.action == permission.action)
            )
            if existing is None:
                permission.profile = target
                permission.save()
            else:
                permission.delete_instance()
        duplicate.delete_instance()

    def has_permission(self, user: User, section: str, action: str, title: str | None = None) -> bool:
        query = (
            Permission.select()
            .join(MenuItem)
            .where(
                Permission.profile == user.profile,
                MenuItem.section == section,
                Permission.action == action,
                Permission.allowed == True,  # noqa: E712
            )
        )
        if title:
            query = query.where(MenuItem.title == title)
        return query.exists()

    def can_view_managerial_dashboard(self, user: User | None) -> bool:
        return bool(
            user is not None
            and user.active
            and self.has_permission(user, "Inicio", "ver", "Dashboard Gerencial")
        )

    @staticmethod
    def is_administrator(user: User | None) -> bool:
        return bool(
            user is not None
            and user.active
            and user.profile.name.strip().lower() == "administrador"
        )

    @staticmethod
    def is_manager(user: User | None) -> bool:
        return bool(
            user is not None
            and user.active
            and canonical_profile_name(user.profile.name) == "Gerencia"
        )

    def require_administrator(self, user: User | None) -> User:
        if not self.is_administrator(user):
            raise PermissionError("Esta operación requiere un administrador habilitado.")
        return user

    def require_managerial_dashboard(self, user: User | None) -> User:
        if not self.can_view_managerial_dashboard(user):
            raise PermissionError("No tiene permiso para ver el Dashboard Gerencial.")
        return user

    def permissions_for_profile(self, profile: UserProfile) -> dict[tuple[int, str], bool]:
        return {
            (permission.menu_item_id, permission.action): bool(permission.allowed)
            for permission in Permission.select().where(Permission.profile == profile)
        }

    def update_profile_permissions(
        self,
        actor: User,
        profile: UserProfile,
        values: dict[tuple[int, str], bool],
    ) -> int:
        self.require_administrator(actor)
        changed = 0
        for (menu_item_id, action), allowed in values.items():
            permission = Permission.get_or_none(
                Permission.profile == profile,
                Permission.menu_item == menu_item_id,
                Permission.action == action,
            )
            if permission is None:
                permission = Permission.create(
                    profile=profile,
                    menu_item=menu_item_id,
                    action=action,
                    allowed=bool(allowed),
                )
                old_allowed = None
            else:
                old_allowed = bool(permission.allowed)
                if old_allowed == bool(allowed):
                    continue
                permission.allowed = bool(allowed)
                permission.save()
            changed += 1
            self.audit_service.record(
                user=actor.username,
                module="Sistema",
                action="modificar permiso",
                record_ref=f"Permission:{permission.id}",
                old_value={
                    "profile": profile.name,
                    "menu_item_id": menu_item_id,
                    "action": action,
                    "allowed": old_allowed,
                },
                new_value={
                    "profile": profile.name,
                    "menu_item_id": menu_item_id,
                    "action": action,
                    "allowed": bool(allowed),
                },
            )
        return changed

    def requires_admin_password(self, action: str) -> bool:
        return action.lower() in SENSITIVE_ACTIONS
