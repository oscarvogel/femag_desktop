from dataclasses import dataclass

from app.models.security import User
from app.services.permission_service import MENU, PermissionService


@dataclass(frozen=True)
class MenuItemView:
    title: str
    placeholder: bool = False


@dataclass(frozen=True)
class MenuSectionView:
    title: str
    items: list[MenuItemView]


FUTURE_MODULES = {
    "Remitos",
    "Generar F150",
    "Hoja resumen / sobre de carga",
    "Clientes con saldo",
    "Movimientos",
    "Registrar pago",
    "Recibos",
    "Anulación de pagos",
    "Importación",
}


def build_menu(user: User) -> list[MenuSectionView]:
    permission_service = PermissionService()
    sections = []
    for section, titles in MENU.items():
        visible_items = []
        for title in titles:
            if permission_service.has_permission(user, section, "ver", title=title):
                visible_items.append(MenuItemView(title=title, placeholder=title in FUTURE_MODULES))
        sections.append(MenuSectionView(title=section, items=visible_items))
    return sections
