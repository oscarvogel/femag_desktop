from dataclasses import dataclass

from app.models.security import User
from app.services.menu_service import MenuNode, MenuService, PLACEHOLDER_MESSAGE


@dataclass(frozen=True)
class MenuItemView:
    title: str
    placeholder: bool = False
    action_key: str | None = None
    route_key: str | None = None
    children: list["MenuItemView"] | None = None


@dataclass(frozen=True)
class MenuSectionView:
    title: str
    items: list[MenuItemView]


@dataclass(frozen=True)
class SidebarTreeSpec:
    sections: list[MenuSectionView]
    placeholder_message: str = PLACEHOLDER_MESSAGE


def build_menu(user: User) -> list[MenuSectionView]:
    tree = MenuService().get_menu_tree_for_user(user)
    return [_to_section(node) for node in tree]


def build_sidebar_tree_spec(user: User) -> SidebarTreeSpec:
    return SidebarTreeSpec(sections=build_menu(user))


def _to_section(node: MenuNode) -> MenuSectionView:
    return MenuSectionView(title=node.title, items=[_to_item(child) for child in node.children])


def _to_item(node: MenuNode) -> MenuItemView:
    return MenuItemView(
        title=node.title,
        placeholder=node.is_placeholder,
        action_key=node.action_key,
        route_key=node.route_key,
        children=[_to_item(child) for child in node.children],
    )
