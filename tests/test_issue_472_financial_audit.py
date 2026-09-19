from PyQt5.QtWidgets import QApplication, QTableWidget

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client, Product
from app.services.audit_history_service import AuditHistoryService
from app.services.auth_service import AuthService
from app.services.budget_print_service import BudgetPrintService
from app.services.budget_service import BudgetService
from app.services.client_manual_debit_service import ClientManualDebitService
from app.services.client_payment_service import ClientPaymentService
from app.services.permission_service import PermissionService
from app.ui.financial_history_dialog import FinancialHistoryDialog


def test_payment_history_tracks_registration_and_annulment_reason(db):
    PermissionService().seed_defaults()
    admin = AuthService().create_user("audit_finance_admin", "secreto", "Administrador")
    client = Client.create(
        name="Cliente Auditoría Pago",
        cuit="30747220001",
        iva_condition="RI",
    )

    service = ClientPaymentService(current_user=admin.username)
    payment = service.register_payment(client=client, amount=1500)
    service.annul_payment(
        payment,
        authorized_by=admin,
        reason="Pago duplicado en caja",
    )

    events = AuditHistoryService().payment_history(payment)

    assert [event.action for event in events] == [
        "Pago registrado",
        "Pago anulado",
    ]
    assert events[-1].previous_status == "activo"
    assert events[-1].new_status == "anulado"
    assert events[-1].reason == "Pago duplicado en caja"


def test_manual_debit_history_tracks_reversal_reason(db):
    client = Client.create(
        name="Cliente Auditoría Débito",
        cuit="30747220002",
        iva_condition="RI",
    )
    service = ClientManualDebitService(current_user="caja_audit")
    movement = service.register_manual_debit(
        client=client,
        amount=2300,
        description="Ajuste manual auditado",
        reference="AUD-DB-1",
    )
    service.reverse_manual_debit(
        movement,
        reason="Corrección de imputación",
    )

    events = AuditHistoryService().account_movement_history(movement)

    assert [event.action for event in events] == [
        "Débito manual registrado",
        "Débito manual reversado",
    ]
    assert events[-1].reason == "Corrección de imputación"


def test_budget_history_tracks_create_print_and_annul_reason(db, tmp_path):
    client = Client.create(
        name="Cliente Auditoría Presupuesto",
        cuit="30747220003",
        iva_condition="RI",
    )
    product = Product.create(name="Producto Auditoría", unit="kg")
    service = BudgetService(current_user="presupuestos_audit")
    budget = service.create_manual(
        client=client,
        items=[
            {
                "product": product,
                "quantity": 10,
                "unit": "kg",
                "unit_price": 1000,
                "discount_percentage": 0,
                "vat_percentage": 21,
            }
        ],
        observations="Presupuesto de prueba auditado",
    )

    BudgetPrintService(current_user="presupuestos_audit").export_pdf(budget, tmp_path)
    service.annul_manual(
        budget,
        reason="Cliente canceló la operación",
    )

    events = AuditHistoryService().budget_history(budget)

    assert [event.action for event in events] == [
        "Presupuesto manual creado",
        "Presupuesto impreso",
        "Presupuesto anulado",
    ]
    assert events[-1].reason == "Cliente canceló la operación"


def test_financial_history_dialog_renders_payment_timeline(db):
    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Historial UI",
        cuit="30747220004",
        iva_condition="RI",
    )
    payment = ClientPaymentService(current_user="caja_ui").register_payment(
        client=client,
        amount=900,
    )
    movement = ClientAccountMovement.get(
        ClientAccountMovement.payment == payment,
        ClientAccountMovement.is_reversal == False,  # noqa: E712
    )

    dialog = FinancialHistoryDialog(movement)
    app.processEvents()
    table = dialog.findChild(QTableWidget, "financialHistoryTable")

    assert table is not None
    assert table.rowCount() == 1
    assert table.item(0, 2).text() == "Pago registrado"
    assert payment.receipt_number in dialog.windowTitle()
