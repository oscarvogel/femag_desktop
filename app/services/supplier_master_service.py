"""Maestro de productores: alta, edicion y baja (#963).

El maestro nacio importado de ``femagfab.proveedo`` (#938), donde el productor
no tiene CUIT ni DNI y dos fichas se unifican por nombre. Este servicio es el
lugar donde FEMAG Desktop mantiene la **persona**: su nombre, sus datos de
contacto y, sobre todo, su CUIT/DNI, que es lo que vuelve verificable la
identidad.

Dos reglas para convivir con la reimportacion:

- ``normalized_name`` es la clave con la que el importador reconoce al legacy.
  Editar el nombre aca **no** la cambia: si cambiara, la proxima importacion
  podria tomar al productor por otro y fusionarlo.
- El importador solo actualiza la ficha del legacy (``SupplierLegacyCode``),
  nunca los datos que se cargan en esta pantalla.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models.suppliers import (
    Supplier,
    SupplierDocument,
    SupplierLegacyCode,
    SupplierPayment,
)
from app.services.audit_service import AuditService
from app.services.supplier_import_service import normalize_supplier_name

AUDIT_MODULE = "Maestros"
MENU_SECTION = "Maestros"
MENU_TITLE = "Productores"
_CUIT_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


class SupplierMasterError(ValueError):
    pass


def normalize_tax_id(value) -> str:
    """Solo los digitos: '20-12345678-3' -> '20123456783'."""
    return "".join(character for character in str(value or "") if character.isdigit())


def is_valid_cuit(digits: str) -> bool:
    if len(digits) != 11 or not digits.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(digits[:10], _CUIT_WEIGHTS))
    check = 11 - (total % 11)
    if check == 11:
        check = 0
    elif check == 10:
        return False
    return check == int(digits[10])


def validate_tax_id(value) -> str | None:
    """Devuelve el CUIT/DNI normalizado, o ``None`` si viene vacio."""
    digits = normalize_tax_id(value)
    if not digits:
        if str(value or "").strip():
            raise SupplierMasterError("El CUIT/DNI solo puede tener números y guiones.")
        return None
    if len(digits) in (7, 8):
        return digits
    if len(digits) == 11:
        if not is_valid_cuit(digits):
            raise SupplierMasterError("El CUIT no es válido: revise el dígito verificador.")
        return digits
    raise SupplierMasterError(
        "El CUIT debe tener 11 dígitos y el DNI 7 u 8."
    )


def format_tax_id(digits: str | None) -> str:
    if not digits:
        return ""
    if len(digits) == 11:
        return f"{digits[:2]}-{digits[2:10]}-{digits[10]}"
    return digits


@dataclass(frozen=True)
class SupplierSummary:
    documents: int
    tickets: int
    notes: int
    imported_balance: Decimal
    payments: int


class SupplierMasterService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    # ---------------------------------------------------------------- lectura
    @staticmethod
    def rows() -> list[list[object]]:
        """Filas para la tabla del ABM: [id, nombre, codigos, localidad, ...]."""
        codes: dict[int, list[str]] = {}
        for ficha in SupplierLegacyCode.select(
            SupplierLegacyCode.supplier, SupplierLegacyCode.code
        ):
            codes.setdefault(ficha.supplier_id, []).append(ficha.code)
        return [
            [
                supplier.id,
                supplier.name,
                ", ".join(sorted(codes.get(supplier.id, []))),
                supplier.locality or "",
                supplier.phone or "",
                format_tax_id(supplier.tax_id),
                "Verificada" if supplier.identity_verified else "Sin verificar",
                "Activo" if supplier.active else "Inactivo",
            ]
            for supplier in Supplier.select().order_by(Supplier.name)
        ]

    @staticmethod
    def summary(supplier: Supplier) -> SupplierSummary:
        documents = list(SupplierDocument.select().where(SupplierDocument.supplier == supplier))
        tickets = sum(1 for d in documents if d.kind == SupplierDocument.KIND_TICKET)
        return SupplierSummary(
            documents=len(documents),
            tickets=tickets,
            notes=len(documents) - tickets,
            imported_balance=sum(
                (Decimal(str(d.balance)) for d in documents), Decimal("0.00")
            ),
            payments=SupplierPayment.select()
            .where(SupplierPayment.supplier == supplier)
            .count(),
        )

    # ---------------------------------------------------------------- escritura
    def _validated(self, *, name, locality, phone, tax_id, identity_verified, supplier_id=None):
        name = " ".join((name or "").split())
        if not name:
            raise SupplierMasterError("Complete el nombre del productor.")
        if len(name) > 80:
            raise SupplierMasterError("El nombre no puede superar los 80 caracteres.")
        locality = (locality or "").strip() or None
        if locality and len(locality) > 40:
            raise SupplierMasterError("La localidad no puede superar los 40 caracteres.")
        phone = (phone or "").strip() or None
        if phone and len(phone) > 40:
            raise SupplierMasterError("El teléfono no puede superar los 40 caracteres.")
        tax_id = validate_tax_id(tax_id)
        if identity_verified and not tax_id:
            raise SupplierMasterError(
                "Para marcar la identidad como verificada hace falta el CUIT/DNI."
            )
        if tax_id:
            other = Supplier.get_or_none(
                (Supplier.tax_id == tax_id)
                & (Supplier.id != (supplier_id or 0))
            )
            if other is not None:
                raise SupplierMasterError(
                    f"El CUIT/DNI {format_tax_id(tax_id)} ya está cargado en "
                    f"«{other.name}»."
                )
        return name, locality, phone, tax_id

    @staticmethod
    def _snapshot(supplier: Supplier) -> dict:
        return {
            "name": supplier.name,
            "locality": supplier.locality,
            "phone": supplier.phone,
            "tax_id": supplier.tax_id,
            "identity_verified": bool(supplier.identity_verified),
            "active": bool(supplier.active),
            "notes": supplier.notes,
        }

    def create(
        self,
        *,
        name: str,
        locality: str | None = None,
        phone: str | None = None,
        tax_id: str | None = None,
        identity_verified: bool = False,
        notes: str | None = None,
    ) -> Supplier:
        name, locality, phone, tax_id = self._validated(
            name=name,
            locality=locality,
            phone=phone,
            tax_id=tax_id,
            identity_verified=identity_verified,
        )
        supplier = Supplier.create(
            name=name,
            normalized_name=normalize_supplier_name(name),
            locality=locality,
            phone=phone,
            tax_id=tax_id,
            identity_verified=bool(identity_verified),
            notes=(notes or "").strip() or None,
        )
        self.audit_service.record(
            user=self.current_user,
            module=AUDIT_MODULE,
            action="crear",
            record_ref=f"Supplier:{supplier.id}",
            new_value=self._snapshot(supplier),
        )
        return supplier

    def update(
        self,
        supplier: Supplier,
        *,
        name: str,
        locality: str | None = None,
        phone: str | None = None,
        tax_id: str | None = None,
        identity_verified: bool = False,
        notes: str | None = None,
    ) -> Supplier:
        supplier = Supplier.get_by_id(supplier.id)
        name, locality, phone, tax_id = self._validated(
            name=name,
            locality=locality,
            phone=phone,
            tax_id=tax_id,
            identity_verified=identity_verified,
            supplier_id=supplier.id,
        )
        before = self._snapshot(supplier)
        supplier.name = name
        # ``normalized_name`` no se toca: es la clave con la que el importador
        # reconoce al productor del legacy.
        supplier.locality = locality
        supplier.phone = phone
        supplier.tax_id = tax_id
        supplier.identity_verified = bool(identity_verified)
        supplier.notes = (notes or "").strip() or None
        supplier.save()
        after = self._snapshot(supplier)
        if after != before:
            self.audit_service.record(
                user=self.current_user,
                module=AUDIT_MODULE,
                action="modificar",
                record_ref=f"Supplier:{supplier.id}",
                old_value=before,
                new_value=after,
            )
        return supplier

    def set_active(self, supplier: Supplier, active: bool) -> Supplier:
        supplier = Supplier.get_by_id(supplier.id)
        if bool(supplier.active) == bool(active):
            return supplier
        supplier.active = bool(active)
        supplier.save()
        self.audit_service.record(
            user=self.current_user,
            module=AUDIT_MODULE,
            action="reactivar" if active else "dar_de_baja",
            record_ref=f"Supplier:{supplier.id}",
            old_value={"active": not active},
            new_value={"active": bool(active)},
        )
        return supplier
