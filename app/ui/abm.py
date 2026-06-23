from dataclasses import dataclass

from app.ui.framework import get_ui_framework


@dataclass(frozen=True)
class ABMViewSpec:
    library: str
    entity: str
    title: str
    permissions_menu: str
    fields: tuple[str, ...]
    actions: tuple[str, ...]
    search_placeholder: str
    table_columns: tuple[str, ...]
    empty_message: str
    form_groups: dict[str, tuple[str, ...]]


def build_abm_spec(
    *,
    entity: str,
    title: str,
    permissions_menu: str,
    fields: tuple[str, ...],
    actions: tuple[str, ...] = ("ver", "crear", "modificar"),
    table_columns: tuple[str, ...] | None = None,
    form_groups: dict[str, tuple[str, ...]] | None = None,
) -> ABMViewSpec:
    framework = get_ui_framework()
    return ABMViewSpec(
        library=framework.name,
        entity=entity,
        title=title,
        permissions_menu=permissions_menu,
        fields=fields,
        actions=actions,
        search_placeholder=f"Buscar en {title.lower()}...",
        table_columns=table_columns or fields,
        empty_message=f"No hay registros cargados en {title.lower()}.",
        form_groups=form_groups or {"Datos principales": fields},
    )


def build_client_abm_spec() -> ABMViewSpec:
    return build_abm_spec(
        entity="clientes",
        title="Clientes",
        permissions_menu="Maestros",
        fields=("Nombre", "CUIT", "Condición IVA", "Teléfono", "Email", "Contacto", "Estado"),
        table_columns=("Nombre", "CUIT", "Localidad", "Teléfono", "Estado"),
        form_groups={
            "Datos fiscales": ("Nombre", "CUIT", "Condición IVA", "Estado"),
            "Contacto": ("Teléfono", "Email", "Contacto"),
        },
    )


def build_master_abm_specs() -> tuple[ABMViewSpec, ...]:
    return (
        build_client_abm_spec(),
        build_abm_spec(
            entity="productos",
            title="Productos",
            permissions_menu="Maestros",
            fields=("Producto", "Unidad", "Estado"),
        ),
        build_abm_spec(
            entity="choferes",
            title="Choferes",
            permissions_menu="Maestros",
            fields=("Nombre", "Documento", "Teléfono", "Disponible", "Estado"),
            table_columns=("Nombre", "Teléfono", "Disponible", "Estado"),
        ),
        build_abm_spec(
            entity="transportistas",
            title="Transportistas",
            permissions_menu="Maestros",
            fields=("Nombre", "CUIT", "Teléfono", "Estado"),
        ),
        build_abm_spec(
            entity="camiones",
            title="Camiones",
            permissions_menu="Maestros",
            fields=("Dominio", "Transportista", "Estado"),
        ),
        build_abm_spec(
            entity="tipos_pallets",
            title="Tipos de pallets",
            permissions_menu="Maestros",
            fields=("Tipo", "Medida", "Peso", "Estado"),
        ),
    )
