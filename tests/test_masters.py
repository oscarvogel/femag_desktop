def test_master_service_creates_operational_masters_and_audits(db):
    from app.models.audit import AuditLog
    from app.services.master_service import MasterService

    service = MasterService(current_user="admin")
    product = service.create_product("Fecula de mandioca", "kg")
    driver = service.create_driver("Juan Perez", document="123", phone="376")
    carrier = service.create_carrier("Transporte Norte", cuit="30777777770")
    truck = service.create_truck("AB123CD", carrier=carrier)
    pallet = service.create_pallet_type("Pallet comun", "1x1", 12.5)
    service.create_service("Flete interno")

    assert product.unit == "kg"
    assert driver.available is True
    assert truck.carrier == carrier
    assert pallet.weight == 12.5
    assert AuditLog.select().where(AuditLog.module == "Maestros").count() == 6
