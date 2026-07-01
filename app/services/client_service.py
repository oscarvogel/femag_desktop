from app.models.masters import Client, ClientAddress
from app.services.audit_service import AuditService


class ClientService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def create_client(
        self,
        name: str,
        cuit: str,
        iva_condition: str,
        phone: str | None = None,
        email: str | None = None,
        contact: str | None = None,
        lista_precios: int = 1,
    ) -> Client:
        if lista_precios not in (1, 2, 3, 4):
            raise ValueError("La lista de precios del cliente debe ser 1, 2, 3 o 4.")
        client = Client.create(
            name=name,
            cuit=cuit,
            iva_condition=iva_condition,
            phone=phone,
            email=email,
            contact=contact,
            lista_precios=lista_precios,
        )
        self.audit_service.record(
            user=self.current_user,
            module="Clientes",
            action="crear",
            record_ref=f"Client:{client.id}",
            new_value={"name": name, "cuit": cuit},
        )
        return client

    def add_address(
        self,
        client: Client,
        address_type: str,
        province: str,
        city: str,
        address: str,
        is_primary: bool = False,
        observations: str | None = None,
    ) -> ClientAddress:
        normalized_type = address_type.lower()
        if normalized_type == "fiscal" and ClientAddress.select().where(
            ClientAddress.client == client,
            ClientAddress.address_type == "fiscal",
        ).exists():
            raise ValueError("El cliente ya tiene un domicilio fiscal")
        if normalized_type == "entrega" and is_primary:
            (
                ClientAddress.update(is_primary=False)
                .where(
                    ClientAddress.client == client,
                    ClientAddress.address_type == "entrega",
                    ClientAddress.is_primary == True,  # noqa: E712
                )
                .execute()
            )
        row = ClientAddress.create(
            client=client,
            address_type=normalized_type,
            province=province,
            city=city,
            address=address,
            is_primary=is_primary,
            observations=observations,
        )
        self.audit_service.record(
            user=self.current_user,
            module="Clientes",
            action="crear domicilio",
            record_ref=f"ClientAddress:{row.id}",
            new_value={"client_id": client.id, "type": normalized_type, "address": address},
        )
        return row
