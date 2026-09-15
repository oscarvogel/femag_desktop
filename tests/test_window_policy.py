from app.ui.window_policy import _is_workspace_dialog_title


def test_pallet_detail_dialog_is_workspace_and_opens_maximized():
    assert _is_workspace_dialog_title("Detalle de pallets") is True
