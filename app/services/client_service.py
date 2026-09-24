from app.models.masters import (
    CLIENT_ADDRESS_TYPE_DELIVERY,
    CLIENT_ADDRESS_TYPE_FISCAL,
    CLIENT_ADDRESS_TYPE_LABELS,
    CLIENT_ADDRESS_TYPE_SHARED,
    Client,
    ClientAddress,
    Salesperson,
    client_address_has_delivery_function,
    client_address_has_fiscal_function,
)
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
        dias_plazo_pago: int = 0,
        salesperson: Salesperson | None = None,
    ) -> Client:
        if lista_precios not in (1, 2, 3, 4):
            raise ValueError("La lista de precios del cliente debe ser 1, 2, 3 o 4.")
        dias_plazo_pago = self.validate_payment_term_days(dias_plazo_pago)
        if salesperson is not None and not bool(salesperson.active):
            raise ValueError("El vendedor seleccionado está inactivo.")
        client = Client.create(
            name=name,
            cuit=cuit,
            iva_condition=iva_condition,
            phone=phone,
            email=email,
            contact=contact,
            lista_precios=lista_precios,
            dias_plazo_pago=dias_plazo_pago,
            salesperson=salesperson,
        )
        self.audit_service.record(
            user=self.current_user,
            module="Clientes",
            action="crear",
            record_ref=f"Client:{client.id}",
            new_value={
                "name": name,
                "cuit": cuit,
                "dias_plazo_pago": dias_plazo_pago,
                "salesperson_id": salesperson.id if salesperson is not None else None,
            },
        )
        return client

    def set_salesperson(
        self,
        client: Client,
        salesperson: Salesperson | None,
    ) -> Client:
        new_id = salesperson.id if salesperson is not None else None
        if client.salesperson_id == new_id:
            return client
        if salesperson is not None and not bool(salesperson.active):
            raise ValueError("El vendedor seleccionado está inactivo.")
        previous_id = client.salesperson_id
        client.salesperson = salesperson
        client.save(only=[Client.salesperson])
        self.audit_service.record(
            user=self.current_user,
            module="Clientes",
            action="asignar vendedor",
            record_ref=f"Client:{client.id}",
            old_value={"salesperson_id": previous_id},
            new_value={"salesperson_id": new_id},
        )
        return client

    @staticmethod
    def validate_payment_term_days(value: int) -> int:
        try:
            days = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Los días de plazo de pago deben ser un número entero.") from exc
        if days < 0:
            raise ValueError("Los días de plazo de pago no pueden ser negativos.")
        return days

    @staticmethod
    def active_clients_query():
        """Clientes habilitados para nuevas operaciones, ordenados por nombre."""
        return Client.select().where(Client.active == True).order_by(Client.name)  # noqa: E712

    @staticmethod
    def ensure_active(client: Client) -> Client:
        """Impide usar un cliente inactivo en una operación nueva."""
        if not bool(client.active):
            raise ValueError("El cliente seleccionado está inactivo y no puede usarse en nuevas operaciones.")
        return client

    def set_active(self, client: Client, active: bool) -> Client:
        """Activa/desactiva un cliente sin eliminar su historial."""
        active = bool(active)
        if bool(client.active) == active:
            return client
        previous = bool(client.active)
        client.active = active
        client.save(only=[Client.active])
        self.audit_service.record(
            user=self.current_user,
            module="Clientes",
            action="activar" if active else "desactivar",
            record_ref=f"Client:{client.id}",
            old_value={"active": previous},
            new_value={"active": active},
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
        if normalized_type not in CLIENT_ADDRESS_TYPE_LABELS:
            raise ValueError("El tipo de domicilio no es válido")
        if client_address_has_fiscal_function(normalized_type) and ClientAddress.select().where(
            ClientAddress.client == client,
            ClientAddress.address_type.in_((CLIENT_ADDRESS_TYPE_FISCAL, CLIENT_ADDRESS_TYPE_SHARED)),
        ).exists():
            raise ValueError("El cliente ya tiene un domicilio fiscal")
        if normalized_type == CLIENT_ADDRESS_TYPE_SHARED:
            is_primary = True
        if client_address_has_delivery_function(normalized_type) and is_primary:
            (
                ClientAddress.update(is_primary=False)
                .where(
                    ClientAddress.client == client,
                    ClientAddress.address_type.in_((CLIENT_ADDRESS_TYPE_DELIVERY, CLIENT_ADDRESS_TYPE_SHARED)),
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

    def update_address(
        self,
        row: ClientAddress,
        *,
        client: Client,
        address_type: str,
        province: str,
        city: str,
        address: str,
        active: bool,
    ) -> ClientAddress:
        normalized_type = address_type.lower()
        if normalized_type not in CLIENT_ADDRESS_TYPE_LABELS:
            raise ValueError("El tipo de domicilio no es válido")
        if client_address_has_fiscal_function(normalized_type) and ClientAddress.select().where(
            (ClientAddress.client == client)
            & (ClientAddress.id != row.id)
            & ClientAddress.address_type.in_((CLIENT_ADDRESS_TYPE_FISCAL, CLIENT_ADDRESS_TYPE_SHARED))
        ).exists():
            raise ValueError("El cliente ya tiene un domicilio fiscal")
        if client_address_has_delivery_function(normalized_type):
            (
                ClientAddress.update(is_primary=False)
                .where(
                    (ClientAddress.client == client)
                    & (ClientAddress.id != row.id)
                    & ClientAddress.address_type.in_((CLIENT_ADDRESS_TYPE_DELIVERY, CLIENT_ADDRESS_TYPE_SHARED))
                    & (ClientAddress.is_primary == True)  # noqa: E712
                )
                .execute()
            )
            row.is_primary = True
        row.client = client
        row.address_type = normalized_type
        row.province = province
        row.city = city
        row.address = address
        row.active = active
        row.save()
        self.audit_service.record(
            user=self.current_user,
            module="Clientes",
            action="editar domicilio",
            record_ref=f"ClientAddress:{row.id}",
            new_value={"client_id": client.id, "type": normalized_type, "address": address},
        )
        return row

    @staticmethod
    def consolidate_identical_fiscal_delivery(client: Client) -> ClientAddress | None:
        addresses = list(ClientAddress.select().where(ClientAddress.client == client).order_by(ClientAddress.id))
        shared = next((item for item in addresses if item.address_type == CLIENT_ADDRESS_TYPE_SHARED), None)
        if shared is not None:
            return shared

        fiscals = [item for item in addresses if item.address_type == CLIENT_ADDRESS_TYPE_FISCAL]
        deliveries = [item for item in addresses if item.address_type == CLIENT_ADDRESS_TYPE_DELIVERY]
        for fiscal in fiscals:
            for delivery in deliveries:
                if ClientService._address_identity(fiscal) != ClientService._address_identity(delivery):
                    continue
                fiscal_referenced = ClientService._address_is_referenced(fiscal)
                delivery_referenced = ClientService._address_is_referenced(delivery)
                if fiscal_referenced and delivery_referenced:
                    return None
                keeper, duplicate = (delivery, fiscal) if delivery_referenced else (fiscal, delivery)
                keeper.address_type = CLIENT_ADDRESS_TYPE_SHARED
                keeper.save()
                duplicate.delete_instance()
                return keeper
        return None

    @staticmethod
    def ensure_imported_shared_address(
        client: Client,
        *,
        province: str,
        city: str,
        address: str,
        observations: str | None,
    ) -> ClientAddress | None:
        consolidated = ClientService.consolidate_identical_fiscal_delivery(client)
        if consolidated is not None:
            return consolidated
        existing = ClientAddress.select().where(
            (ClientAddress.client == client)
            & ClientAddress.address_type.in_(
                (CLIENT_ADDRESS_TYPE_FISCAL, CLIENT_ADDRESS_TYPE_DELIVERY, CLIENT_ADDRESS_TYPE_SHARED)
            )
        )
        if existing.exists():
            return None
        return ClientAddress.create(
            client=client,
            address_type=CLIENT_ADDRESS_TYPE_SHARED,
            province=province,
            city=city,
            address=address,
            is_primary=True,
            observations=observations,
        )

    @staticmethod
    def _address_identity(address: ClientAddress) -> tuple[object, ...]:
        return (
            address.province,
            address.city,
            address.address,
            address.observations,
            address.active,
            address.is_primary,
        )

    @staticmethod
    def _address_is_referenced(address: ClientAddress) -> bool:
        for foreign_key, related_model in ClientAddress._meta.backrefs.items():
            if related_model.select().where(foreign_key == address).exists():
                return True
        return False
