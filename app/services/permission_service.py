from dataclasses import dataclass

from app.models.security import MenuItem, Permission, User, UserProfile


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
    "Inicio": ["Dashboard", "Pendientes", "Accesos rápidos"],
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
    "Secretaria": {"ver", "crear", "modificar", "imprimir", "reimprimir", "cerrar"},
    "Secretaría": {"ver", "crear", "modificar", "imprimir", "reimprimir", "cerrar"},
    "Administracion": {"ver", "crear", "modificar", "imprimir", "reimprimir", "cerrar"},
    "Administración": {"ver", "crear", "modificar", "imprimir", "reimprimir", "cerrar"},
    "Solo consulta": {"ver", "reimprimir"},
}

SENSITIVE_ACTIONS = {"anular remito", "modificar pago", "anular pago", "cambiar saldo inicial"}


@dataclass(frozen=True)
class MenuPermission:
    section: str
    title: str
    action: str


class PermissionService:
    def seed_defaults(self) -> None:
        profiles = {name: UserProfile.get_or_create(name=name)[0] for name in PROFILE_ACTIONS}
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
                        allowed = action in allowed_actions
                        if section == "Sistema" and profile_name != "Administrador":
                            allowed = False
                        Permission.get_or_create(
                            profile=profile,
                            menu_item=item,
                            action=action,
                            defaults={"allowed": allowed},
                        )

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

    def requires_admin_password(self, action: str) -> bool:
        return action.lower() in SENSITIVE_ACTIONS
