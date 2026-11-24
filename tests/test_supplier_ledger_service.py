"""Tests del libro de movimientos de la cuenta corriente de proveedores (#940)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date
from decimal import Decimal

import pytest

from app.services.supplier_ledger_service import (
    AllocationRequest,
    SupplierLedgerError,
    SupplierLedgerService,
)

CUTOFF = date(2026, 11, 20)


def _supplier(name="COOP NUEVA ARGENTINA"):
    from app.models.suppliers import Supplier

    return Supplier.create(name=name, normalized_name=name)


def _ticket(supplier, code, balance, amount=None):
    from app.models.suppliers import SupplierDocument

    balance = Decimal(balance)
    return SupplierDocument.create(
        supplier=supplier,
        kind=SupplierDocument.KIND_TICKET,
        source_key=f"femagfab:movi:{code}",
        source_code=code,
        issued_at=date(2026, 6, 1),
        amount=Decimal(amount) if amount else balance,
        balance=balance,
        source_hash="x",
    )


def _note(supplier, code, balance):
    from app.models.suppliers import SupplierDocument

    return SupplierDocument.create(
        supplier=supplier,
        kind=SupplierDocument.KIND_PROMISSORY_NOTE,
        source_key=f"femagfab:documentos:{code}",
        source_code=code,
        issued_at=date(2026, 4, 28),
        amount=Decimal("8000000"),
        balance=Decimal(balance),
        source_hash="x",
    )


def _user(username="admin", profile="Administrador"):
    from app.models.security import User, UserProfile

    perfil, _ = UserProfile.get_or_create(name=profile)
    return User.create(username=username, password_hash="x", profile=perfil)


def _pay(service, supplier, *pairs, amount=None, key=None, when=date(2026, 11, 22)):
    allocations = [AllocationRequest(document=doc, amount=Decimal(val)) for doc, val in pairs]
    total = amount if amount is not None else sum(Decimal(v) for _, v in pairs)
    return service.register_payment(
        supplier=supplier,
        amount=total,
        method="transferencia",
        allocations=allocations,
        payment_date=when,
        idempotency_key=key,
    )


@pytest.fixture()
def libro(db):
    supplier = _supplier()
    t1 = _ticket(supplier, "000000044143", "299060.00")
    t2 = _ticket(supplier, "000000044150", "100000.00")
    pagare = _note(supplier, "0616", "5700000.00")
    service = SupplierLedgerService("admin")
    return service, supplier, t1, t2, pagare


def test_el_saldo_inicial_respeta_el_signo_y_es_idempotente(libro):
    service, supplier, *_ = libro

    assert service.open_ledger_from_imports(cutoff=CUTOFF) == 3
    assert service.open_ledger_from_imports(cutoff=CUTOFF) == 0
    # Tickets suman (la empresa debe), el pagare resta (debe el productor).
    assert service.balance(supplier) == Decimal("299060.00") + Decimal("100000.00") - Decimal("5700000.00")
    # Antes del corte no hay libro.
    assert service.balance(supplier, at=date(2026, 11, 19)) == Decimal("0.00")


def test_todo_movimiento_tiene_autor_fecha_y_observacion(libro):
    from app.models.suppliers import SupplierAccountMovement

    service, supplier, t1, *_ = libro
    service.open_ledger_from_imports(cutoff=CUTOFF)
    _pay(service, supplier, (t1, "1000"))

    movimientos = list(SupplierAccountMovement.select())
    assert movimientos
    for movimiento in movimientos:
        assert movimiento.created_by == "admin"
        assert movimiento.movement_date is not None
        assert movimiento.observations


def test_pago_parcial_en_varios_documentos(libro):
    service, supplier, t1, t2, _ = libro
    service.open_ledger_from_imports(cutoff=CUTOFF)
    antes = service.balance(supplier)

    pago = _pay(service, supplier, (t1, "200000"), (t2, "100000"))

    assert pago.number.startswith("OPP-")
    assert service.document_pending(t1) == Decimal("99060.00")
    assert service.document_pending(t2) == Decimal("0.00")
    assert service.balance(supplier) == antes - Decimal("300000.00")
    assert pago.allocations.count() == 2


def test_doble_activacion_registra_un_solo_pago(libro):
    from app.models.suppliers import SupplierAccountMovement, SupplierPayment

    service, supplier, t1, *_ = libro
    primero = _pay(service, supplier, (t1, "1000"), key="clic-1")
    segundo = _pay(service, supplier, (t1, "1000"), key="clic-1")

    assert primero.id == segundo.id
    assert SupplierPayment.select().count() == 1
    assert (
        SupplierAccountMovement.select()
        .where(SupplierAccountMovement.movement_type == SupplierAccountMovement.TYPE_PAYMENT)
        .count()
        == 1
    )
    assert service.document_pending(t1) == Decimal("298060.00")


def test_la_clave_reusada_con_otro_importe_se_rechaza(libro):
    service, supplier, t1, *_ = libro
    _pay(service, supplier, (t1, "1000"), key="clic-1")
    with pytest.raises(SupplierLedgerError, match="idempotencia"):
        _pay(service, supplier, (t1, "2000"), key="clic-1")


def test_dos_pagos_legitimos_de_igual_importe_son_distintos(libro):
    service, supplier, t1, *_ = libro
    a = _pay(service, supplier, (t1, "1000"), key="a")
    b = _pay(service, supplier, (t1, "1000"), key="b")
    sin_clave = _pay(service, supplier, (t1, "1000"))

    assert len({a.id, b.id, sin_clave.id}) == 3
    assert service.document_pending(t1) == Decimal("296060.00")


def test_no_deja_un_documento_en_negativo(libro):
    service, supplier, t1, *_ = libro
    _pay(service, supplier, (t1, "299000"))
    with pytest.raises(SupplierLedgerError, match="negativo"):
        _pay(service, supplier, (t1, "100"))
    assert service.document_pending(t1) == Decimal("60.00")


def test_las_imputaciones_deben_sumar_el_pago(libro):
    service, supplier, t1, *_ = libro
    with pytest.raises(SupplierLedgerError, match="coincidir"):
        _pay(service, supplier, (t1, "1000"), amount=Decimal("1500"))


def test_no_imputa_a_un_pagare_ni_a_documentos_de_otro_proveedor(libro):
    service, supplier, _, _, pagare = libro
    with pytest.raises(SupplierLedgerError, match="no lo cancela"):
        _pay(service, supplier, (pagare, "1000"))

    otro = _supplier("TERESCHUK ALBERTO CESAR")
    ajeno = _ticket(otro, "000000050000", "5000")
    with pytest.raises(SupplierLedgerError, match="no es de este proveedor"):
        _pay(service, supplier, (ajeno, "1000"))


def test_no_imputa_dos_veces_el_mismo_documento(libro):
    service, supplier, t1, *_ = libro
    with pytest.raises(SupplierLedgerError, match="dos veces"):
        _pay(service, supplier, (t1, "100"), (t1, "200"))


def test_anular_revierte_solo_ese_pago(libro):
    service, supplier, t1, t2, _ = libro
    service.open_ledger_from_imports(cutoff=CUTOFF)
    _user()
    inicial = service.balance(supplier)
    a = _pay(service, supplier, (t1, "1000"), (t2, "500"), key="a")
    b = _pay(service, supplier, (t1, "1000"), (t2, "500"), key="b")

    from app.models.security import User

    service.annul_payment(a, authorized_by=User.get(User.username == "admin"), reason="Cargado dos veces")

    from app.models.suppliers import SupplierPayment

    assert SupplierPayment.get_by_id(a.id).status == SupplierPayment.STATUS_ANNULLED
    assert SupplierPayment.get_by_id(b.id).status == SupplierPayment.STATUS_ACTIVE
    assert service.document_pending(t1) == Decimal("298060.00")
    assert service.document_pending(t2) == Decimal("99500.00")
    assert service.balance(supplier) == inicial - Decimal("1500.00")


def test_el_saldo_a_fecha_respeta_el_dia_de_la_anulacion(libro):
    from app.models.security import User

    service, supplier, t1, *_ = libro
    service.open_ledger_from_imports(cutoff=CUTOFF)
    _user()
    inicial = service.balance(supplier)
    pago = _pay(service, supplier, (t1, "1000"), when=date(2026, 11, 21))
    service.annul_payment(pago, authorized_by=User.get(User.username == "admin"), reason="Error")

    assert service.balance(supplier, at=date(2026, 11, 21)) == inicial - Decimal("1000.00")
    assert service.balance(supplier) == inicial


def test_el_saldo_coincide_con_la_suma_de_movimientos(libro):
    from app.models.suppliers import SupplierAccountMovement

    service, supplier, t1, t2, _ = libro
    service.open_ledger_from_imports(cutoff=CUTOFF)
    _pay(service, supplier, (t1, "1234.56"), (t2, "0.44"))

    suma = sum(
        (Decimal(str(m.amount)) for m in SupplierAccountMovement.select()),
        Decimal("0"),
    )
    assert service.balance(supplier) == suma.quantize(Decimal("0.01"))
    assert service.balances()[supplier.id] == service.balance(supplier)


def test_no_se_anula_dos_veces_ni_sin_permiso(libro):
    service, supplier, t1, *_ = libro
    admin = _user()
    pago = _pay(service, supplier, (t1, "1000"))

    with pytest.raises(SupplierLedgerError, match="motivo"):
        service.annul_payment(pago, authorized_by=admin, reason=" ")
    service.annul_payment(pago, authorized_by=admin, reason="Error")
    with pytest.raises(SupplierLedgerError, match="ya esta anulado"):
        service.annul_payment(pago, authorized_by=admin, reason="Error")

    operador = _user("operador", "Operador")
    otro_pago = _pay(service, supplier, (t1, "1000"))
    with pytest.raises(PermissionError):
        SupplierLedgerService("operador").annul_payment(
            otro_pago, authorized_by=operador, reason="Error"
        )
    with pytest.raises(PermissionError, match="sesion"):
        SupplierLedgerService("operador").annul_payment(
            otro_pago, authorized_by=admin, reason="Error"
        )


def test_reintentar_con_la_clave_de_un_pago_anulado_avisa(libro):
    service, supplier, t1, *_ = libro
    admin = _user()
    pago = _pay(service, supplier, (t1, "1000"), key="k")
    service.annul_payment(pago, authorized_by=admin, reason="Error")
    with pytest.raises(SupplierLedgerError, match="anulado"):
        _pay(service, supplier, (t1, "1000"), key="k")


def test_el_pago_crea_el_saldo_inicial_si_el_libro_no_estaba_abierto(libro):
    from app.models.suppliers import SupplierAccountMovement

    service, supplier, t1, *_ = libro
    _pay(service, supplier, (t1, "1000"))

    apertura = SupplierAccountMovement.get(
        SupplierAccountMovement.source_ref == f"SupplierDocument:{t1.id}:opening"
    )
    assert Decimal(str(apertura.amount)) == Decimal("299060.00")
    assert service.balance(supplier) == Decimal("298060.00")
