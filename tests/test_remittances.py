from decimal import Decimal

import pytest


def test_manual_remittance_is_independent_and_numbered(db):
    from app.models.audit import AuditLog
    from app.models.remittances import Remittance
    from app.services.remittance_service import RemittanceService
    from tests.conftest import _master_data

    data = _master_data()
    remittance = RemittanceService(current_user="admin").create_manual(
        client=data["client"],
        delivery_address=data["address"],
        products=[{"product": data["product"], "quantity": Decimal("12.5")}],
    )

    assert remittance.remittance_number == "REM-00000001"
    assert remittance.status == Remittance.STATUS_DRAFT
    assert remittance.source_order is None
    assert remittance.items.get().product_name == "Fecula de mandioca"
    assert AuditLog.get().action == "crear_manual"


def test_remittance_from_order_copies_only_selected_destination(db):
    from app.models.load_orders import LoadOrderDestination
    from app.services.load_order_service import LoadOrderService
    from app.services.remittance_service import RemittanceService
    from tests.conftest import _multi_client_data

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [{"product": data["product"], "quantity": 10}],
            },
            {
                "client": data["other_client"],
                "delivery_address": data["other_address"],
                "products": [{"product": data["third_product"], "quantity": 7}],
            },
        ],
        pallets=[],
    )
    selected = LoadOrderDestination.get(
        LoadOrderDestination.order == order,
        LoadOrderDestination.client == data["other_client"],
    )

    remittance = RemittanceService(current_user="admin").create_from_order(order, selected)
    order.status = order.STATUS_ANNULLED
    order.save()

    assert remittance.source_order.id == order.id
    assert remittance.client.id == data["other_client"].id
    assert [line.product_name for line in remittance.items] == ["Glucosa"]
    assert remittance.status == remittance.STATUS_DRAFT


def test_issued_remittance_cannot_be_edited(db):
    from app.services.remittance_service import RemittanceService
    from tests.conftest import _master_data

    data = _master_data()
    service = RemittanceService(current_user="admin")
    remittance = service.create_manual(
        client=data["client"],
        delivery_address=data["address"],
        products=[{"product": data["product"], "quantity": 2}],
    )
    service.issue(remittance)

    with pytest.raises(ValueError, match="borrador"):
        service.update_draft(remittance, observations="No permitido")


def test_remittance_validates_address_and_products(db):
    from app.services.remittance_service import RemittanceService
    from tests.conftest import _multi_client_data

    data = _multi_client_data()
    service = RemittanceService(current_user="admin")
    with pytest.raises(ValueError, match="domicilio"):
        service.create_manual(
            client=data["client"],
            delivery_address=data["other_address"],
            products=[{"product": data["product"], "quantity": 1}],
        )
    with pytest.raises(ValueError, match="mayor que cero"):
        service.create_manual(
            client=data["client"],
            delivery_address=data["address"],
            products=[{"product": data["product"], "quantity": 0}],
        )
