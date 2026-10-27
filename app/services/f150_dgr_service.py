"""Correccion controlada de datos DGR desde la pantalla F150 (#790).

El operador autorizado puede completar el domicilio de entrega y los rubros
DGR de los productos sin entrar a MySQL. El servicio concentra permisos,
validaciones, auditoria y la unica escritura permitida sobre un remito ya
emitido: calle/ciudad/provincia del snapshot. Nunca toca importes, items,
numeracion, estado ni archivos F150 ya presentados.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.config.database import database_proxy
from app.models.dgr import DgrLocality
from app.models.masters import Product
from app.models.remittances import Remittance, RemittanceItem
from app.models.security import User
from app.services.audit_service import AuditService
from app.services.client_service import ClientService
from app.services.dgr_validation import (
    consistency_issues,
    derive_city_province,
    is_missing_dgr_text,
    locality_issues,
    locality_label,
)
from app.services.f150_batch_service import F150BatchService
from app.services.permission_service import PermissionService


@dataclass(frozen=True)
class ProductDgrUpdate:
    product_id: int
    rh1: str
    rh2: str
    rh3: str
    rh4: str
    unidad_dgr: str


class F150DgrCorrectionService:
    def __init__(
        self,
        current_user: str,
        audit_service: AuditService | None = None,
    ):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def require_permission(self) -> User:
        """Exige un administrador o el permiso de configuracion de F150."""
        user = (
            User.select()
            .where(User.username == self.current_user)
            .order_by(User.id)
            .first()
        )
        if user is None or not bool(user.active):
            raise PermissionError(
                "La correccion de datos DGR requiere un usuario habilitado."
            )
        permissions = PermissionService()
        allowed = permissions.is_administrator(user) or permissions.has_permission(
            user, "Operaciones", "configurar", "Generar F150"
        )
        if not allowed:
            raise PermissionError(
                "La correccion de datos DGR requiere permiso administrativo "
                "(Operaciones / Generar F150 / configurar)."
            )
        return user

    @staticmethod
    def localities(query: str = "") -> list[DgrLocality]:
        rows = DgrLocality.select().order_by(DgrLocality.name, DgrLocality.code)
        text = (query or "").strip()
        if text:
            rows = rows.where(
                (DgrLocality.name.contains(text))
                | (DgrLocality.code.contains(text))
            )
        return list(rows)

    @staticmethod
    def locality_label(locality: DgrLocality | None) -> str:
        return locality_label(locality)

    @staticmethod
    def products_for(remittance: Remittance) -> list[Product]:
        seen = set()
        products = []
        rows = RemittanceItem.select().where(RemittanceItem.remittance == remittance)
        for row in rows.order_by(RemittanceItem.id):
            product = row.product
            if product is None or product.id in seen:
                continue
            seen.add(product.id)
            products.append(product)
        return products

    def correct(
        self,
        remittance: Remittance,
        *,
        address: str,
        city: str,
        province: str,
        locality_id: int,
        product_updates: Iterable[ProductDgrUpdate | dict],
        update_snapshot: bool = True,
    ) -> dict:
        self.require_permission()
        remittance = Remittance.get_by_id(remittance.id)
        delivery = remittance.delivery_address
        if delivery is None:
            raise ValueError("El remito no tiene un domicilio de entrega asociado.")

        locality = DgrLocality.get_or_none(DgrLocality.id == locality_id)
        if locality is None:
            raise ValueError("Elegi una localidad DGR valida.")
        address = " ".join(str(address or "").split())
        city = " ".join(str(city or "").split())
        province = " ".join(str(province or "").split())
        if is_missing_dgr_text(address):
            raise ValueError("Complete la calle/domicilio de entrega.")
        if is_missing_dgr_text(city):
            raise ValueError("Complete la ciudad de entrega.")
        if is_missing_dgr_text(province):
            raise ValueError("Complete la provincia de entrega.")
        issues = locality_issues(locality)
        if issues:
            raise ValueError("; ".join(issues))
        issues = consistency_issues(
            city=city, province=province, locality=locality
        )
        if issues:
            raise ValueError("; ".join(issues))

        updates = self._normalize_product_updates(remittance, product_updates)
        old_address = self._address_snapshot(delivery)
        old_products = {
            update.product_id: self._product_snapshot(
                Product.get_by_id(update.product_id)
            )
            for update in updates
        }

        snapshot_updated = False
        snapshot_skipped_reason = None
        with database_proxy.atomic():
            ClientService(self.current_user, self.audit_service).update_address(
                delivery,
                client=remittance.client,
                address_type=delivery.address_type,
                province=province,
                city=city,
                address=address,
                active=bool(delivery.active),
                locality=locality,
            )
            if update_snapshot:
                if F150BatchService.is_included(remittance):
                    snapshot_skipped_reason = (
                        "El remito ya pertenece a un lote F150: se corrigio el "
                        "maestro, pero no se modifico el snapshot historico ni "
                        "el TXT ya presentado."
                    )
                else:
                    remittance.delivery_address_text = address
                    remittance.delivery_city = city
                    remittance.delivery_province = province
                    remittance.updated_by = self.current_user
                    remittance.save(
                        only=[
                            Remittance.delivery_address_text,
                            Remittance.delivery_city,
                            Remittance.delivery_province,
                            Remittance.updated_by,
                        ]
                    )
                    snapshot_updated = True

            for update in updates:
                product = Product.get_by_id(update.product_id)
                product.rh1 = update.rh1
                product.rh2 = update.rh2
                product.rh3 = update.rh3
                product.rh4 = update.rh4
                product.unidad_dgr = update.unidad_dgr
                product.save(
                    only=[
                        Product.rh1,
                        Product.rh2,
                        Product.rh3,
                        Product.rh4,
                        Product.unidad_dgr,
                    ]
                )
                self.audit_service.record(
                    user=self.current_user,
                    module="F150",
                    action="corregir rubros DGR",
                    record_ref=f"Product:{product.id}",
                    old_value=old_products[product.id],
                    new_value=self._product_snapshot(product),
                )

            self.audit_service.record(
                user=self.current_user,
                module="F150",
                action="corregir datos DGR",
                record_ref=f"Remittance:{remittance.id}",
                old_value={
                    "address": old_address,
                    "products": old_products,
                },
                new_value={
                    "address": self._address_snapshot(delivery),
                    "locality_id": locality.id,
                    "locality": locality_label(locality),
                    "snapshot_updated": snapshot_updated,
                    "products": {
                        update.product_id: self._product_snapshot(
                            Product.get_by_id(update.product_id)
                        )
                        for update in updates
                    },
                },
                observation=snapshot_skipped_reason,
            )

        remittance = Remittance.get_by_id(remittance.id)
        return {
            "snapshot_updated": snapshot_updated,
            "snapshot_skipped_reason": snapshot_skipped_reason,
            "remaining_issues": F150BatchService.validation_issues(remittance),
            "locality": locality,
        }

    def _normalize_product_updates(
        self,
        remittance: Remittance,
        product_updates: Iterable[ProductDgrUpdate | dict],
    ) -> list[ProductDgrUpdate]:
        used_ids = {product.id for product in self.products_for(remittance)}
        normalized = []
        seen = set()
        for raw in product_updates:
            if isinstance(raw, ProductDgrUpdate):
                update = raw
            else:
                update = ProductDgrUpdate(
                    product_id=int(raw["product_id"]),
                    rh1=str(raw.get("rh1") or ""),
                    rh2=str(raw.get("rh2") or ""),
                    rh3=str(raw.get("rh3") or ""),
                    rh4=str(raw.get("rh4") or ""),
                    unidad_dgr=str(raw.get("unidad_dgr") or ""),
                )
            if update.product_id in seen:
                raise ValueError("Hay un producto repetido en la correccion.")
            seen.add(update.product_id)
            if update.product_id not in used_ids:
                raise ValueError(
                    "El producto indicado no pertenece al remito seleccionado."
                )
            for label, value in (
                ("RH1", update.rh1),
                ("RH2", update.rh2),
                ("RH3", update.rh3),
                ("RH4", update.rh4),
            ):
                text = str(value or "").strip()
                if not re.fullmatch(r"\d{1,4}", text):
                    raise ValueError(
                        f"{label} debe ser un codigo numerico autorizado, sin "
                        "inventar valores."
                    )
            unit = str(update.unidad_dgr or "").strip().upper()
            if not re.fullmatch(r"[A-Z0-9]{1,10}", unit):
                raise ValueError(
                    "La unidad DGR debe ser un codigo alfanumerico de hasta 10 "
                    "caracteres."
                )
            normalized.append(
                ProductDgrUpdate(
                    product_id=update.product_id,
                    rh1=update.rh1.strip(),
                    rh2=update.rh2.strip(),
                    rh3=update.rh3.strip(),
                    rh4=update.rh4.strip(),
                    unidad_dgr=unit,
                )
            )
        return normalized

    @staticmethod
    def _address_snapshot(address) -> dict:
        return {
            "id": address.id,
            "address": address.address,
            "city": address.city,
            "province": address.province,
            "locality_id": address.locality_id,
            "locality": (
                locality_label(address.locality) if address.locality else None
            ),
        }

    @staticmethod
    def _product_snapshot(product: Product) -> dict:
        return {
            "id": product.id,
            "name": product.name,
            "rh1": product.rh1,
            "rh2": product.rh2,
            "rh3": product.rh3,
            "rh4": product.rh4,
            "unidad_dgr": product.unidad_dgr,
        }

    @staticmethod
    def suggested_city_province(locality: DgrLocality | None) -> tuple[str, str]:
        return derive_city_province(locality)
