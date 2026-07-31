from datetime import date
from decimal import Decimal, InvalidOperation

from app.config.database import database_proxy
from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
from app.models.masters import Client, ClientAddress, Product, product_is_loadable
from app.models.remittances import Remittance, RemittanceItem
from app.models.system import NumberSequence
from app.services.audit_service import AuditService


class RemittanceService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def create_manual(
        self,
        *,
        client: Client,
        delivery_address: ClientAddress,
        products: list[dict],
        remittance_date: date | None = None,
        carrier=None,
        driver=None,
        observations: str | None = None,
    ) -> Remittance:
        return self._create(
            client=client,
            delivery_address=delivery_address,
            products=products,
            remittance_date=remittance_date,
            carrier=carrier,
            driver=driver,
            observations=observations,
            source_order=None,
        )

    def create_from_order(
        self,
        order: LoadOrder,
        destination: LoadOrderDestination,
        *,
        remittance_date: date | None = None,
        observations: str | None = None,
    ) -> Remittance:
        order = LoadOrder.get_by_id(order.id)
        destination = LoadOrderDestination.get_by_id(destination.id)
        if destination.order_id != order.id:
            raise ValueError("El destino seleccionado no pertenece a la orden.")
        lines = list(
            LoadOrderProduct.select()
            .where(LoadOrderProduct.order == order, LoadOrderProduct.destination == destination)
            .order_by(LoadOrderProduct.id)
        )
        if not lines:
            raise ValueError("El destino seleccionado no tiene productos para copiar.")
        products = [
            {
                "product": line.product,
                "quantity": line.quantity,
                "unit": line.unit,
                "observations": line.observations,
            }
            for line in lines
        ]
        return self._create(
            client=destination.client,
            delivery_address=destination.delivery_address,
            products=products,
            remittance_date=remittance_date,
            carrier=order.carrier,
            driver=order.driver,
            observations=observations,
            source_order=order,
        )

    def update_draft(self, remittance: Remittance, **changes) -> Remittance:
        remittance = Remittance.get_by_id(remittance.id)
        if remittance.status != Remittance.STATUS_DRAFT:
            raise ValueError("Solo se pueden modificar remitos en borrador.")
        old_value = self.snapshot(remittance)
        client = changes.pop("client", remittance.client)
        address = changes.pop("delivery_address", remittance.delivery_address)
        products = changes.pop("products", None)
        self._validate_header(client, address)
        normalized = self._validate_products(products) if products is not None else None
        remittance.client = client
        remittance.delivery_address = address
        remittance.client_name = client.name
        remittance.client_cuit = client.cuit
        remittance.delivery_address_text = self._address_text(address)
        for field in ("date", "carrier", "driver", "observations"):
            if field in changes:
                setattr(remittance, field, changes[field])
        remittance.carrier_name = remittance.carrier.name if remittance.carrier else None
        remittance.driver_name = remittance.driver.name if remittance.driver else None
        remittance.updated_by = self.current_user
        with database_proxy.atomic():
            remittance.save()
            if normalized is not None:
                RemittanceItem.delete().where(RemittanceItem.remittance == remittance).execute()
                self._insert_items(remittance, normalized)
            self.audit_service.record(
                user=self.current_user,
                module="Remitos",
                action="modificar",
                record_ref=f"Remittance:{remittance.id}",
                old_value=old_value,
                new_value=self.snapshot(remittance),
            )
        return remittance

    def issue(self, remittance: Remittance) -> Remittance:
        remittance = Remittance.get_by_id(remittance.id)
        if remittance.status != Remittance.STATUS_DRAFT:
            raise ValueError("Solo se puede emitir un remito en borrador.")
        if RemittanceItem.select().where(RemittanceItem.remittance == remittance).count() == 0:
            raise ValueError("El remito debe contener al menos un producto.")
        remittance.status = Remittance.STATUS_ISSUED
        remittance.issued_by = self.current_user
        remittance.updated_by = self.current_user
        remittance.save()
        self.audit_service.record(
            user=self.current_user,
            module="Remitos",
            action="emitir",
            record_ref=f"Remittance:{remittance.id}",
            new_value=self.snapshot(remittance),
        )
        return remittance

    def annul(self, remittance: Remittance, *, can_annul: bool, reason: str) -> Remittance:
        if not can_annul:
            raise PermissionError("No tiene permiso para anular remitos.")
        if not reason or not reason.strip():
            raise ValueError("Debe indicar el motivo de anulacion.")
        remittance = Remittance.get_by_id(remittance.id)
        if remittance.status == Remittance.STATUS_ANNULLED:
            raise ValueError("El remito ya esta anulado.")
        old_status = remittance.status
        remittance.status = Remittance.STATUS_ANNULLED
        remittance.annulled_by = self.current_user
        remittance.annulment_reason = reason.strip()
        remittance.updated_by = self.current_user
        remittance.save()
        self.audit_service.record(
            user=self.current_user,
            module="Remitos",
            action="anular",
            record_ref=f"Remittance:{remittance.id}",
            old_value={"status": old_status},
            new_value={"status": remittance.status, "reason": reason.strip()},
        )
        return remittance

    def list_remittances(self, search: str | None = None) -> list[Remittance]:
        query = Remittance.select().order_by(Remittance.id.desc())
        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.where(
                (Remittance.remittance_number ** term)
                | (Remittance.client_name ** term)
                | (Remittance.status ** term)
            )
        return list(query)

    def snapshot(self, remittance: Remittance) -> dict:
        remittance = Remittance.get_by_id(remittance.id)
        return {
            "number": remittance.remittance_number,
            "date": remittance.date.isoformat(),
            "status": remittance.status,
            "client": remittance.client_name,
            "delivery_address": remittance.delivery_address_text,
            "source_order": remittance.source_order.order_number if remittance.source_order else None,
            "products": [
                {
                    "product": item.product_name,
                    "quantity": str(item.quantity),
                    "unit": item.unit,
                }
                for item in remittance.items.order_by(RemittanceItem.id)
            ],
        }

    def _create(self, **values) -> Remittance:
        client = values["client"]
        address = values["delivery_address"]
        self._validate_header(client, address)
        products = self._validate_products(values["products"])
        carrier = values.get("carrier")
        driver = values.get("driver")
        with database_proxy.atomic():
            remittance = Remittance.create(
                remittance_number=self._next_number(),
                date=values.get("remittance_date") or date.today(),
                client=client,
                delivery_address=address,
                source_order=values.get("source_order"),
                carrier=carrier,
                driver=driver,
                client_name=client.name,
                client_cuit=client.cuit,
                delivery_address_text=self._address_text(address),
                carrier_name=carrier.name if carrier else None,
                driver_name=driver.name if driver else None,
                observations=values.get("observations"),
                created_by=self.current_user,
                updated_by=self.current_user,
            )
            self._insert_items(remittance, products)
            self.audit_service.record(
                user=self.current_user,
                module="Remitos",
                action="crear_desde_orden" if values.get("source_order") else "crear_manual",
                record_ref=f"Remittance:{remittance.id}",
                new_value=self.snapshot(remittance),
            )
        return remittance

    def _next_number(self) -> str:
        sequence, _ = NumberSequence.get_or_create(name="remittance", defaults={"current_number": 0})
        sequence.current_number += 1
        sequence.save()
        return f"REM-{sequence.current_number:08d}"

    @staticmethod
    def _validate_header(client: Client, address: ClientAddress) -> None:
        if not client or not client.active:
            raise ValueError("Debe seleccionar un cliente activo.")
        if not address or not address.active or address.client_id != client.id:
            raise ValueError("Debe seleccionar un domicilio activo del cliente.")

    @staticmethod
    def _validate_products(products: list[dict] | None) -> list[dict]:
        if not products:
            raise ValueError("Debe cargar al menos un producto.")
        normalized = []
        for line in products:
            product = line.get("product")
            if not isinstance(product, Product) or not product.active or not product_is_loadable(product):
                raise ValueError("Todos los productos deben estar activos y habilitados para carga.")
            try:
                quantity = Decimal(str(line.get("quantity")))
            except (InvalidOperation, TypeError):
                raise ValueError("La cantidad de cada producto debe ser numerica.") from None
            if quantity <= 0:
                raise ValueError("La cantidad de cada producto debe ser mayor que cero.")
            normalized.append(
                {
                    "product": product,
                    "quantity": quantity,
                    "unit": (line.get("unit") or product.unit).strip(),
                    "observations": line.get("observations"),
                }
            )
        return normalized

    @staticmethod
    def _insert_items(remittance: Remittance, products: list[dict]) -> None:
        RemittanceItem.insert_many(
            [
                {
                    "remittance": remittance,
                    "product": line["product"],
                    "product_name": line["product"].name,
                    "quantity": line["quantity"],
                    "unit": line["unit"],
                    "observations": line["observations"],
                }
                for line in products
            ]
        ).execute()

    @staticmethod
    def _address_text(address: ClientAddress) -> str:
        return ", ".join(part for part in (address.address, address.city, address.province) if part)
