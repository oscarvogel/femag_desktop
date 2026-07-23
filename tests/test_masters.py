from decimal import Decimal

import pytest


def test_master_service_creates_operational_masters_and_audits(db):
    from app.models.audit import AuditLog
    from app.services.master_service import MasterService

    service = MasterService(current_user="admin")
    product = service.create_product("Fecula de mandioca", "kg")
    carrier = service.create_carrier("Transporte Norte", cuit="30777777770")
    driver = service.create_driver("Juan Perez", carrier=carrier, document="123", phone="376")
    truck = service.create_truck("AB123CD", carrier=carrier)
    pallet = service.create_pallet_type("Pallet comun", "1x1", 12.5)
    service.create_service("Flete interno")

    assert product.unit == "kg"
    assert driver.carrier == carrier
    assert driver.available is True
    assert truck.carrier == carrier
    assert pallet.weight == 12.5
    assert AuditLog.select().where(AuditLog.module == "Maestros").count() == 6


def test_driver_can_be_filtered_by_carrier_and_truck(db):
    from app.services.master_service import MasterService

    service = MasterService(current_user="admin")
    north = service.create_carrier("Transporte Norte")
    south = service.create_carrier("Transporte Sur")
    truck = service.create_truck("AB123CD", carrier=north)
    north_driver = service.create_driver("Juan Perez", carrier=north)
    service.create_driver("Pedro Gomez", carrier=south)

    assert service.valid_drivers_for_carrier(north) == [north_driver]
    assert service.valid_drivers_for_truck(truck) == [north_driver]
    assert service.is_driver_valid_for_carrier(north_driver, north) is True
    assert service.is_driver_valid_for_carrier(north_driver, south) is False
    assert service.is_driver_valid_for_truck(north_driver, truck) is True


def test_master_service_creates_trailer_and_habitual_truck_relationship(db):
    from app.services.master_service import MasterService

    service = MasterService(current_user="admin")
    carrier = service.create_carrier("Transporte habitual")
    truck = service.create_truck("AB123CD", carrier=carrier, trailer_domain="EF456GH")
    driver = service.create_driver("Chofer habitual", carrier=carrier, usual_truck=truck)

    assert truck.trailer_domain == "EF456GH"
    assert driver.usual_truck == truck


def test_driver_model_allows_pending_carrier_and_own_cuit(db):
    from app.models.masters import Carrier, Driver
    from app.services.master_service import MasterService

    driver = Driver.create(
        name="Chofer pendiente",
        carrier=None,
        cuit="27123456789",
    )
    carrier = Carrier.create(name="Transporte posterior")

    stored = Driver.get_by_id(driver.id)

    assert stored.carrier is None
    assert stored.cuit == "27123456789"
    assert MasterService(current_user="test").is_driver_valid_for_carrier(stored, carrier) is False


def test_truck_and_driver_require_carrier(db):
    from app.services.master_service import MasterService

    service = MasterService(current_user="admin")

    with pytest.raises(ValueError, match="transportista"):
        service.create_driver("Juan Perez", carrier=None)

    with pytest.raises(ValueError, match="transportista"):
        service.create_truck("AB123CD", carrier=None)


def test_create_product_accepts_unit_weight(db):
    from app.services.master_service import MasterService

    product = MasterService(current_user="admin").create_product(
        "Cemento",
        "bolsa",
        peso_unitario_kg=Decimal("25.000"),
    )

    assert product.peso_unitario_kg == Decimal("25.000")


def test_create_and_update_product_persist_tipo_iva(db):
    from app.models.masters import TipoIVA
    from app.services.master_service import MasterService

    service = MasterService(current_user="admin")
    iva_reducido = TipoIVA.create(nombre="IVA reducido", porcentaje=10.5)
    iva_general = TipoIVA.iva_default()

    product = service.create_product("Producto gravado", "unidad", tipo_iva=iva_reducido)
    assert product.tipo_iva == iva_reducido

    service.update_product(product, product.name, product.unit, tipo_iva=iva_general)
    assert product.tipo_iva == iva_general


def test_create_product_rejects_inactive_tipo_iva(db):
    from app.models.masters import TipoIVA
    from app.services.master_service import MasterService

    iva_inactivo = TipoIVA.create(nombre="IVA inactivo", porcentaje=5.0, activo=False)

    with pytest.raises(ValueError, match="tipo de IVA activo"):
        MasterService(current_user="admin").create_product(
            "Producto invalido",
            "unidad",
            tipo_iva=iva_inactivo,
        )


def test_create_product_rejects_negative_weight(db):
    from app.services.master_service import MasterService

    with pytest.raises(ValueError, match="peso.*no puede ser negativo"):
        MasterService(current_user="admin").create_product(
            "Invalido",
            "unidad",
            peso_unitario_kg=Decimal("-0.001"),
        )
