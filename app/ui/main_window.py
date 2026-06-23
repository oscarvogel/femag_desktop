from app.services.menu_service import PLACEHOLDER_MESSAGE
from app.ui.menu import MenuItemView, SidebarTreeSpec, build_sidebar_tree_spec


class MainWindow:
    def __init__(self, user=None):
        self.user = user
        self.sidebar_tree: SidebarTreeSpec | None = build_sidebar_tree_spec(user) if user else None

    def show(self):  # pragma: no cover - real UI is exercised manually.
        return None

    def handle_menu_item(self, item: MenuItemView) -> str | None:
        if item.placeholder:
            return PLACEHOLDER_MESSAGE
        return item.route_key
