from pathlib import Path

import pytest
from pypdf import PdfReader

from conftest import _master_data


def _complete_order(data):
    from app.services.load_order_service import LoadOrderService

    data["product"].peso_unitario_kg = 2.5
    data["product"].save()
    return LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [{"product": data["product"], "quantity": 100}],
            }
        ],
        pallets=[
            {
                "sequence": 1,
                "pallet_type": data["pallet"],
                "allocations": [
                    {
                        "client": data["client"],
                        "delivery_address": data["address"],
                        "product": data["product"],
                        "quantity": 100,
                    }
                ],
            }
        ],
    )


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_reprint_requires_permission_and_original_print(db, tmp_path):
    from app.services.load_order_operation_service import LoadOrderOperationService

    order = _complete_order(_master_data())
    operations = LoadOrderOperationService(current_user="secretaria", prints_dir=tmp_path)

    with pytest.raises(PermissionError, match="permiso"):
        operations.reprint_order(order, can_reprint=False)
    with pytest.raises(ValueError, match="Primero debe imprimir"):
        operations.reprint_order(order, can_reprint=True)


def test_reprint_generates_numbered_marked_copies_and_separate_audit(db, tmp_path):
    from app.models.audit import AuditLog
    from app.services.load_order_operation_service import LoadOrderOperationService

    order = _complete_order(_master_data())
    operations = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path)

    original = operations.print_order(order)
    first_copy = operations.reprint_order(order, can_reprint=True)
    second_copy = operations.reprint_order(order, can_reprint=True)

    assert original.name == "orden_carga_1.pdf"
    assert first_copy.name == "orden_carga_1_reimpresion_1.pdf"
    assert second_copy.name == "orden_carga_1_reimpresion_2.pdf"
    assert original.exists() and first_copy.exists() and second_copy.exists()
    assert "REIMPRESIÓN" not in _pdf_text(original)
    assert "REIMPRESIÓN - copia 1 -" in _pdf_text(first_copy)
    assert "REIMPRESIÓN - copia 2 -" in _pdf_text(second_copy)

    audits = list(
        AuditLog.select()
        .where(
            AuditLog.module == "Ordenes de carga",
            AuditLog.record_ref == f"LoadOrder:{order.id}",
            AuditLog.action.in_(("imprimir", "reimprimir")),
        )
        .order_by(AuditLog.id)
    )
    assert [row.action for row in audits] == ["imprimir", "reimprimir", "reimprimir"]
    assert audits[1].new_value["copy_number"] == 1
    assert audits[2].new_value["copy_number"] == 2
    assert audits[1].new_value["reprinted_at"]
