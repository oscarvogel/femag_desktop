from dataclasses import dataclass

from app.ui.abm import ABMViewSpec, build_abm_spec


@dataclass(frozen=True)
class LoadOrderSectionSpec:
    title: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class LoadOrderFormSpec:
    title: str
    sections: tuple[LoadOrderSectionSpec, ...]
    detail_columns: tuple[str, ...]
    detail_actions: tuple[str, ...]
    primary_actions: tuple[str, ...]
    driver_status_messages: dict[str, str]


def build_load_order_view_spec() -> ABMViewSpec:
    return build_abm_spec(
        entity="ordenes_carga",
        title="Órdenes de carga",
        permissions_menu="Operaciones",
        fields=(
            "Número",
            "Fecha",
            "Cliente cabecera / VARIOS",
            "Destino general",
            "Estado",
            "Transportista",
            "Camión",
            "Chofer",
            "Vehículo limpio y apto",
            "Detalle de despacho",
        ),
        table_columns=("Número", "Fecha", "Cliente", "Destino", "Chofer", "Estado"),
        actions=("ver", "crear", "modificar", "imprimir", "reimprimir", "anular", "cerrar"),
    )


def build_load_order_form_spec() -> LoadOrderFormSpec:
    return LoadOrderFormSpec(
        title="Nueva orden de carga",
        sections=(
            LoadOrderSectionSpec(
                "Datos de la carga",
                ("Número", "Fecha", "Cliente cabecera / VARIOS", "Destino general", "Estado"),
            ),
            LoadOrderSectionSpec(
                "Transporte",
                ("Transportista", "Camión", "Chofer", "Vehículo limpio y apto"),
            ),
        ),
        detail_columns=(
            "Cliente / destinatario",
            "Localidad / destino",
            "Producto / detalle",
            "Bolsas x 25 kg",
            "Bolsas x 10 kg",
            "Pack",
            "Pallet",
            "Lote",
            "Fecha elaboración",
            "Observaciones",
        ),
        detail_actions=("Agregar renglón", "Duplicar renglón", "Quitar renglón"),
        primary_actions=("Guardar", "Guardar e imprimir", "Cerrar orden", "Anular", "Reimprimir"),
        driver_status_messages={
            "available": "Chofer disponible para nueva carga.",
            "blocked": "El chofer seleccionado ya tiene una carga activa.",
        },
    )
