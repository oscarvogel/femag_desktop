from dataclasses import dataclass

from app.models.security import User
from app.services.menu_service import MenuNode, MenuService, PLACEHOLDER_MESSAGE


@dataclass(frozen=True)
class MenuItemView:
    title: str
    placeholder: bool = False
    action_key: str | None = None
    route_key: str | None = None
    disabled_reason: str | None = None
    children: list["MenuItemView"] | None = None


@dataclass(frozen=True)
class MenuSectionView:
    title: str
    items: list[MenuItemView]


@dataclass(frozen=True)
class SidebarTreeSpec:
    sections: list[MenuSectionView]
    active_route: str = "dashboard"
    placeholder_message: str = PLACEHOLDER_MESSAGE
    style_tokens: dict[str, str] | None = None


def build_menu(user: User) -> list[MenuSectionView]:
    return [_to_section(node) for node in MenuService().get_menu_tree_for_user(user)]


def build_sidebar_tree_spec(user: User, *, active_route: str = "dashboard") -> SidebarTreeSpec:
    menu_items = {item.title: item for section in build_menu(user) for item in section.items}

    def approved_item(display_title: str, source_title: str | None = None, route_key: str | None = None) -> MenuItemView:
        source = menu_items.get(source_title or display_title)
        if source is None:
            return MenuItemView(title=display_title, route_key=route_key or "placeholder")
        return MenuItemView(
            title=display_title,
            placeholder=False,
            action_key=source.action_key,
            route_key=route_key or source.route_key or "placeholder",
            disabled_reason=source.disabled_reason,
        )

    return SidebarTreeSpec(
        sections=[
            MenuSectionView(
                title="Principal",
                items=[
                    approved_item("Dashboard"),
                    approved_item("Órdenes de carga"),
                    approved_item("Remitos"),
                    approved_item("F150", "Generar F150"),
                    approved_item("Clientes"),
                    approved_item("Choferes"),
                    approved_item("Transportistas"),
                    approved_item("Camiones"),
                    approved_item("Productos"),
                    approved_item("Cuenta corriente", route_key="placeholder"),
                    approved_item("Reportes", route_key="placeholder"),
                    approved_item("Configuración", "Parámetros", route_key="placeholder"),
                ],
            )
        ],
        active_route=active_route,
        style_tokens={
            "background": "#f8fafc",
            "active": "#1d4ed8",
            "text": "#1f2937",
            "muted": "#6b7280",
        },
    )


def _to_section(node: MenuNode) -> MenuSectionView:
    return MenuSectionView(title=node.title, items=[_to_item(child) for child in node.children])


def _to_item(node: MenuNode) -> MenuItemView:
    return MenuItemView(
        title=node.title,
        placeholder=node.is_placeholder,
        action_key=node.action_key,
        route_key=node.route_key,
        disabled_reason=node.disabled_reason,
        children=[_to_item(child) for child in node.children],
    )
