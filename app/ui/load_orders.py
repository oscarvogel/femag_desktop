from app.ui.abm import ABMViewSpec, build_abm_spec


def build_load_order_view_spec() -> ABMViewSpec:
    return build_abm_spec(
        entity="ordenes_carga",
        title="Órdenes de carga",
        permissions_menu="Operaciones",
        fields=(
            "order_number",
            "date",
            "header_client",
            "header_client_text",
            "destination",
            "carrier",
            "driver",
            "truck",
            "vehicle_clean_and_suitable",
            "status",
            "observations",
            "lines",
        ),
        actions=("ver", "crear", "modificar", "imprimir", "reimprimir", "anular", "cerrar"),
    )
