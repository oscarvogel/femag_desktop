from dataclasses import dataclass, field

from app.models.security import MenuItem, Permission, User
from app.services.permission_service import MENU


PLACEHOLDER_MESSAGE = "Funcionalidad prevista para una próxima entrega."

REAL_MODULES = {
    "Dashboard": "dashboard",
    "Pendientes": "pending",
    "Órdenes de carga": "load_orders",
    "Clientes": "clients",
    "Domicilios": "addresses",
    "Productos": "products",
    "Choferes": "drivers",
    "Transportistas": "carriers",
    "Camiones": "trucks",
    "Tipos de pallets": "pallet_types",
    "Pallets / tipos de pallet": "pallet_types",
    "Usuarios": "users",
    "Perfiles": "profiles",
    "Permisos": "permissions",
    "Permisos por menú": "permissions",
    "Parámetros": "settings",
    "Backups": "backups",
    "Auditoría": "audit",
    "Importación": "imports",
    "Accesos rápidos": "quick_actions",
}


@dataclass(frozen=True)
class MenuNode:
    title: str
    route_key: str | None = None
    action_key: str | None = None
    is_placeholder: bool = False
    disabled_reason: str | None = None
    children: list["MenuNode"] = field(default_factory=list)


class MenuService:
    def get_menu_tree_for_user(self, user: User) -> list[MenuNode]:
        sections: list[MenuNode] = []
        for section, titles in MENU.items():
            children = [self._build_child(user, section, title) for title in titles if self._can_view(user, section, title)]
            if children:
                sections.append(MenuNode(title=section, children=children))
        return sections

    def _build_child(self, user: User, section: str, title: str) -> MenuNode:
        route_key = REAL_MODULES.get(title)
        is_placeholder = route_key is None
        return MenuNode(
            title=title,
            route_key=route_key,
            action_key=f"{section}:{title}",
            is_placeholder=is_placeholder,
            disabled_reason=PLACEHOLDER_MESSAGE if is_placeholder else None,
        )

    def _can_view(self, user: User, section: str, title: str) -> bool:
        return (
            Permission.select()
            .join(MenuItem)
            .where(
                Permission.profile == user.profile,
                MenuItem.section == section,
                MenuItem.title == title,
                Permission.action == "ver",
                Permission.allowed == True,  # noqa: E712
            )
            .exists()
        )
