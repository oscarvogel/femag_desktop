"""Edicion auditada de lote/fechas desde Escritorio (#864, PR 2)."""

import os
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest

from conftest import _master_data, _valid_order_payload

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.models.audit import AuditLog
from app.models.load_orders import (
    LoadOrder,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.sync import SyncEntityMap
from app.services.load_order_traceability_service import (
    LoadOrderTraceabilityError,
    LoadOrderTraceabilityService,
)


def _order_with_contents(*, status=LoadOrder.STATUS_PENDING):
    data = _master_data()
    data["product"].peso_unitario_kg = Decimal("25.000")
    data["product"].save()
    service = LoadOrderTraceabilityService(current_user="secretaria")
    order = service_create_order(data, status=status)
    destination = order.destinations.get()
    line = LoadOrderProduct.get(LoadOrderProduct.order == order)
    pallet = LoadOrderPallet.create(order=order, sequence=1)
    allocation = LoadOrderPalletAllocation.create(
        pallet=pallet,
        destination=destination,
        product=data["product"],
        quantity=40,
        peso_unitario_kg=Decimal("25.000"),
        lote="LOTE-VIEJO",
        fecha_elaboracion=date(2026, 10, 19),
        fecha_envasado=date(2026, 10, 18),
    )
    loose = LoadOrderLooseAllocation.create(
        order=order,
        destination=destination,
        product=data["product"],
        quantity=10,
        peso_unitario_kg=Decimal("25.000"),
        lote="SUELTO-VIEJO",
        fecha_elaboracion=date(2026, 10, 17),
        fecha_envasado=date(2026, 10, 16),
    )
    return order, line, allocation, loose


def service_create_order(data, *, status=LoadOrder.STATUS_PENDING):
    from app.services.load_order_service import LoadOrderService

    order = LoadOrderService(current_user="secretaria").create_order(
        **_valid_order_payload(data)
    )
    if status != order.status:
        order.status = status
        order.save()
    return order


@contextmanager
def _runtime_load_order_page():
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.load_order_workspace_restore_extension import (
        install_load_order_workspace_restore_extension,
    )

    original = FemagDesktopWindow._load_order_page
    install_load_order_workspace_restore_extension()
    try:
        yield
    finally:
        FemagDesktopWindow._load_order_page = original


def _items(allocation, loose):
    return [
        {
            "kind": "pallet_content",
            "id": allocation.id,
            "lote": "LOTE-NUEVO",
            "fecha_elaboracion": date(2026, 10, 20),
            "fecha_envasado": date(2026, 10, 21),
        },
        {
            "kind": "loose_content",
            "id": loose.id,
            "lote": "SUELTO-NUEVO",
            "fecha_elaboracion": date(2026, 10, 22),
            "fecha_envasado": date(2026, 10, 23),
        },
    ]


def test_update_contents_is_audited_and_bumps_sync_version(db):
    order, _line, allocation, loose = _order_with_contents()

    changed = LoadOrderTraceabilityService("secretaria").update_lote_fecha(
        order, _items(allocation, loose)
    )

    assert changed == 2
    allocation = LoadOrderPalletAllocation.get_by_id(allocation.id)
    loose = LoadOrderLooseAllocation.get_by_id(loose.id)
    assert (
        allocation.lote,
        allocation.fecha_elaboracion,
        allocation.fecha_envasado,
    ) == ("LOTE-NUEVO", date(2026, 10, 20), date(2026, 10, 21))
    assert (
        loose.lote,
        loose.fecha_elaboracion,
        loose.fecha_envasado,
    ) == ("SUELTO-NUEVO", date(2026, 10, 22), date(2026, 10, 23))

    audits = list(
        AuditLog.select()
        .where(AuditLog.action == "editar lote/fecha")
        .order_by(AuditLog.id)
    )
    assert len(audits) == 2
    assert audits[0].old_value["lote"] == "LOTE-VIEJO"
    assert audits[0].new_value["lote"] == "LOTE-NUEVO"
    assert audits[0].user == "secretaria"

    entity = SyncEntityMap.get(
        (SyncEntityMap.entity_type == SyncEntityMap.ENTITY_ORDER)
        & (SyncEntityMap.local_id == str(order.id))
    )
    assert entity.local_version == 2


def test_legacy_line_can_be_edited_without_composition(db):
    data = _master_data()
    service = LoadOrderTraceabilityService("secretaria")
    order = service_create_order(data)
    line = LoadOrderProduct.get(LoadOrderProduct.order == order)

    changed = service.update_lote_fecha(
        order,
        [
            {
                "kind": "line",
                "id": line.id,
                "lote": "LEGACY-NUEVO",
                "fecha_elaboracion": "2026-10-24",
                "fecha_envasado": None,
            }
        ],
    )

    assert changed == 1
    line = LoadOrderProduct.get_by_id(line.id)
    assert line.lote == "LEGACY-NUEVO"
    assert line.fecha_elaboracion == date(2026, 10, 24)
    assert line.fecha_envasado is None


def test_closed_order_requires_reason(db):
    order, _line, allocation, loose = _order_with_contents(
        status=LoadOrder.STATUS_CLOSED
    )
    service = LoadOrderTraceabilityService("secretaria")

    with pytest.raises(LoadOrderTraceabilityError, match="motivo"):
        service.update_lote_fecha(order, _items(allocation, loose))

    changed = service.update_lote_fecha(
        order, _items(allocation, loose), reason="Correccion de lote mal escaneado"
    )

    assert changed == 2
    audit = AuditLog.get(AuditLog.action == "editar lote/fecha")
    assert audit.observation == "Correccion de lote mal escaneado"


def test_annulled_order_is_rejected(db):
    order, _line, allocation, loose = _order_with_contents(
        status=LoadOrder.STATUS_ANNULLED
    )

    with pytest.raises(LoadOrderTraceabilityError, match="anulada"):
        LoadOrderTraceabilityService("secretaria").update_lote_fecha(
            order, _items(allocation, loose)
        )


def test_invalid_items_are_rejected(db):
    order, _line, allocation, loose = _order_with_contents()
    service = LoadOrderTraceabilityService("secretaria")

    with pytest.raises(LoadOrderTraceabilityError, match="255"):
        service.update_lote_fecha(
            order,
            [{"kind": "pallet_content", "id": allocation.id, "lote": "x" * 256}],
        )
    with pytest.raises(LoadOrderTraceabilityError, match="fecha"):
        service.update_lote_fecha(
            order,
            [
                {
                    "kind": "loose_content",
                    "id": loose.id,
                    "fecha_elaboracion": "no-es-fecha",
                }
            ],
        )
    with pytest.raises(LoadOrderTraceabilityError, match="no pertenece"):
        service.update_lote_fecha(
            order,
            [{"kind": "pallet_content", "id": 999999, "lote": "X"}],
        )


def test_permission_cargar_lote_is_only_for_admin_and_secretary(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService

    permissions = PermissionService()
    permissions.seed_defaults()
    auth = AuthService()
    admin = auth.create_user("admin_lote", "clave", "Administrador")
    secretary = auth.create_user("secre_lote", "clave", "Secretaria")
    administration = auth.create_user("admon_lote", "clave", "Administracion")
    viewer = auth.create_user("consulta_lote", "clave", "Solo consulta")

    for user in (admin, secretary):
        assert permissions.has_permission(
            user, "Operaciones", "cargar lote", "Órdenes de carga"
        )
    for user in (administration, viewer):
        assert not permissions.has_permission(
            user, "Operaciones", "cargar lote", "Órdenes de carga"
        )


def test_dialog_lists_contents_and_saves_changes(db):
    from PyQt5.QtWidgets import QApplication, QLineEdit

    from app.ui.load_order_traceability_dialog import LoadOrderTraceabilityDialog

    app = QApplication.instance() or QApplication([])
    order, _line, allocation, loose = _order_with_contents()
    dialog = LoadOrderTraceabilityDialog(
        LoadOrderTraceabilityService("secretaria"), order
    )
    app.processEvents()

    assert dialog.table.rowCount() == 2
    assert dialog.table.item(0, 0).text() == "Pallet 1"
    assert dialog.table.item(1, 0).text() == "Suelto"

    dialog.findChild(QLineEdit, "loadOrderTraceabilityLote_0").setText("LOTE-UI")
    dialog._save()

    assert dialog.updated_count == 1
    assert LoadOrderPalletAllocation.get_by_id(allocation.id).lote == "LOTE-UI"
    assert LoadOrderLooseAllocation.get_by_id(loose.id).lote == "SUELTO-VIEJO"


def test_closed_dialog_requires_reason_before_saving(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.load_order_traceability_dialog import LoadOrderTraceabilityDialog

    app = QApplication.instance() or QApplication([])
    order, _line, _allocation, _loose = _order_with_contents(
        status=LoadOrder.STATUS_CLOSED
    )
    dialog = LoadOrderTraceabilityDialog(
        LoadOrderTraceabilityService("secretaria"), order
    )
    app.processEvents()

    assert dialog.reason_input is not None
    dialog._save()
    assert dialog.result() == 0
    assert "motivo" in dialog.validation_label.text().lower()

    dialog.reason_input.setPlainText("Correccion autorizada")
    dialog._save()
    assert dialog.result() == 1


def test_toolbar_button_follows_permission_and_annulled_state(db):
    from PyQt5.QtWidgets import QApplication, QPushButton, QTableWidget

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Secretaría")
    user = User.create(username="secre_toolbar", password_hash="x", profile=profile)
    order, _line, _allocation, _loose = _order_with_contents()

    with _runtime_load_order_page():
        window = FemagDesktopWindow(user=user, demo_mode=True)
        window.show()
        app.processEvents()
        window.findChild(QTableWidget, "loadOrdersTable").setCurrentCell(0, 0)
        app.processEvents()

        button = window.findChild(QPushButton, "editLoadOrderTraceabilityButton")
        assert button.isHidden() is False
        assert button.isEnabled()
        window.close()

        order.status = LoadOrder.STATUS_ANNULLED
        order.save()
        annulled_window = FemagDesktopWindow(user=user, demo_mode=True)
        annulled_window.show()
        app.processEvents()
        annulled_window.findChild(QTableWidget, "loadOrdersTable").setCurrentCell(0, 0)
        app.processEvents()

        annulled_button = annulled_window.findChild(
            QPushButton, "editLoadOrderTraceabilityButton"
        )
        assert annulled_button.isHidden() is False
        assert annulled_button.isEnabled() is False
        annulled_window.close()


def test_toolbar_hides_traceability_without_permission(db):
    from PyQt5.QtWidgets import QApplication, QPushButton, QTableWidget

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Solo consulta")
    user = User.create(username="consulta_toolbar", password_hash="x", profile=profile)
    _order_with_contents()

    with _runtime_load_order_page():
        window = FemagDesktopWindow(user=user, demo_mode=True)
        window.show()
        app.processEvents()
        window.findChild(QTableWidget, "loadOrdersTable").setCurrentCell(0, 0)
        app.processEvents()

        button = window.findChild(QPushButton, "editLoadOrderTraceabilityButton")
        assert button is not None
        assert button.isHidden() is True
        window.close()


def test_stale_cloud_event_conflicts_after_local_edit(db):
    from app.models.sync import SyncConflict
    from app.services.sync_event_consumer import SyncEventConsumer
    from app.services.sync_service import SyncService

    order, _line, allocation, loose = _order_with_contents()
    service = LoadOrderTraceabilityService("secretaria")
    service.update_lote_fecha(
        order,
        [
            {
                "kind": "pallet_content",
                "id": allocation.id,
                "lote": "LOTE-LOCAL",
                "fecha_elaboracion": date(2026, 10, 25),
                "fecha_envasado": date(2026, 10, 26),
            }
        ],
    )
    order_map = SyncService.ensure_entity_uid(
        SyncEntityMap.ENTITY_ORDER, order.id
    )
    content_map = SyncService.ensure_entity_uid(
        SyncEntityMap.ENTITY_PALLET_CONTENT, allocation.id
    )
    event = {
        "event_id": "evento-viejo-864",
        "event_type": "order_content_lote_fecha_updated",
        "origin": "cloud",
        "aggregate_type": "pallet_content",
        "aggregate_id": content_map.global_uid,
        "aggregate_version": 1,
        "cursor": 1,
        "occurred_at": "2026-10-29T12:00:00Z",
        "payload": {
            "order_uid": order_map.global_uid,
            "content_uid": content_map.global_uid,
            "content_type": "pallet",
            "lote": "LOTE-NUBE",
            "fecha_elaboracion": "2026-10-29",
            "expected_version": 1,
        },
    }

    class _FakeClient:
        def __init__(self):
            self.acks = []

        def get_events(self, cursor=0, limit=50):
            return {"events": [event], "next_cursor": cursor}

        def ack_event(self, event_id, result, error=None):
            self.acks.append((event_id, result, error))
            return {"event_id": event_id, "result": result}

    client = _FakeClient()
    result = SyncEventConsumer(client).pull_and_apply()

    assert result["conflicts"] == 1
    assert client.acks[0][1] == "conflict"
    assert SyncConflict.select().where(SyncConflict.status == "open").count() == 1
    allocation = LoadOrderPalletAllocation.get_by_id(allocation.id)
    assert allocation.lote == "LOTE-LOCAL"
