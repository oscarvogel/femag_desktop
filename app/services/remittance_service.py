from datetime import date
from decimal import Decimal, InvalidOperation

from app.config.database import database_proxy
from app.models.load_orders import LoadOrder, LoadOrderDestination
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.remittances import Remittance, RemittanceItem, RemittanceSeries
from app.models.system import NumberSequence
from app.services.audit_service import AuditService


class RemittanceSeriesService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    @staticmethod
    def _point_of_sale(value: str) -> str:
        normalized = str(value or "").strip().replace("-", "")
        if not normalized.isdigit() or len(normalized) > 4:
            raise ValueError("El punto de venta debe contener hasta 4 dígitos.")
        return normalized.zfill(4)

    @staticmethod
    def _validate_numbers(next_number: int, end_number: int | None) -> None:
        if next_number <= 0:
            raise ValueError("El próximo número debe ser mayor que cero.")
        if end_number is not None and end_number < next_number:
            raise ValueError("El número final no puede ser menor que el próximo número.")
        if next_number > 99999999 or (end_number is not None and end_number > 99999999):
            raise ValueError("La numeración del talonario admite hasta 8 dígitos.")

    def save(
        self,
        *,
        name: str,
        point_of_sale: str,
        next_number: int,
        end_number: int | None = None,
        active: bool = True,
        is_default: bool = False,
        series: RemittanceSeries | None = None,
    ) -> RemittanceSeries:
        name = str(name or "").strip()
        if not name:
            raise ValueError("Debe indicar un nombre para el talonario.")
        point = self._point_of_sale(point_of_sale)
        self._validate_numbers(next_number, end_number)
        if is_default and not active:
            raise ValueError("El talonario predeterminado debe estar activo.")
        used_numbers = [
            int(remittance.physical_number)
            for remittance in Remittance.select().where(
                (Remittance.physical_point_of_sale == point)
                & (Remittance.physical_number.is_null(False))
            )
        ]
        if used_numbers and next_number <= max(used_numbers):
            raise ValueError("El próximo número debe ser posterior al último remito emitido.")
        old_value = self.snapshot(series) if series is not None else None
        with database_proxy.atomic():
            if is_default:
                RemittanceSeries.update(is_default=False).where(
                    RemittanceSeries.is_default == True  # noqa: E712
                ).execute()
            if series is None:
                series = RemittanceSeries.create(
                    name=name,
                    document_type="Remito R",
                    point_of_sale=point,
                    next_number=next_number,
                    end_number=end_number,
                    active=active,
                    is_default=is_default,
                    created_by=self.current_user,
                    updated_by=self.current_user,
                )
                action = "crear talonario"
            else:
                series = RemittanceSeries.get_by_id(series.id)
                series.name = name
                series.point_of_sale = point
                series.next_number = next_number
                series.end_number = end_number
                series.active = active
                series.is_default = is_default
                series.updated_by = self.current_user
                series.save()
                action = "modificar talonario"
            self.audit_service.record(
                user=self.current_user,
                module="Remitos",
                action=action,
                record_ref=f"RemittanceSeries:{series.id}",
                old_value=old_value,
                new_value=self.snapshot(series),
            )
        return series

    def skip_number(self, series: RemittanceSeries, *, reason: str) -> RemittanceSeries:
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("Debe indicar por qué se salta la hoja.")
        with database_proxy.atomic():
            series = RemittanceSeries.get_by_id(series.id)
            self._ensure_available(series)
            skipped = series.next_number
            series.next_number += 1
            series.updated_by = self.current_user
            series.save()
            self.audit_service.record(
                user=self.current_user,
                module="Remitos",
                action="saltar hoja",
                record_ref=f"RemittanceSeries:{series.id}",
                old_value={"next_number": skipped},
                new_value={"next_number": series.next_number},
                observation=reason,
            )
        return series

    @staticmethod
    def default() -> RemittanceSeries | None:
        return (
            RemittanceSeries.select()
            .where(
                (RemittanceSeries.active == True)  # noqa: E712
                & (RemittanceSeries.is_default == True)  # noqa: E712
            )
            .order_by(RemittanceSeries.id)
            .first()
        )

    @staticmethod
    def preview(series: RemittanceSeries | None) -> str:
        if series is None:
            return "Sin talonario configurado"
        return f"{series.point_of_sale}-{series.next_number:08d} (se asigna al emitir)"

    @staticmethod
    def _ensure_available(series: RemittanceSeries) -> None:
        if not series.active:
            raise ValueError("El talonario seleccionado está inactivo.")
        if series.end_number is not None and series.next_number > series.end_number:
            raise ValueError("El talonario seleccionado no tiene más números disponibles.")

    def allocate(self, series: RemittanceSeries) -> tuple[str, str]:
        for _attempt in range(5):
            current = RemittanceSeries.get_by_id(series.id)
            self._ensure_available(current)
            number = current.next_number
            updated = (
                RemittanceSeries.update(
                    next_number=number + 1,
                    updated_by=self.current_user,
                )
                .where(
                    (RemittanceSeries.id == current.id)
                    & (RemittanceSeries.next_number == number)
                )
                .execute()
            )
            if updated == 1:
                return current.point_of_sale, f"{number:08d}"
        raise RuntimeError("No se pudo reservar el próximo número del talonario.")

    @staticmethod
    def snapshot(series: RemittanceSeries | None) -> dict | None:
        if series is None:
            return None
        return {
            "id": series.id,
            "name": series.name,
            "document_type": series.document_type,
            "point_of_sale": series.point_of_sale,
            "next_number": series.next_number,
            "end_number": series.end_number,
            "active": series.active,
            "is_default": series.is_default,
        }


class RemittanceService:
    """Reglas de negocio del remito independiente.

    La Orden de carga es solo una fuente opcional de precarga. Los snapshots
    guardados en el remito son deliberadamente independientes de cambios
    posteriores en maestros u ordenes.
    """

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def _next_internal_number(self) -> str:
        sequence, _ = NumberSequence.get_or_create(
            name="remittance", defaults={"current_number": 0}
        )
        sequence.current_number += 1
        sequence.save()
        return f"REM-{sequence.current_number:08d}"

    @staticmethod
    def _normalize_physical_number(value: str | None, *, size: int) -> str | None:
        if value is None or not str(value).strip():
            return None
        normalized = str(value).strip().replace("-", "")
        if not normalized.isdigit():
            raise ValueError("La numeracion fisica del remito debe contener solo digitos.")
        if len(normalized) > size:
            raise ValueError("La numeracion fisica del remito excede el largo permitido.")
        return normalized.zfill(size)

    @staticmethod
    def _validate_header(client: Client, delivery_address: ClientAddress) -> None:
        if client is None:
            raise ValueError("Debe seleccionar un cliente.")
        if delivery_address is None:
            raise ValueError("Debe seleccionar un domicilio.")
        if delivery_address.client_id != client.id:
            raise ValueError("El domicilio seleccionado no pertenece al cliente.")
        if not delivery_address.active:
            raise ValueError("El domicilio seleccionado esta inactivo.")

    @staticmethod
    def _normalize_items(items: list[dict] | None) -> list[dict]:
        if not items:
            raise ValueError("El remito debe contener al menos un producto.")
        normalized = []
        for row in items:
            product = row.get("product")
            if not isinstance(product, Product):
                raise ValueError("Cada renglon debe tener un producto valido.")
            try:
                quantity = Decimal(str(row.get("quantity")))
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError("La cantidad del remito debe ser numerica.") from None
            if quantity <= 0:
                raise ValueError("La cantidad del remito debe ser mayor que cero.")
            description = str(row.get("printed_description") or product.name).strip()
            if not description:
                raise ValueError("Cada renglon debe tener una descripcion para imprimir.")
            normalized.append(
                {
                    "product": product,
                    "product_name": product.name,
                    "printed_description": description,
                    "quantity": quantity,
                    "unit": str(row.get("unit") or product.unit),
                    "lot": row.get("lot"),
                    "production_date": row.get("production_date"),
                    "observations": row.get("observations"),
                }
            )
        return normalized

    def create_manual(
        self,
        *,
        client: Client,
        delivery_address: ClientAddress,
        items: list[dict],
        remittance_date: date | None = None,
        carrier: Carrier | None = None,
        truck: Truck | None = None,
        driver: Driver | None = None,
        physical_point_of_sale: str | None = None,
        physical_number: str | None = None,
        document_reference: str | None = None,
        observations: str | None = None,
        source_order: LoadOrder | None = None,
        series: RemittanceSeries | None = None,
    ) -> Remittance:
        self._validate_header(client, delivery_address)
        normalized_items = self._normalize_items(items)
        point = self._normalize_physical_number(physical_point_of_sale, size=4)
        number = self._normalize_physical_number(physical_number, size=8)
        if bool(point) != bool(number):
            raise ValueError("Punto de venta y numero fisico deben cargarse juntos.")

        with database_proxy.atomic():
            remittance = Remittance.create(
                remittance_number=self._next_internal_number(),
                physical_point_of_sale=point,
                physical_number=number,
                date=remittance_date or date.today(),
                status=Remittance.STATUS_DRAFT,
                client=client,
                delivery_address=delivery_address,
                source_order=source_order,
                series=series or RemittanceSeriesService.default(),
                carrier=carrier,
                truck=truck,
                driver=driver,
                client_name=client.name,
                client_cuit=client.cuit,
                client_iva_condition=client.iva_condition,
                delivery_address_text=delivery_address.address,
                delivery_city=delivery_address.city,
                delivery_province=delivery_address.province,
                document_reference=document_reference,
                carrier_name=carrier.name if carrier else None,
                carrier_cuit=carrier.cuit if carrier else None,
                truck_domain=truck.domain if truck else None,
                driver_name=driver.name if driver else None,
                driver_document=driver.document if driver else None,
                observations=observations,
                created_by=self.current_user,
                updated_by=self.current_user,
            )
            self._replace_items(remittance, normalized_items)
            self.audit_service.record(
                user=self.current_user,
                module="Remitos",
                action="crear",
                record_ref=f"Remittance:{remittance.id}",
                new_value=self._snapshot(remittance),
            )
        return remittance

    def create_from_order(
        self,
        *,
        order: LoadOrder,
        destination: LoadOrderDestination,
        physical_point_of_sale: str | None = None,
        physical_number: str | None = None,
        remittance_date: date | None = None,
        document_reference: str | None = None,
    ) -> Remittance:
        order = LoadOrder.get_by_id(order.id)
        destination = LoadOrderDestination.get_by_id(destination.id)
        if destination.order_id != order.id:
            raise ValueError("El destino seleccionado no pertenece a la Orden de carga.")

        products = list(destination.products)
        if not products:
            raise ValueError("El destino seleccionado no tiene productos para remitir.")
        items = [
            {
                "product": line.product,
                "quantity": line.quantity,
                "unit": line.unit,
                "printed_description": line.product.name,
                "lot": line.lote,
                "production_date": line.fecha_elaboracion,
                "observations": line.observations,
            }
            for line in products
        ]
        return self.create_manual(
            client=destination.client,
            delivery_address=destination.delivery_address,
            items=items,
            remittance_date=remittance_date,
            carrier=order.carrier,
            truck=order.truck,
            driver=order.driver,
            physical_point_of_sale=physical_point_of_sale,
            physical_number=physical_number,
            document_reference=document_reference or f"OC {order.order_number}",
            observations=None,
            source_order=order,
        )

    def update_draft(self, remittance: Remittance, **changes) -> Remittance:
        remittance = Remittance.get_by_id(remittance.id)
        if remittance.status != Remittance.STATUS_DRAFT:
            raise ValueError("Solo se pueden editar remitos en borrador.")
        old_snapshot = self._snapshot(remittance)
        items = changes.pop("items", None)
        normalized_items = self._normalize_items(items) if items is not None else None

        client = changes.pop("client", remittance.client)
        delivery_address = changes.pop("delivery_address", remittance.delivery_address)
        self._validate_header(client, delivery_address)

        if "physical_point_of_sale" in changes or "physical_number" in changes:
            point = self._normalize_physical_number(
                changes.pop("physical_point_of_sale", remittance.physical_point_of_sale), size=4
            )
            number = self._normalize_physical_number(
                changes.pop("physical_number", remittance.physical_number), size=8
            )
            if bool(point) != bool(number):
                raise ValueError("Punto de venta y numero fisico deben cargarse juntos.")
            remittance.physical_point_of_sale = point
            remittance.physical_number = number

        remittance.client = client
        remittance.delivery_address = delivery_address
        remittance.client_name = client.name
        remittance.client_cuit = client.cuit
        remittance.client_iva_condition = client.iva_condition
        remittance.delivery_address_text = delivery_address.address
        remittance.delivery_city = delivery_address.city
        remittance.delivery_province = delivery_address.province

        if "series" in changes:
            remittance.series = changes["series"]

        for field in ("date", "document_reference", "observations"):
            if field in changes:
                setattr(remittance, field, changes[field])
        for relation, snapshot_fields in (
            ("carrier", ("carrier_name", "carrier_cuit")),
            ("truck", ("truck_domain",)),
            ("driver", ("driver_name", "driver_document")),
        ):
            if relation not in changes:
                continue
            value = changes[relation]
            setattr(remittance, relation, value)
            if relation == "carrier":
                remittance.carrier_name = value.name if value else None
                remittance.carrier_cuit = value.cuit if value else None
            elif relation == "truck":
                remittance.truck_domain = value.domain if value else None
            elif relation == "driver":
                remittance.driver_name = value.name if value else None
                remittance.driver_document = value.document if value else None

        remittance.updated_by = self.current_user
        with database_proxy.atomic():
            remittance.save()
            if normalized_items is not None:
                self._replace_items(remittance, normalized_items)
            self.audit_service.record(
                user=self.current_user,
                module="Remitos",
                action="modificar",
                record_ref=f"Remittance:{remittance.id}",
                old_value=old_snapshot,
                new_value=self._snapshot(remittance),
            )
        return remittance

    def issue(self, remittance: Remittance) -> Remittance:
        remittance = Remittance.get_by_id(remittance.id)
        if remittance.status != Remittance.STATUS_DRAFT:
            raise ValueError("Solo se pueden emitir remitos en borrador.")
        if not remittance.items.exists():
            raise ValueError("El remito no tiene productos.")
        old_snapshot = self._snapshot(remittance)
        with database_proxy.atomic():
            if not remittance.physical_point_of_sale or not remittance.physical_number:
                series = remittance.series or RemittanceSeriesService.default()
                if series is None:
                    raise ValueError("Debe configurar un talonario predeterminado antes de emitir.")
                point, number = RemittanceSeriesService(self.current_user).allocate(series)
                remittance.series = series
                remittance.physical_point_of_sale = point
                remittance.physical_number = number
            remittance.status = Remittance.STATUS_ISSUED
            remittance.issued_by = self.current_user
            remittance.updated_by = self.current_user
            remittance.save()
            self.audit_service.record(
                user=self.current_user,
                module="Remitos",
                action="emitir",
                record_ref=f"Remittance:{remittance.id}",
                old_value=old_snapshot,
                new_value=self._snapshot(remittance),
            )
        return remittance

    def annul(self, remittance: Remittance, *, reason: str) -> Remittance:
        remittance = Remittance.get_by_id(remittance.id)
        if remittance.status == Remittance.STATUS_ANNULLED:
            return remittance
        if not reason or not reason.strip():
            raise ValueError("Debe indicar el motivo de anulacion.")
        old_snapshot = self._snapshot(remittance)
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
            old_value=old_snapshot,
            new_value=self._snapshot(remittance),
        )
        return remittance

    @staticmethod
    def _replace_items(remittance: Remittance, items: list[dict]) -> None:
        RemittanceItem.delete().where(RemittanceItem.remittance == remittance).execute()
        for row in items:
            RemittanceItem.create(remittance=remittance, **row)

    @staticmethod
    def _snapshot(remittance: Remittance) -> dict:
        return {
            "id": remittance.id,
            "number": remittance.remittance_number,
            "physical": (
                f"{remittance.physical_point_of_sale}-{remittance.physical_number}"
                if remittance.physical_point_of_sale and remittance.physical_number
                else None
            ),
            "date": str(remittance.date),
            "status": remittance.status,
            "series_id": remittance.series_id,
            "client": remittance.client_name,
            "address": remittance.delivery_address_text,
            "source_order_id": remittance.source_order_id,
            "items": [
                {
                    "product": item.product_name,
                    "description": item.printed_description,
                    "quantity": str(item.quantity),
                    "unit": item.unit,
                }
                for item in remittance.items
            ],
        }
