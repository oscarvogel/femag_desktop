from pathlib import Path

from app.ui import load_order_workspace_restore_extension as extension


def test_load_order_workspace_uses_split_budget_export():
    source = Path(extension.__file__).read_text(encoding="utf-8")
    assert "export_budgets(order" in source
    assert "export_combined_budget(order)" not in source
    # Con reparto hay dos presupuestos por cliente, asi que el mensaje ya no
    # puede afirmar "uno por cliente" y el boton tiene que dejar elegir la parte.
    assert "uno por cliente" not in source
    assert "_BudgetSendChoiceDialog" in source
