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

    def create_product(self, name: str, unit: str) -> Product:
        row = Product.create(name=name, unit=unit)
        self._record("Product", row, {"name": name, "unit": unit})
        return row

    def create_driver(self, name: str, document: str | None = None, phone: str | None = None) -> Driver:
        row = Driver.create(name=name, document=document, phone=phone)
        self._record("Driver", row, {"name": name})
        return row

    def create_carrier(self, name: str, cuit: str | None = None, phone: str | None = None) -> Carrier:
        row = Carrier.create(name=name, cuit=cuit, phone=phone)
        self._record("Carrier", row, {"name": name, "cuit": cuit})
        return row

    def create_truck(self, domain: str, carrier: Carrier | None = None) -> Truck:
        row = Truck.create(domain=domain, carrier=carrier)
        self._record("Truck", row, {"domain": domain, "carrier_id": carrier.id if carrier else None})
        return row

    def create_pallet_type(self, type: str, measure: str, weight: float) -> PalletType:
        row = PalletType.create(type=type, measure=measure, weight=weight)
        self._record("PalletType", row, {"type": type, "measure": measure, "weight": weight})
        return row

    def create_service(self, name: str) -> OperationalService:
        row = OperationalService.create(name=name)
        self._record("OperationalService", row, {"name": name})
        return row
