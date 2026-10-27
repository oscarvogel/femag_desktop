from app.config.database import database_proxy
from app.models.dgr import DgrLocality
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
from app.services.whatsapp_phone_classifier import (
    ESTADO_INVALIDO,
    clasificar_telefono,
)


_UNSET = object()


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

    def set_phone(self, client: Client, phone: str | None) -> Client:
        """Guarda el teléfono del cliente y deja registro de quién lo cambió.

        Acepta cualquier teléfono que sirva para llamar: una línea fija también
        sirve, y a veces el cliente no tiene celular. Lo que no se acepta es basura
        (letras o dos números en el mismo campo), porque eso ya no es un teléfono.

        Devuelve el cliente actualizado. Si el teléfono no cambió, no toca la base
        ni genera auditoría.
        """
        texto = (phone or "").strip() or None
        if texto is not None:
            clasificacion = clasificar_telefono(texto)
            if clasificacion.estado == ESTADO_INVALIDO:
                raise ValueError(f"El teléfono no es válido: {clasificacion.motivo}.")
        anterior = (client.phone or "").strip()
        nuevo = texto or ""
        if anterior == nuevo:
            return client
        client.phone = nuevo or None
        client.save(only=[Client.phone, Client.updated_at])
        self.audit_service.record(
            user=self.current_user,
            module="Clientes",
            action="actualizar teléfono",
            record_ref=f"Client:{client.id}",
            old_value={"phone": anterior or None},
            new_value={"phone": nuevo or None},
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
        locality: DgrLocality | None = None,
    ) -> ClientAddress:
        normalized_type = address_type.lower()
        if normalized_type not in CLIENT_ADDRESS_TYPE_LABELS:
            raise ValueError("El tipo de domicilio no es válido")
        province, city = self._complete_city_province(
            province, city, locality, current_province="", current_city=""
        )
        if client_address_has_fiscal_function(normalized_type) and ClientAddress.select().where(
            ClientAddress.client == client,
            ClientAddress.address_type.in_((CLIENT_ADDRESS_TYPE_FISCAL, CLIENT_ADDRESS_TYPE_SHARED)),
        ).exists():
            raise ValueError("El cliente ya tiene un domicilio fiscal")
        if normalized_type == CLIENT_ADDRESS_TYPE_SHARED:
            is_primary = True
        # El cambio de principal, el alta y la auditoria son una sola operacion.
        # Si falla la auditoria o la insercion, el cliente no puede quedar sin
        # principal o con un domicilio a medias (#788).
        with database_proxy.atomic():
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
                locality=locality,
                is_primary=is_primary,
                observations=observations,
            )
            self.audit_service.record(
                user=self.current_user,
                module="Clientes",
                action="crear domicilio",
                record_ref=f"ClientAddress:{row.id}",
                new_value={
                    "client_id": client.id,
                    "type": normalized_type,
                    "address": address,
                    "city": city,
                    "province": province,
                    "locality_id": locality.id if locality is not None else None,
                },
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
        locality: DgrLocality | None | object = _UNSET,
        observations: str | None | object = _UNSET,
    ) -> ClientAddress:
        normalized_type = address_type.lower()
        if normalized_type not in CLIENT_ADDRESS_TYPE_LABELS:
            raise ValueError("El tipo de domicilio no es válido")
        target_locality = row.locality if locality is _UNSET else locality
        province, city = self._complete_city_province(
            province,
            city,
            target_locality,
            current_province=row.province or "",
            current_city=row.city or "",
        )
        previous = {
            "type": row.address_type,
            "province": row.province,
            "city": row.city,
            "address": row.address,
            "locality_id": row.locality_id,
            "active": bool(row.active),
        }
        if client_address_has_fiscal_function(normalized_type) and ClientAddress.select().where(
            (ClientAddress.client == client)
            & (ClientAddress.id != row.id)
            & ClientAddress.address_type.in_((CLIENT_ADDRESS_TYPE_FISCAL, CLIENT_ADDRESS_TYPE_SHARED))
        ).exists():
            raise ValueError("El cliente ya tiene un domicilio fiscal")
        with database_proxy.atomic():
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
            if locality is not _UNSET:
                row.locality = target_locality
            if observations is not _UNSET:
                row.observations = observations
            row.save()
            self.audit_service.record(
                user=self.current_user,
                module="Clientes",
                action="editar domicilio",
                record_ref=f"ClientAddress:{row.id}",
                old_value=previous,
                new_value={
                    "client_id": client.id,
                    "type": normalized_type,
                    "address": address,
                    "city": city,
                    "province": province,
                    "locality_id": row.locality_id,
                    "active": bool(active),
                },
            )
        return row

    @staticmethod
    def _complete_city_province(
        province: str,
        city: str,
        locality: DgrLocality | None,
        *,
        current_province: str,
        current_city: str,
    ) -> tuple[str, str]:
        """Completa ciudad/provincia con la localidad DGR sin pisar datos reales.

        El operador puede corregir a mano la ciudad o la provincia; el sistema
        solo reemplaza vacios o el relleno ``Sin especificar``. La localidad DGR
        manda para completar, no para inventar: si no hay localidad, se conserva
        exactamente lo que vino.
        """
        from app.services.dgr_validation import derive_city_province, is_missing_dgr_text

        if locality is None:
            return province, city
        derived_city, derived_province = derive_city_province(locality)
        final_province = province
        final_city = city
        if is_missing_dgr_text(province) and not is_missing_dgr_text(current_province):
            final_province = current_province
        elif is_missing_dgr_text(province) and derived_province:
            final_province = derived_province
        if is_missing_dgr_text(city) and not is_missing_dgr_text(current_city):
            final_city = current_city
        elif is_missing_dgr_text(city) and derived_city:
            final_city = derived_city
        return final_province, final_city

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
        locality: DgrLocality | None = None,
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
            locality=locality,
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
