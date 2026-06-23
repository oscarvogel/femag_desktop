from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.models.security import MenuItem, User


PLACEHOLDER_MESSAGE = "Funcionalidad prevista para una próxima entrega."


DEFAULT_MENU_TREE = [
    {
        "title": "Inicio",
        "module": "inicio",
        "sort_order": 10,
        "requires_permission": False,
        "children": [
            {"title": "Dashboard", "action_key": "inicio.dashboard", "route_key": "dashboard", "sort_order": 10},
            {"title": "Pendientes", "action_key": "inicio.pendientes", "sort_order": 20, "is_placeholder": True},
        ],
    },
    {
        "title": "Operaciones",
        "module": "operaciones",
        "sort_order": 20,
        "requires_permission": False,
        "children": [
            {
                "title": "Órdenes de carga",
                "action_key": "operaciones.ordenes_carga",
                "route_key": "load_orders",
                "sort_order": 10,
            },
            {"title": "Remitos", "action_key": "operaciones.remitos", "sort_order": 20, "is_placeholder": True},
            {"title": "Generar F150", "action_key": "operaciones.f150", "sort_order": 30, "is_placeholder": True},
            {
                "title": "Hoja resumen / sobre de carga",
                "action_key": "operaciones.hoja_resumen",
                "sort_order": 40,
                "is_placeholder": True,
            },
        ],
    },
    {
        "title": "Cuenta corriente",
        "module": "cuenta_corriente",
        "sort_order": 30,
        "requires_permission": False,
        "children": [
            {
                "title": "Clientes con saldo",
                "action_key": "cuenta_corriente.clientes_saldo",
                "sort_order": 10,
                "is_placeholder": True,
            },
            {
                "title": "Registrar pago",
                "action_key": "cuenta_corriente.registrar_pago",
                "sort_order": 20,
                "is_placeholder": True,
            },
            {"title": "Recibos", "action_key": "cuenta_corriente.recibos", "sort_order": 30, "is_placeholder": True},
        ],
    },
    {
        "title": "Maestros",
        "module": "maestros",
        "sort_order": 40,
        "requires_permission": False,
        "children": [
            {"title": "Clientes", "action_key": "maestros.clientes", "route_key": "clients", "sort_order": 10},
            {
                "title": "Domicilios",
                "action_key": "maestros.domicilios",
                "route_key": "client_addresses",
                "sort_order": 20,
            },
            {"title": "Productos", "action_key": "maestros.productos", "route_key": "products", "sort_order": 30},
            {"title": "Choferes", "action_key": "maestros.choferes", "route_key": "drivers", "sort_order": 40},
            {
                "title": "Transportistas",
                "action_key": "maestros.transportistas",
                "route_key": "carriers",
                "sort_order": 50,
            },
            {"title": "Camiones", "action_key": "maestros.camiones", "route_key": "trucks", "sort_order": 60},
            {
                "title": "Tipos de pallets",
                "action_key": "maestros.tipos_pallets",
                "route_key": "pallet_types",
                "sort_order": 70,
            },
        ],
    },
    {
        "title": "Sistema",
        "module": "sistema",
        "sort_order": 50,
        "requires_permission": False,
        "children": [
            {"title": "Usuarios", "action_key": "sistema.usuarios", "sort_order": 10},
            {"title": "Perfiles", "action_key": "sistema.perfiles", "sort_order": 20},
            {"title": "Permisos", "action_key": "sistema.permisos", "sort_order": 30},
            {"title": "Backups", "action_key": "sistema.backups", "route_key": "backups", "sort_order": 40},
            {"title": "Auditoria", "action_key": "sistema.auditoria", "route_key": "audit", "sort_order": 50},
        ],
    },
]


@dataclass(frozen=True)
class MenuNode:
    id: int
    parent_id: int | None
    title: str
    icon: str | None
    action_key: str | None
    route_key: str | None
    module: str | None
    sort_order: int
    is_active: bool
    is_placeholder: bool
    requires_permission: bool
    children: list["MenuNode"]


class MenuService:
    def seed_default_menu(self) -> None:
        for root_spec in DEFAULT_MENU_TREE:
            self._upsert_item(root_spec, parent=None, section=root_spec["title"])

    def get_full_tree(self, active_only: bool = False) -> list[MenuNode]:
        query = MenuItem.select()
        if active_only:
            query = query.where(MenuItem.is_active == True)  # noqa: E712
        items = list(query.order_by(MenuItem.sort_order, MenuItem.title))
        return self._build_nodes(items, parent_id=None)

    def get_active_tree(self) -> list[MenuNode]:
        return self.get_full_tree(active_only=True)

    def get_menu_tree_for_user(self, user: User) -> list[MenuNode]:
        from app.services.permission_service import PermissionService

        permission_service = PermissionService()
        return self._filter_nodes(self.get_active_tree(), user, permission_service)

    def _upsert_item(self, spec: dict, parent: MenuItem | None, section: str) -> MenuItem:
        lookup = {"action_key": spec["action_key"]} if spec.get("action_key") else {"parent": parent, "title": spec["title"]}
        item, _ = MenuItem.get_or_create(**lookup, defaults={"title": spec["title"], "parent": parent})
        item.parent = parent
        item.section = section
        item.title = spec["title"]
        item.icon = spec.get("icon")
        item.route_key = spec.get("route_key")
        item.module = spec.get("module") or (parent.module if parent else None)
        item.sort_order = spec.get("sort_order", 0)
        item.is_active = spec.get("is_active", True)
        item.is_placeholder = spec.get("is_placeholder", False)
        item.requires_permission = spec.get("requires_permission", True)
        item.save()
        for child_spec in spec.get("children", []):
            self._upsert_item(child_spec, parent=item, section=section)
        return item

    def _build_nodes(self, items: Iterable[MenuItem], parent_id: int | None) -> list[MenuNode]:
        children = [item for item in items if item.parent_id == parent_id]
        return [self._to_node(item, self._build_nodes(items, item.id)) for item in children]

    def _to_node(self, item: MenuItem, children: list[MenuNode]) -> MenuNode:
        return MenuNode(
            id=item.id,
            parent_id=item.parent_id,
            title=item.title,
            icon=item.icon,
            action_key=item.action_key,
            route_key=item.route_key,
            module=item.module,
            sort_order=item.sort_order,
            is_active=item.is_active,
            is_placeholder=item.is_placeholder,
            requires_permission=item.requires_permission,
            children=children,
        )

    def _filter_nodes(self, nodes: list[MenuNode], user: User, permission_service) -> list[MenuNode]:
        visible = []
        for node in nodes:
            children = self._filter_nodes(node.children, user, permission_service)
            can_show_node = not node.requires_permission or permission_service.has_menu_permission(user, node.id)
            if children or (can_show_node and not node.children):
                visible.append(MenuNode(**{**node.__dict__, "children": children}))
        return visible
