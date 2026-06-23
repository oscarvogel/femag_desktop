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


def build_abm_spec(
    *,
    entity: str,
    title: str,
    permissions_menu: str,
    fields: tuple[str, ...],
    actions: tuple[str, ...] = ("ver", "crear", "modificar"),
) -> ABMViewSpec:
    framework = get_ui_framework()
    return ABMViewSpec(
        library=framework.name,
        entity=entity,
        title=title,
        permissions_menu=permissions_menu,
        fields=fields,
        actions=actions,
    )


def build_client_abm_spec() -> ABMViewSpec:
    return build_abm_spec(
        entity="clientes",
        title="Clientes",
        permissions_menu="Maestros",
        fields=("name", "cuit", "iva_condition", "phone", "email", "contact", "active"),
    )
