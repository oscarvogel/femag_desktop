from __future__ import annotations


def destination_label_with_observation(label: str, observations: str | None) -> str:
    """Append the client/destination observation to the load-order destination banner."""

    observation = (observations or "").strip()
    if not observation:
        return label
    return f"{label} | Observación: {observation}"


def install_load_order_instructions_extension() -> None:
    """Make each client/destination observation visible on the printed load order.

    `LoadOrderDestination.observations` is already the text captured for a specific
    client/destination and is already reused by that client's budget.  Issue #454
    requires the same text to also be visible in the load order, next to the client
    it belongs to.  No persistence or budget behavior is changed here.
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

    service_class._destination_detail_block = destination_detail_block_with_observation
    service_class._client_observation_on_load_order_installed = True
