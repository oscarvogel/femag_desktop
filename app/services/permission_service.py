from dataclasses import dataclass

from app.models.security import MenuItem, Permission, User, UserProfile
from app.services.menu_service import MenuService


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

PROFILE_ACTIONS = {
    "Administrador": set(ACTIONS),
    "Secretaria": {"ver", "crear", "modificar", "imprimir", "reimprimir", "cerrar"},
    "Secretaría": {"ver", "crear", "modificar", "imprimir", "reimprimir", "cerrar"},
    "Administracion": {"ver", "crear", "modificar", "imprimir", "reimprimir", "cerrar"},
    "Administración": {"ver", "crear", "modificar", "imprimir", "reimprimir", "cerrar"},
    "Solo consulta": {"ver", "reimprimir"},
}

PROFILE_MENU_KEYS = {
    "Administrador": "*",
    "Secretaria": {
        "inicio.dashboard",
        "inicio.pendientes",
        "operaciones.ordenes_carga",
        "operaciones.remitos",
        "operaciones.f150",
        "operaciones.hoja_resumen",
        "maestros.clientes",
        "maestros.domicilios",
        "maestros.productos",
        "maestros.choferes",
        "maestros.transportistas",
        "maestros.camiones",
        "maestros.tipos_pallets",
    },
    "Secretaría": {
        "inicio.dashboard",
        "inicio.pendientes",
        "operaciones.ordenes_carga",
        "operaciones.remitos",
        "operaciones.f150",
        "operaciones.hoja_resumen",
        "maestros.clientes",
        "maestros.domicilios",
        "maestros.productos",
        "maestros.choferes",
        "maestros.transportistas",
        "maestros.camiones",
        "maestros.tipos_pallets",
    },
    "Administracion": {
        "inicio.dashboard",
        "cuenta_corriente.clientes_saldo",
        "cuenta_corriente.registrar_pago",
        "cuenta_corriente.recibos",
    },
    "Administración": {
        "inicio.dashboard",
        "cuenta_corriente.clientes_saldo",
        "cuenta_corriente.registrar_pago",
        "cuenta_corriente.recibos",
    },
    "Solo consulta": {
        "inicio.dashboard",
        "operaciones.ordenes_carga",
        "maestros.clientes",
        "maestros.productos",
    },
}

SENSITIVE_ACTIONS = {"anular remito", "modificar pago", "anular pago", "cambiar saldo inicial"}


@dataclass(frozen=True)
class MenuPermission:
    section: str
    title: str
    action: str


class PermissionService:
    def seed_defaults(self) -> None:
        MenuService().seed_default_menu()
        profiles = {name: UserProfile.get_or_create(name=name)[0] for name in PROFILE_ACTIONS}
        menu_items = MenuItem.select().where(MenuItem.requires_permission == True)  # noqa: E712
        for item in menu_items:
            for profile_name, allowed_actions in PROFILE_ACTIONS.items():
                profile = profiles[profile_name]
                profile_menu_keys = PROFILE_MENU_KEYS[profile_name]
                menu_allowed = profile_menu_keys == "*" or item.action_key in profile_menu_keys
                for action in ACTIONS:
                    allowed = menu_allowed and action in allowed_actions
                    Permission.get_or_create(
                        profile=profile,
                        menu_item=item,
                        action=action,
                        defaults={"allowed": allowed},
                    )

    def has_menu_permission(self, user: User, menu_item_id: int, action: str = "ver") -> bool:
        if user.profile.name == "Administrador":
            return True
        return (
            Permission.select()
            .where(
                Permission.profile == user.profile,
                Permission.menu_item_id == menu_item_id,
                Permission.action == action,
                Permission.allowed == True,  # noqa: E712
            )
            .exists()
        )

    def has_permission(self, user: User, section: str, action: str, title: str | None = None) -> bool:
        if user.profile.name == "Administrador":
            return True
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

    def requires_admin_password(self, action: str) -> bool:
        return action.lower() in SENSITIVE_ACTIONS
