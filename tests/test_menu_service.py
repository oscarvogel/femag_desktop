def flatten(nodes):
    return [child for node in nodes for child in [node, *flatten(node.children)]]


def titles(nodes):
    return [node.title for node in nodes]


def find_node(nodes, title):
    for node in flatten(nodes):
        if node.title == title:
            return node
    raise AssertionError(f"No se encontro el menu {title!r}")


def test_menu_service_builds_parent_child_tree(db):
    from app.models.security import MenuItem
    from app.services.menu_service import MenuService

    operations = MenuItem.create(title="Operaciones", module="operaciones", sort_order=10)
    MenuItem.create(parent=operations, title="Remitos", action_key="operaciones.remitos", sort_order=20)
    MenuItem.create(parent=operations, title="Ordenes", action_key="operaciones.ordenes", sort_order=10)

    tree = MenuService().get_full_tree()

    assert titles(tree) == ["Operaciones"]
    assert titles(tree[0].children) == ["Ordenes", "Remitos"]
    assert tree[0].children[0].parent_id == operations.id


def test_menu_service_excludes_inactive_items_and_orders_by_sort_order(db):
    from app.models.security import MenuItem
    from app.services.menu_service import MenuService

    MenuItem.create(title="Zeta", sort_order=30)
    MenuItem.create(title="Alfa", sort_order=10)
    MenuItem.create(title="Oculto", sort_order=1, is_active=False)

    tree = MenuService().get_active_tree()

    assert titles(tree) == ["Alfa", "Zeta"]


def test_admin_menu_includes_every_active_seeded_option(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.services.menu_service import MenuService

    PermissionService().seed_defaults()
    admin = AuthService().create_user("admin", "secreto", "Administrador")

    tree = MenuService().get_menu_tree_for_user(admin)

    assert find_node(tree, "Sistema").children
    assert find_node(tree, "Backups").requires_permission is True
    assert find_node(tree, "Generar F150").is_placeholder is True


def test_secretaria_menu_shows_operations_and_masters_but_not_system(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.services.menu_service import MenuService

    PermissionService().seed_defaults()
    user = AuthService().create_user("secretaria", "clave", "Secretaria")

    tree = MenuService().get_menu_tree_for_user(user)

    assert find_node(tree, "Operaciones").children
    assert find_node(tree, "Maestros").children
    assert "Sistema" not in titles(tree)


def test_menu_service_hides_items_without_permission(db):
    from app.models.security import Permission
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.services.menu_service import MenuService

    PermissionService().seed_defaults()
    user = AuthService().create_user("secretaria_sin_remitos", "clave", "Secretaria")
    remitos = find_node(MenuService().get_full_tree(), "Remitos")
    Permission.update(allowed=False).where(
        Permission.profile == user.profile,
        Permission.menu_item_id == remitos.id,
        Permission.action == "ver",
    ).execute()

    tree = MenuService().get_menu_tree_for_user(user)

    assert "Remitos" not in [node.title for node in flatten(tree)]
    assert "Órdenes de carga" in [node.title for node in flatten(tree)]


def test_placeholders_are_visible_only_when_user_has_permission(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.services.menu_service import MenuService

    PermissionService().seed_defaults()
    secretary = AuthService().create_user("secretaria", "clave", "Secretaria")
    viewer = AuthService().create_user("consulta", "clave", "Solo consulta")

    secretary_tree = MenuService().get_menu_tree_for_user(secretary)
    viewer_tree = MenuService().get_menu_tree_for_user(viewer)

    assert find_node(secretary_tree, "Remitos").is_placeholder is True
    assert "Remitos" not in [node.title for node in flatten(viewer_tree)]


def test_ui_menu_uses_menu_service_instead_of_static_menu_constant(db):
    import inspect

    from app.ui import menu

    source = inspect.getsource(menu.build_menu)

    assert "MenuService" in source
    assert "MENU" not in source
