import unicodedata
from dataclasses import dataclass, replace

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

    operations_children = [
        item
        for item in (
            approved_item("Órdenes de carga"),
            approved_item("Remitos"),
            approved_item("F150", "Generar F150"),
        )
        if item.route_key != "placeholder" or item.action_key is not None
    ]

    informes_children = [
        item
        for item in (
            approved_item("Informe operativo diario", "Pendientes", route_key="daily_operations"),
            approved_item("Órdenes pendientes", "Pendientes", route_key="pending_orders_aging"),
            approved_item("Trazabilidad por lote", "Pendientes", route_key="lot_traceability"),
            approved_item("Devoluciones y reclamos", "Pendientes", route_key="returns_report"),
            approved_item("Vencimientos de cobranzas", "Pendientes", route_key="collection_due_report"),
            approved_item("Ventas por producto", "Pendientes", route_key="operational_product_sales"),
        )
        if item.route_key != "placeholder" or item.action_key is not None
    ]

    master_children = [
        item
        for item in (
            approved_item("Clientes"),
            approved_item("Vendedores"),
            approved_item("Productos"),
            approved_item("Precios por lista", "Productos", route_key="product_price_bulk"),
            approved_item("Tipos de IVA"),
            approved_item("Transportistas"),
            approved_item("Choferes"),
            approved_item("Camiones"),
        )
        if item.route_key != "placeholder" or item.action_key is not None
    ]

    production_children = [
        item
        for item in (
            approved_item("Recepciones de materia prima"),
            approved_item("Partes de producción"),
            approved_item("Contraste de producción"),
            approved_item("Inventario inicial"),
            approved_item("Conteo físico"),
        )
        if item.route_key != "placeholder" or item.action_key is not None
    ]

    principal_items = [approved_item("Dashboard")]

    managerial_dashboard = approved_item("Dashboard Gerencial")
    if managerial_dashboard.action_key is not None:
        principal_items.append(
            MenuItemView(
                title="Dashboard Gerencial",
                children=[
                    MenuItemView(
                        title="Resumen gerencial",
                        placeholder=False,
                        action_key=managerial_dashboard.action_key,
                        route_key="managerial_dashboard",
                    ),
                    MenuItemView(
                        title="Ventas y despachos",
                        placeholder=False,
                        action_key=managerial_dashboard.action_key,
                        route_key="managerial_sales_dispatch",
                    ),
                    MenuItemView(
                        title="Cuenta corriente y deuda vencida",
                        placeholder=False,
                        action_key=managerial_dashboard.action_key,
                        route_key="managerial_account_risk",
                    ),
                    MenuItemView(
                        title="Cobranzas y movimientos",
                        placeholder=False,
                        action_key=managerial_dashboard.action_key,
                        route_key="daily_collections",
                    ),
                    MenuItemView(
                        title="Clientes",
                        placeholder=False,
                        action_key=managerial_dashboard.action_key,
                        route_key="managerial_clients",
                    ),
                    *(
                        [
                            MenuItemView(
                                title="Rentabilidad por producto",
                                placeholder=False,
                                action_key=menu_items["Rentabilidad por producto"].action_key,
                                route_key="product_profitability",
                            )
                        ]
                        if "Rentabilidad por producto" in menu_items
                        else []
                    ),
                ],
            )
        )

    if production_children:
        principal_items.append(MenuItemView(title="Producción", children=production_children))
    if operations_children:
        principal_items.append(MenuItemView(title="Operaciones", children=operations_children))
    if informes_children:
        principal_items.append(MenuItemView(title="Informes", children=informes_children))
    if master_children:
        principal_items.append(MenuItemView(title="Maestros", children=master_children))

    principal_items.append(approved_item("Cuenta corriente", route_key="customer_ledger"))

    system_children = [
        item
        for item in (
            approved_item("Configuración", "Parámetros", route_key="remittance_series"),
            approved_item("WhatsApp", "Parámetros", route_key="whatsapp_configuration"),
            approved_item("Importación DBF", "Importación", route_key="legacy_dbf_import"),
            approved_item("Usuarios", route_key="user_management"),
            approved_item("Perfiles y permisos", "Permisos por menú", route_key="user_management"),
            approved_item("Auditoría", route_key="audit_query"),
        )
        if item.action_key is not None
    ]
    if system_children:
        principal_items.append(MenuItemView(title="Sistema", children=system_children))

    principal_items.append(approved_item("Avisos", route_key="avisos"))

    return SidebarTreeSpec(
        sections=[
            MenuSectionView(
                title="Principal",
                items=principal_items,
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


# -- Buscador del menu lateral --------------------------------------------
#
# Por que la coincidencia no distingue tildes ni mayusculas
# ------------------------------------------------------
# El menu esta lleno de palabras acentuadas ("Configuración", "Producción",
# "Auditoría") y el operador las teclea como las escribe de memoria. Sin
# normalizar, buscar "configuracion" no encuentra "Configuración" y el operador
# concluye que la pantalla no existe. Es el mismo criterio que usan las demas
# busquedas del proyecto (``master_abm.normalize_master_text``,
# ``permission_service``), asi que el menu no puede ser el unico que exija
# acentos.
#
# Por que NO se busca tambien por ``route_key``
# -------------------------------------------
# PyFE matchea contra la clave tecnica de cada boton. Aca eso dejaria pasar
# cosas que el operador nunca escribio: "product_profitability" apareceria como
# resultado de "profit". Se matchea solo por titulo, que es lo que se ve.


def normalizar_texto_menu(texto: object) -> str:
    """Minusculas y sin tildes: 'Configuración' -> 'configuracion'.

    A diferencia de ``normalize_master_text`` (que saca los espacios y todo lo
    que no es alfanumerico porque ordena columnas), aca se conservan los espacios
    y la puntuacion: la busqueda es por *contiene*, y "cuenta corriente" tiene
    que seguir siendo una frase buscable.
    """
    descompuesto = unicodedata.normalize("NFD", str(texto or "").casefold())
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).strip()


def _coincide(consulta: str, titulo: str) -> bool:
    return consulta in normalizar_texto_menu(titulo)


def _contar_acciones(sections: list[MenuSectionView]) -> int:
    """Cuantas acciones hay en total, sin contar dos veces los titulos de grupo.

    Un grupo no es una accion: es la carpeta que la contiene. Contarlo como
    resultado haria que el menu nunca se viera vacio.
    """
    total = 0
    for section in sections:
        for item in section.items:
            total += len(item.children) if item.children else 1
    return total


@dataclass(frozen=True)
class SidebarSearchResult:
    """Lo que el menu muestra para una consulta, y cuantas acciones quedaron."""

    sections: list[MenuSectionView]
    matches: int
    query: str

    @property
    def empty(self) -> bool:
        """Si hay que avisar que no se encontro nada.

        Con el menu entero no hay nada que avisar aunque `matches` valga cero
        (que no puede, pero el contrato no depende de eso): el aviso es de "no
        coincide con lo que escribiste", y sin escribir no hay consulta.
        """
        return bool(self.query) and self.matches == 0


def filtrar_sidebar(sections: list[MenuSectionView], consulta: str) -> SidebarSearchResult:
    """Deja solo las acciones que coinciden con ``consulta``.

    Reglas, que son las de PyFE adaptadas a los grupos de FEMAG:

    - **Sin consulta** devuelve el menu tal como estaba. El buscador no toca el
      estado del acordeon: si no se escribe nada, no cambio nada.
    - **Una accion suelta** se muestra si su titulo coincide.
    - **El titulo de un grupo** muestra el grupo entero, no solo los hijos que
      coinciden. Buscar "maestros" tiene que mostrar todos los maestros.
    - **El titulo de un hijo** muestra el grupo con ese hijo, y solo ese. Un
      grupo desplegado por un unico resultado es ruido: si el operador escribio
      "f150", quiere ver F150, no las ocho pantallas de Operaciones.

    El filtro no consulta la base ni revisa permisos: opera sobre el spec que ya
    se construyo para ese usuario, asi que no puede revelar nada que el menu no
    mostrara antes.
    """
    consulta = normalizar_texto_menu(consulta)

    if not consulta:
        return SidebarSearchResult(
            sections=list(sections),
            matches=_contar_acciones(sections),
            query=consulta,
        )

    secciones_filtradas: list[MenuSectionView] = []
    matches = 0

    for section in sections:
        items_filtrados: list[MenuItemView] = []

        for item in section.items:
            if not item.children:
                if _coincide(consulta, item.title):
                    items_filtrados.append(item)
                    matches += 1
                continue

            grupo_coincide = _coincide(consulta, item.title)
            hijos = [
                hijo for hijo in item.children
                if grupo_coincide or _coincide(consulta, hijo.title)
            ]
            if not grupo_coincide and not hijos:
                continue

            items_filtrados.append(replace(item, children=hijos))
            matches += len(hijos)

        # Una seccion sin items no se agrega: si no, el sidebar dibujaria un
        # grupo vacio y el operador veria que "algo" coincide sin poder llegar.
        if items_filtrados:
            secciones_filtradas.append(
                MenuSectionView(title=section.title, items=items_filtrados)
            )

    return SidebarSearchResult(sections=secciones_filtradas, matches=matches, query=consulta)
