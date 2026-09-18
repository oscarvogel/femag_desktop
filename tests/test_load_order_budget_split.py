from pathlib import Path

from app.ui import load_order_workspace_restore_extension as extension


def test_load_order_workspace_uses_split_budget_export():
    source = Path(extension.__file__).read_text(encoding="utf-8")
    assert "export_budgets(order)" in source
    assert "export_combined_budget(order)" not in source
    assert "presupuesto(s) separados, uno por cliente" in source
