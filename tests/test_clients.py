import pytest


def test_client_service_creates_client_addresses_and_audits(db):
    from app.models.audit import AuditLog
    from app.models.masters import ClientAddress
    from app.services.client_service import ClientService

    service = ClientService(current_user="admin")
    client = service.create_client(
        name="Cliente FEMAG",
        cuit="30712345678",
        iva_condition="Responsable Inscripto",
        phone="3764",
        email="cliente@example.com",
        contact="Maria",
    )
    fiscal = service.add_address(client, "fiscal", "Misiones", "Posadas", "Calle 1")
    delivery = service.add_address(
        client, "entrega", "Misiones", "Obera", "Ruta 14", is_primary=True
    )

    assert fiscal.address_type == "fiscal"
    assert delivery.is_primary is True
    assert ClientAddress.select().where(ClientAddress.client == client).count() == 2
    assert AuditLog.select().where(AuditLog.module == "Clientes").count() == 3


def test_client_address_rules_are_enforced(db):
    from app.services.client_service import ClientService

    service = ClientService(current_user="admin")
    client = service.create_client("Cliente", "30700000009", "RI")
    service.add_address(client, "fiscal", "Misiones", "Posadas", "Fiscal")

    with pytest.raises(ValueError, match="domicilio fiscal"):
        service.add_address(client, "fiscal", "Misiones", "Obera", "Otro")

    first = service.add_address(client, "entrega", "Misiones", "A", "A", is_primary=True)
    second = service.add_address(client, "entrega", "Misiones", "B", "B", is_primary=True)
    first_refreshed = type(first).get_by_id(first.id)

    assert first_refreshed.is_primary is False
    assert second.is_primary is True
