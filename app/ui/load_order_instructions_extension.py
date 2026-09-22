from __future__ import annotations


def destination_label_with_observation(label: str, observations: str | None) -> str:
    """Append the client/destination observation to the load-order banner."""

    observation = (observations or "").strip()
    if not observation:
        return label
    return f"{label} | Observación: {observation}"


def _budget_observation_for_destination(order, destination) -> str | None:
    """Return the persisted budget observation for this order/client, if any."""

    from app.models.budgets import Budget

    budget = Budget.get_or_none(
        (Budget.load_order == order)
        & (Budget.client == destination.client)
        & (Budget.origin == Budget.ORIGIN_LOAD_ORDER)
    )
    if budget is None:
        return None
    observation = (budget.observations or "").strip()
    return observation or None


def _load_order_destination_observation(order, destination) -> str | None:
    """Use the budget observation when available, preserving legacy fallback."""

    budget_observation = _budget_observation_for_destination(order, destination)
    if budget_observation:
        return budget_observation
    observation = (destination.observations or "").strip()
    return observation or None


def install_load_order_instructions_extension() -> None:
    """Show each client's relevant observation next to it on the printed load order.

    Issue #454 introduced per-destination operational observations in the load-order
    banner. Issue #520 requires the observation that is actually persisted on the
    associated numbered budget to be the source shown there when available.
    Destination observations remain as a fallback for legacy orders/budgets.
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
            _load_order_destination_observation(order, destination),
        )
        return block

    def budget_observations_without_load_instructions(self, order, *, client=None, destination=None):
        # The legacy budget renderer must not leak operational destination notes.
        # Numbered budgets use BudgetPrintService and persist their own observations.
        return []

    service_class._destination_detail_block = destination_detail_block_with_observation
    service_class._budget_observations = budget_observations_without_load_instructions
    service_class._client_observation_on_load_order_installed = True
