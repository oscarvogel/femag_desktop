from dataclasses import dataclass

from app.models.security import User
from app.services.menu_service import PLACEHOLDER_MESSAGE
from app.ui.dashboard import DashboardService, DashboardViewSpec
from app.ui.menu import MenuItemView, SidebarTreeSpec, build_sidebar_tree_spec


@dataclass(frozen=True)
class ShellStatusBarSpec:
    version: str
    state: str
    last_backup: str


@dataclass(frozen=True)
class MainShellSpec:
    app_name: str
    subtitle: str
    username: str
    profile: str
    connection_state: str
    sidebar: SidebarTreeSpec | None
    dashboard: DashboardViewSpec
    status_bar: ShellStatusBarSpec


class MainWindow:
    def __init__(self, user: User | None = None, *, demo_mode: bool = False):
        self.user = user
        self.demo_mode = demo_mode
        self.sidebar_tree: SidebarTreeSpec | None = build_sidebar_tree_spec(user) if user else None
        self.shell_spec = self._build_shell_spec()

    def show(self):  # pragma: no cover - real UI is exercised manually.
        return None

    def handle_menu_item(self, item: MenuItemView) -> str | None:
        if item.placeholder:
            return PLACEHOLDER_MESSAGE
        return item.route_key

    def _build_shell_spec(self) -> MainShellSpec:
        username = self.user.username if self.user else "demo"
        profile = self.user.profile.name if self.user else "Modo demo"
        dashboard = DashboardService().view_spec(demo_mode=self.demo_mode)
        last_backup = dashboard.summary_cards.get("Último backup", "Sin registros")
        return MainShellSpec(
            app_name="FEMAG Desktop",
            subtitle="Gestión operativa local",
            username=username,
            profile=profile,
            connection_state="Modo demo" if self.demo_mode else "Base local conectada",
            sidebar=self.sidebar_tree,
            dashboard=dashboard,
            status_bar=ShellStatusBarSpec(version="v0.1", state="Listo", last_backup=str(last_backup)),
        )
