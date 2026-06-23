def test_audit_service_records_structured_changes(db):
    from app.models.audit import AuditLog
    from app.services.audit_service import AuditService

    AuditService().record(
        user="admin",
        module="Maestros",
        action="crear",
        record_ref="Client:1",
        old_value={"name": None},
        new_value={"name": "Cliente"},
        observation="alta inicial",
        workstation="PC-ADMIN",
    )

    row = AuditLog.get()
    assert row.user == "admin"
    assert row.module == "Maestros"
    assert row.action == "crear"
    assert row.old_value == {"name": None}
    assert row.new_value == {"name": "Cliente"}
    assert row.workstation == "PC-ADMIN"
