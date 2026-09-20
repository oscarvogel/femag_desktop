from __future__ import annotations


def destination_label_with_observation(label: str, observations: str | None) -> str:
    """Append the client/destination load observation to the load-order banner."""

    observation = (observations or "").strip()
    if not observation:
        return label
    return f"{label} | Observación: {observation}"


def install_load_order_instructions_extension() -> None:
    """Show per-client load observations only on the printed load order.

    `LoadOrderDestination.observations` is an operational loading instruction for a
    specific client/destination. Issue #454 requires it to be visible next to that
    client in the load order, while it must not be exposed in the client budget.
    No persistence changes are required.
    """

    from app.services import load_order_print_service

    service_class = load_order_print_service.LoadOrderPrintService
    if getattr(service_class, "_client_observation_on_load_order_installed", False):
        return

    base_destination_detail_block = service_class._destination_detail_block

    def destination_detail_block_with_observation(self, order, destination):
        block = base_destination_detail_block(self, order, destination)
        block["destination"] = destination_label_with_observation(
            str(block.get("destination") or ""),
            destination.observations,
        )
        return block

    def budget_observations_without_load_instructions(self, order, *, client=None, destination=None):
        # Destination observations are operational loading instructions and are
        # intentionally omitted from customer-facing budgets.
        return []

    service_class._destination_detail_block = destination_detail_block_with_observation
    service_class._budget_observations = budget_observations_without_load_instructions
    service_class._client_observation_on_load_order_installed = True
