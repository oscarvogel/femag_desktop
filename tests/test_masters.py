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


def test_driver_model_allows_pending_carrier_and_own_cuit(db):
    from app.models.masters import Driver

    driver = Driver.create(
        name="Chofer pendiente",
        carrier=None,
        cuit="27123456789",
    )

    stored = Driver.get_by_id(driver.id)

    assert stored.carrier is None
    assert stored.cuit == "27123456789"


def test_truck_and_driver_require_carrier(db):
    import pytest

    from app.services.master_service import MasterService

    service = MasterService(current_user="admin")

    with pytest.raises(ValueError, match="transportista"):
        service.create_driver("Juan Perez", carrier=None)

    with pytest.raises(ValueError, match="transportista"):
        service.create_truck("AB123CD", carrier=None)
