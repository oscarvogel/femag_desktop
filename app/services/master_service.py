from app.models.masters import Carrier, Driver, OperationalService, PalletType, Product, Truck
from app.services.audit_service import AuditService


class MasterService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def _record(self, model_name: str, row, payload: dict):
        self.audit_service.record(
            user=self.current_user,
            module="Maestros",
            action="crear",
            record_ref=f"{model_name}:{row.id}",
            new_value=payload,
        )

    def create_product(
        self,
        name: str,
        unit: str,
        *,
        precio_lista_1: float = 0.0,
        precio_lista_2: float = 0.0,
        precio_lista_3: float = 0.0,
        precio_lista_4: float = 0.0,
    ) -> Product:
        row = Product.create(
            name=name,
            unit=unit,
            precio_neto_base=precio_lista_1,
            precio_lista_1=precio_lista_1,
            precio_lista_2=precio_lista_2,
            precio_lista_3=precio_lista_3,
            precio_lista_4=precio_lista_4,
        )
        self._record("Product", row, {"name": name, "unit": unit})
        return row

    def create_driver(
        self,
        name: str,
        *,
        carrier: Carrier | None,
        document: str | None = None,
        phone: str | None = None,
    ) -> Driver:
        if carrier is None:
            raise ValueError("El chofer debe estar asociado a un transportista.")
        row = Driver.create(name=name, carrier=carrier, document=document, phone=phone)
        self._record("Driver", row, {"name": name, "carrier_id": carrier.id})
        return row

    def create_carrier(self, name: str, cuit: str | None = None, phone: str | None = None) -> Carrier:
        row = Carrier.create(name=name, cuit=cuit, phone=phone)
        self._record("Carrier", row, {"name": name, "cuit": cuit})
        return row

    def create_truck(self, domain: str, carrier: Carrier | None) -> Truck:
        if carrier is None:
            raise ValueError("El camion debe estar asociado a un transportista.")
        row = Truck.create(domain=domain, carrier=carrier)
        self._record("Truck", row, {"domain": domain, "carrier_id": carrier.id})
        return row

    def valid_drivers_for_carrier(self, carrier: Carrier) -> list[Driver]:
        return list(
            Driver.select()
            .where(
                Driver.carrier == carrier,
                Driver.active == True,  # noqa: E712
            )
            .order_by(Driver.name)
        )

    def valid_drivers_for_truck(self, truck: Truck) -> list[Driver]:
        return self.valid_drivers_for_carrier(truck.carrier)

    def is_driver_valid_for_carrier(self, driver: Driver, carrier: Carrier) -> bool:
        return bool(driver.active and driver.carrier_id is not None and driver.carrier_id == carrier.id)

    def is_driver_valid_for_truck(self, driver: Driver, truck: Truck) -> bool:
        return self.is_driver_valid_for_carrier(driver, truck.carrier)

    def create_pallet_type(self, type: str, measure: str, weight: float) -> PalletType:
        row = PalletType.create(type=type, measure=measure, weight=weight)
        self._record("PalletType", row, {"type": type, "measure": measure, "weight": weight})
        return row

    def create_service(self, name: str) -> OperationalService:
        row = OperationalService.create(name=name)
        self._record("OperationalService", row, {"name": name})
        return row
