from __future__ import annotations


def test_whatsapp_extract_uses_latest_persisted_client_phone(db):
    from app.models.masters import Client
    from app.ui.desktop_app import _current_client_phone

    Client.create(
        name="Cliente WhatsApp",
        cuit="30777774820",
        iva_condition="RI",
        phone="0376 15 4000000",
    )
    stale_client = Client.get(Client.cuit == "30777774820")
    updated_client = Client.get_by_id(stale_client.id)
    updated_client.phone = "+54 9 376 4555123"
    updated_client.save(only=[Client.phone])

    assert stale_client.phone == "0376 15 4000000"
    assert _current_client_phone(stale_client) == "+54 9 376 4555123"


def test_whatsapp_extract_dialog_preloads_phone_and_professional_message(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.whatsapp_send import WhatsAppSendDialog

    app = QApplication.instance() or QApplication([])
    dialog = WhatsAppSendDialog(
        client_name="Distribuidora Norte",
        phone="+54 9 376 4555123",
    )
    app.processEvents()

    assert dialog.phone_input.text() == "+54 9 376 4555123"
    assert dialog.phone() == "+54 9 376 4555123"
    assert dialog.caption() == (
        "Hola Distribuidora Norte. Le enviamos adjunto el resumen actualizado de su "
        "cuenta corriente con FEMAG. Ante cualquier consulta, quedamos a disposición."
    )

    dialog.phone_input.setText("+54 9 376 4999999")
    dialog.caption_input.setPlainText("Mensaje personalizado")

    assert dialog.phone() == "+54 9 376 4999999"
    assert dialog.caption() == "Mensaje personalizado"
    dialog.close()


def test_whatsapp_extract_dialog_allows_missing_phone_until_confirmation(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.whatsapp_send import WhatsAppSendDialog

    app = QApplication.instance() or QApplication([])
    dialog = WhatsAppSendDialog(client_name="Cliente sin teléfono", phone="")
    app.processEvents()

    assert dialog.phone_input.text() == ""
    assert dialog.normalized_label.text() == "Número final: —"
    dialog.close()
