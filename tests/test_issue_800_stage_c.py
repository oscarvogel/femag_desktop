import os
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_APP = None


def _application():
    global _APP
    from PyQt5.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


def _admin_user(username: str):
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    return User.create(username=username, password_hash="x", profile=profile)


def _manager_user(username: str):
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Gerencia")
    return User.create(username=username, password_hash="x", profile=profile)


def test_client_detail_shows_ledger_service_balance_and_opens_exact_client(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QLabel, QPushButton

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.ui.master_detail_dialogs import ClientDetailDialog

    app = _application()
    user = _admin_user("ui_800_balance")
    client = Client.create(name="Cliente Saldo", cuit="30700000820", iva_condition="RI")
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        total_amount=Decimal("150.00"),
        description="Saldo de prueba",
        source_ref="test:800:balance",
    )
    opened: list[int] = []
    dialog = ClientDetailDialog(
        current_user=user.username,
        record_id=client.id,
        user=user,
        view_ledger_callback=lambda value: opened.append(value.id),
    )

    assert dialog.findChild(QLabel, "clientDetailBalanceValue").text() == "$150.00"
    button = dialog.findChild(QPushButton, "clientDetailOpenLedgerButton")
    assert button.isEnabled()

    button.click()
    app.processEvents()

    assert opened == [client.id]
    assert dialog.result() == dialog.Accepted


def test_client_detail_does_not_show_accounting_without_permission(db):
    from PyQt5.QtWidgets import QLabel, QPushButton

    from app.models.masters import Client
    from app.ui.master_detail_dialogs import ClientDetailDialog

    _application()
    user = _manager_user("ui_800_no_accounting")
    client = Client.create(name="Cliente Sin Permiso", cuit="30700000821", iva_condition="RI")
    dialog = ClientDetailDialog(
        current_user=user.username,
        record_id=client.id,
        user=user,
        view_ledger_callback=lambda _client: None,
        print_envelope_callback=lambda _budget: None,
    )

    assert dialog.findChild(QLabel, "clientDetailBalanceValue") is None
    assert dialog.findChild(QPushButton, "clientDetailOpenLedgerButton") is None
    assert dialog.findChild(QPushButton, "clientDetailPrintEnvelopeButton").isEnabled() is False
    assert dialog.findChild(QPushButton, "clientDetailWhatsAppButton").isEnabled() is False


def test_client_detail_lists_only_active_budgets_and_prints_selected(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QPushButton, QTableWidget

    from app.models.budgets import Budget
    from app.models.masters import Client
    from app.ui.master_detail_dialogs import ClientDetailDialog

    _application()
    user = _admin_user("ui_800_budgets")
    client = Client.create(name="Cliente Presupuestos", cuit="30700000822", iva_condition="RI")
    active = Budget.create(
        budget_number=8001,
        client=client,
        origin=Budget.ORIGIN_MANUAL,
        issue_date=date(2026, 10, 27),
        status=Budget.STATUS_ACTIVE,
        total_amount=1234.5,
    )
    Budget.create(
        budget_number=8002,
        client=client,
        origin=Budget.ORIGIN_MANUAL,
        issue_date=date(2026, 10, 26),
        status=Budget.STATUS_ANNULLED,
        total_amount=500,
    )
    printed: list[int] = []
    dialog = ClientDetailDialog(
        current_user=user.username,
        record_id=client.id,
        user=user,
        print_envelope_callback=lambda budget: printed.append(budget.id),
    )

    table = dialog.findChild(QTableWidget, "clientDetailBudgetsTable")
    assert table.rowCount() == 1
    assert table.item(0, 0).data(Qt.UserRole) == active.id
    assert table.item(0, 0).text() == active.display_number
    button = dialog.findChild(QPushButton, "clientDetailPrintEnvelopeButton")
    assert button.isEnabled()

    button.click()

    assert printed == [active.id]


def test_detail_edit_button_calls_callback_and_refreshes_the_card(db):
    from PyQt5.QtWidgets import QLabel, QPushButton

    from app.models.masters import Client
    from app.ui.master_detail_dialogs import ClientDetailDialog

    _application()
    user = _admin_user("ui_800_edit")
    client = Client.create(name="Cliente Editable", cuit="30700000823", iva_condition="RI")
    calls: list[tuple[str, int]] = []

    def edit_callback(kind: str, record_id: int) -> bool:
        calls.append((kind, record_id))
        record = Client.get_by_id(record_id)
        record.name = "Cliente Editado"
        record.save()
        return True

    dialog = ClientDetailDialog(
        current_user=user.username,
        record_id=client.id,
        user=user,
        can_edit_callback=lambda kind: kind == "client",
        edit_callback=edit_callback,
    )
    button = dialog.findChild(QPushButton, "editMasterDetailButton")
    assert button.isEnabled()

    button.click()

    assert calls == [("client", client.id)]
    assert dialog.findChild(QLabel, "clientDetailNameValue").text() == "Cliente Editado"


def test_detail_edit_button_is_disabled_without_permission(db):
    from app.models.masters import Client
    from app.ui.master_detail_dialogs import ClientDetailDialog

    _application()
    user = _admin_user("ui_800_edit_disabled")
    client = Client.create(name="Cliente Solo Lectura", cuit="30700000824", iva_condition="RI")
    dialog = ClientDetailDialog(
        current_user=user.username,
        record_id=client.id,
        user=user,
        can_edit_callback=lambda _kind: False,
        edit_callback=lambda _kind, _record_id: True,
    )

    assert dialog.edit_button.isEnabled() is False


def test_whatsapp_text_dialog_validates_and_confirms_recipient_and_message(
    db, monkeypatch
):
    from PyQt5.QtWidgets import QMessageBox, QPushButton

    from app.ui.whatsapp_send import WhatsAppTextDialog

    _application()
    dialog = WhatsAppTextDialog(
        recipient_name="Cliente WhatsApp",
        phone="+5491153088679",
    )
    dialog.message_input.setPlainText("Hola, mensaje de prueba")
    monkeypatch.setattr(
        "app.ui.whatsapp_send.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.Yes,
    )

    dialog.findChild(QPushButton, "confirmWhatsAppTextSendButton").click()

    assert dialog.result() == dialog.Accepted
    assert dialog.message() == "Hola, mensaje de prueba"
    assert dialog.phone() == "+5491153088679"

    invalid = WhatsAppTextDialog(recipient_name="Cliente", phone="123")
    invalid.message_input.setPlainText("Hola")
    invalid.findChild(QPushButton, "confirmWhatsAppTextSendButton").click()

    assert invalid.result() != invalid.Accepted
    assert invalid.feedback.message


def test_whatsapp_service_sends_text_and_records_delivery(db):
    from app.models.security import User, UserProfile
    from app.models.whatsapp import WhatsAppEnvio
    from app.services.whatsapp_envio_service import WhatsAppEnvioService

    class FakeClient:
        def __init__(self):
            self.config = SimpleNamespace(instance_id="legacy-instance")
            self.sent: dict = {}

        def send_text(self, **kwargs):
            self.sent = kwargs
            return {"messageId": "msg-800", "status": "accepted"}

        def get_message(self, message_id, *, instance_id=None):
            assert message_id == "msg-800"
            return {
                "status": "delivered",
                "deliveredAt": "2026-10-27T12:00:00Z",
            }

    _application()
    profile = UserProfile.create(name="Perfil WhatsApp 800")
    user = User.create(
        username="ui_800_whatsapp",
        password_hash="x",
        profile=profile,
        whatsapp_instance_id="user-instance-800",
    )
    fake_client = FakeClient()
    service = WhatsAppEnvioService(client=fake_client)

    envio = service.create_text_attempt(
        tipo_documento="mensaje_ficha_cliente",
        documento_id="1",
        destinatario="+5491153088679",
        message="Hola desde la ficha",
        usuario=user,
    )
    assert envio.estado == "preparing"
    assert envio.mime_type == "text/plain"
    assert envio.nombre_archivo == "mensaje_de_texto"
    assert envio.instance_id == "user-instance-800"
    assert envio.destinatario == "5491153088679"

    result = service.send_text(
        envio=envio,
        message="Hola desde la ficha",
        poll_attempts=1,
        poll_interval=0,
    )

    assert result.estado == "delivered"
    assert result.message_id == "msg-800"
    assert result.delivered_at is not None
    assert fake_client.sent["message"] == "Hola desde la ficha"
    assert fake_client.sent["instance_id"] == "user-instance-800"
    assert fake_client.sent["actor_name"] == "ui_800_whatsapp"
    assert WhatsAppEnvio.select().count() == 1


def test_client_detail_whatsapp_uses_service_with_confirmed_message(db, monkeypatch):
    from PyQt5.QtWidgets import QDialog, QPushButton

    from app.models.masters import Client
    from app.ui import master_detail_dialogs
    from app.ui.master_detail_dialogs import ClientDetailDialog

    _application()
    user = _admin_user("ui_800_whatsapp_ui")
    client = Client.create(
        name="Cliente WhatsApp UI",
        cuit="30700000825",
        iva_condition="RI",
        phone="+5491153088679",
    )
    captured: dict = {}

    class FakeTextDialog:
        def __init__(self, **kwargs):
            captured["dialog"] = kwargs

        def exec_(self):
            return QDialog.Accepted

        def phone(self):
            return "+5491153088679"

        def message(self):
            return "Mensaje confirmado"

    class FakeService:
        def create_text_attempt(self, **kwargs):
            captured["attempt"] = kwargs
            return SimpleNamespace(id=77)

    class FakeSignal:
        def connect(self, *_args, **_kwargs):
            pass

    class FakeSignals:
        def __init__(self):
            self.succeeded = FakeSignal()
            self.failed = FakeSignal()
            self.finished = FakeSignal()

    class FakeWorker:
        def __init__(self, **kwargs):
            captured["worker"] = kwargs
            self.signals = FakeSignals()

    class FakePool:
        def start(self, worker):
            captured["started"] = worker

    class FakeThreadPool:
        @staticmethod
        def globalInstance():
            return FakePool()

    monkeypatch.setattr(master_detail_dialogs, "WhatsAppTextDialog", FakeTextDialog)
    monkeypatch.setattr(master_detail_dialogs, "WhatsAppEnvioService", FakeService)
    monkeypatch.setattr(master_detail_dialogs, "WhatsAppTextWorker", FakeWorker)
    monkeypatch.setattr(master_detail_dialogs, "QThreadPool", FakeThreadPool)

    dialog = ClientDetailDialog(
        current_user=user.username,
        record_id=client.id,
        user=user,
    )
    button = dialog.findChild(QPushButton, "clientDetailWhatsAppButton")
    assert button.isEnabled()

    button.click()

    assert captured["attempt"] == {
        "tipo_documento": "mensaje_ficha_cliente",
        "documento_id": str(client.id),
        "destinatario": "+5491153088679",
        "message": "Mensaje confirmado",
        "usuario": user,
    }
    assert captured["worker"]["message"] == "Mensaje confirmado"
    assert "enviando" in dialog.whatsapp_status_label.text()

    dialog._whatsapp_succeeded(
        SimpleNamespace(estado="delivered", message_id="msg-800")
    )
    assert "entregado" in dialog.whatsapp_status_label.text()
    assert "msg-800" in dialog.whatsapp_status_label.text()


def test_whatsapp_buttons_exist_only_for_people_and_require_a_saved_phone(db):
    from PyQt5.QtWidgets import QPushButton

    from app.models.masters import Carrier, Client, Driver, Truck
    from app.ui.master_detail_dialogs import (
        CarrierDetailDialog,
        ClientDetailDialog,
        DriverDetailDialog,
        TruckDetailDialog,
    )

    _application()
    user = _admin_user("ui_800_whatsapp_buttons")
    client = Client.create(
        name="Cliente Sin Telefono", cuit="30700000826", iva_condition="RI"
    )
    carrier = Carrier.create(name="Transportista WhatsApp")
    driver = Driver.create(name="Chofer WhatsApp")
    truck = Truck.create(domain="WHA800", carrier=carrier)

    client_dialog = ClientDetailDialog(
        current_user=user.username, record_id=client.id, user=user
    )
    assert (
        client_dialog.findChild(QPushButton, "clientDetailWhatsAppButton").isEnabled()
        is False
    )

    carrier_dialog = CarrierDetailDialog(
        current_user=user.username, record_id=carrier.id, user=user
    )
    assert (
        carrier_dialog.findChild(
            QPushButton, "carrierDetailWhatsAppButton"
        ).isEnabled()
        is False
    )

    driver_dialog = DriverDetailDialog(
        current_user=user.username, record_id=driver.id, user=user
    )
    assert (
        driver_dialog.findChild(QPushButton, "driverDetailWhatsAppButton").isEnabled()
        is False
    )

    truck_dialog = TruckDetailDialog(
        current_user=user.username, record_id=truck.id, user=user
    )
    assert truck_dialog.findChild(QPushButton, "truckDetailWhatsAppButton") is None


def test_master_grid_detail_receives_permissions_and_edit_callbacks(db, monkeypatch):
    from PyQt5.QtWidgets import QDialog, QTableWidget

    from app.models.masters import Carrier, Driver
    from app.ui import master_abm

    _application()
    user = _admin_user("ui_800_detail_callbacks")
    carrier = Carrier.create(name="Carrier Callbacks")
    driver = Driver.create(name="Chofer Callbacks", carrier=carrier)
    captured: dict = {}

    class FakeDetail:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def exec_(self):
            return QDialog.Rejected

    class FakeDriverEntryDialog:
        def __init__(self, *, current_user, record_id, parent=None):
            captured["edited_id"] = record_id

        def exec_(self):
            return QDialog.Accepted

    monkeypatch.setattr(master_abm, "CarrierDetailDialog", FakeDetail)
    monkeypatch.setattr(master_abm, "DriverEntryDialog", FakeDriverEntryDialog)
    config = master_abm.master_abm_configs()["carriers"]
    page = master_abm.build_master_abm_page(
        config=config,
        user=user,
        current_user=user.username,
    )
    table = page.findChild(QTableWidget, "newCarrierButtonTable")
    row = next(
        row for row in range(table.rowCount())
        if table.item(row, 0).text() == "Carrier Callbacks"
    )
    table.setCurrentCell(row, 0)

    table.itemDoubleClicked.emit(table.item(row, 0))

    assert captured["user"] is user
    assert captured["can_edit_callback"]("carrier") is True
    assert captured["can_edit_callback"]("driver") is True
    assert captured["edit_callback"]("driver", driver.id) is True
    assert captured["edited_id"] == driver.id
