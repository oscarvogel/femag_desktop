"""Tests de la importacion de documentos de deuda de proveedores (#939)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime
from decimal import Decimal

from app.importers.femagfab import (
    LegacySupplierPromissoryNote,
    LegacySupplierTicket,
)
from app.services.supplier_document_import_service import (
    LEGACY_EPOCH,
    SupplierDocumentImportService,
)


class _FakeSource:
    instance = "femagfab"

    def __init__(self, tickets=None, notes=None):
        self.tickets = list(tickets or [])
        self.notes = list(notes or [])

    def fetch_supplier_tickets(self):
        return list(self.tickets)

    def fetch_supplier_promissory_notes(self):
        return list(self.notes)

    def supplier_source_key(self, code):
        return f"femagfab:femagfab:proveedo:{code}"

    def document_source_key(self, kind, code):
        return f"femagfab:femagfab:{kind}:{code}"


def ticket(
    comp="000000044143",
    supplier="0656",
    received=datetime(2026, 3, 2, 10, 38),
    kg="1574",
    price="190000",
    balance=None,
    product="01",
):
    payable = Decimal(kg)
    precio = Decimal(price)
    if balance is None:
        balance = payable * precio / Decimal("1000")
    return LegacySupplierTicket(
        comp=comp,
        received_at=received,
        supplier_code=supplier,
        product_code=product,
        payable_kg=payable,
        price_per_ton=precio,
        legacy_balance=Decimal(str(balance)),
    )


def note(code="0616", supplier="0656", issued="2026-04-28", amount="8000000", balance="5700000"):
    return LegacySupplierPromissoryNote(
        code=code,
        supplier_code=supplier,
        issued_on=issued,
        amount=Decimal(amount),
        balance=Decimal(balance),
        concept="",
    )


def _crear_maestro_real(db):
    """Crea el maestro de un proveedor concreto sin pasar por el importador."""
    from app.models.suppliers import Supplier, SupplierLegacyCode

    persona = Supplier.create(name="COOP NUEVA ARGENTINA", normalized_name="COOP NUEVA ARGENTINA")
    for code in ("0656", "0999"):
        SupplierLegacyCode.create(
            supplier=persona,
            source_instance="femagfab",
            code=code,
            source_key=f"femagfab:femagfab:proveedo:{code}",
            name=persona.name,
        )
    return persona


def test_importa_un_ticket_con_saldo_recalculado(db):
    from app.models.suppliers import SupplierDocument

    _crear_maestro_real(db)
    service = SupplierDocumentImportService(
        source=_FakeSource(tickets=[ticket()])
    )
    report = service.import_documents()

    assert report.imported_tickets == 1
    assert report.excluded_count == 0
    documento = SupplierDocument.get()
    assert documento.kind == SupplierDocument.KIND_TICKET
    assert documento.balance == Decimal("299060.00")
    assert documento.balance_corrected is False
    assert documento.issued_at == datetime(2026, 3, 2).date()


def test_corrige_el_saldo_que_el_legacy_guardo_como_precio(db):
    """El legacy guardo el precio por tonelada en vez del total."""
    from app.models.suppliers import SupplierDocument

    _crear_maestro_real(db)
    service = SupplierDocumentImportService(
        source=_FakeSource(
            tickets=[ticket(comp="000000044432", kg="4059", price="130000", balance="130000")]
        )
    )
    report = service.import_documents()

    assert report.corrected_balances == 1
    documento = SupplierDocument.get()
    assert documento.balance == Decimal("527670.00")
    assert documento.balance_corrected is True


def test_excluye_el_ticket_sin_kilos_o_precio_utilizable(db):
    from app.models.suppliers import SupplierDocument, SupplierDocumentExclusion

    _crear_maestro_real(db)
    service = SupplierDocumentImportService(
        source=_FakeSource(tickets=[ticket(kg="0", price="165000", balance="165000")])
    )
    report = service.import_documents()

    assert report.imported_tickets == 0
    assert report.excluded_count == 1
    assert SupplierDocument.select().count() == 0
    exclusion = SupplierDocumentExclusion.get()
    assert exclusion.reason == SupplierDocumentExclusion.REASON_NO_QUANTITY
    assert exclusion.amount == Decimal("165000")


def test_excluye_el_pagare_con_saldo_fuera_de_rango(db):
    from app.models.suppliers import SupplierDocument, SupplierDocumentExclusion

    _crear_maestro_real(db)
    service = SupplierDocumentImportService(
        source=_FakeSource(notes=[note(code="0624", amount="1000000", balance="1400000")])
    )
    report = service.import_documents()

    assert report.imported_notes == 0
    assert report.excluded_count == 1
    assert SupplierDocument.select().count() == 0
    exclusion = SupplierDocumentExclusion.get()
    assert exclusion.reason == SupplierDocumentExclusion.REASON_BALANCE_OUT_OF_RANGE


def test_excluye_el_pagare_sobrepagado(db):
    from app.models.suppliers import SupplierDocumentExclusion

    _crear_maestro_real(db)
    service = SupplierDocumentImportService(
        source=_FakeSource(notes=[note(code="0511", amount="350000", balance="-26180")])
    )
    report = service.import_documents()

    assert report.excluded_count == 1
    assert SupplierDocumentExclusion.get().reason == (
        SupplierDocumentExclusion.REASON_BALANCE_OUT_OF_RANGE
    )


def test_importa_el_pagare_con_saldo_coherente(db):
    from app.models.suppliers import SupplierDocument

    _crear_maestro_real(db)
    service = SupplierDocumentImportService(
        source=_FakeSource(notes=[note()])
    )
    report = service.import_documents()

    assert report.imported_notes == 1
    documento = SupplierDocument.get()
    assert documento.kind == SupplierDocument.KIND_PROMISSORY_NOTE
    assert documento.amount == Decimal("8000000")
    assert documento.balance == Decimal("5700000")


def test_excluye_el_documento_de_un_proveedor_que_no_esta_en_el_maestro(db):
    from app.models.suppliers import SupplierDocumentExclusion

    _crear_maestro_real(db)
    service = SupplierDocumentImportService(
        source=_FakeSource(tickets=[ticket(supplier="0000")])
    )
    report = service.import_documents()

    assert report.imported_tickets == 0
    assert report.excluded_count == 1
    assert SupplierDocumentExclusion.get().reason == (
        SupplierDocumentExclusion.REASON_WITHOUT_SUPPLIER
    )


def test_deduce_la_fecha_de_los_tickets_con_fecha_por_defecto(db):
    """El bloque con FECHA = 2002 es de junio 2026: lo acotan los vecinos."""
    from app.models.suppliers import SupplierDocument

    _crear_maestro_real(db)
    tickets = [
        ticket(comp="000000046620", received=datetime(2026, 6, 16, 9, 0)),
        ticket(comp="000000046624", received=datetime(2002, 1, 1), kg="970"),
        ticket(comp="000000046750", received=datetime(2002, 1, 2), kg="832"),
        ticket(comp="000000046780", received=datetime(2026, 6, 18, 9, 0)),
    ]
    service = SupplierDocumentImportService(source=_FakeSource(tickets=tickets))
    report = service.import_documents()

    assert report.inferred_dates == 2
    inferidos = list(
        SupplierDocument.select().where(SupplierDocument.date_inferred == True)  # noqa: E712
    )
    for documento in inferidos:
        assert documento.issued_at == datetime(2026, 6, 16).date()
        assert documento.date_bracket_from == datetime(2026, 6, 16).date()
        assert documento.date_bracket_to == datetime(2026, 6, 18).date()


def test_la_epoca_del_legacy_deja_afuera_las_fechas_imposibles():
    from app.services.supplier_document_import_service import _is_reliable_date

    assert _is_reliable_date(datetime(2026, 3, 2)) is True
    assert _is_reliable_date(datetime(2002, 1, 1)) is False
    assert _is_reliable_date(datetime(2015, 12, 31)) is False
    assert _is_reliable_date(None) is False
    assert LEGACY_EPOCH.year == 2016


def test_reimportar_no_duplica_ni_exclusiones(db):
    from app.models.suppliers import SupplierDocument, SupplierDocumentExclusion

    _crear_maestro_real(db)
    source = _FakeSource(
        tickets=[ticket()], notes=[note(code="0624", amount="1000000", balance="1400000")]
    )
    SupplierDocumentImportService(source=source).import_documents()
    segundo = SupplierDocumentImportService(source=source).import_documents()

    assert segundo.imported == 0
    # El ticket ya estaba importado; el pagare habia quedado afuera, asi que
    # vuelve a quedar afuera (y no se duplica la exclusion).
    assert segundo.already_imported == 1
    assert segundo.excluded_count == 1
    assert SupplierDocument.select().count() == 1
    assert SupplierDocumentExclusion.select().count() == 1


def test_el_documento_guarda_la_moneda_explicita(db):
    """El legacy no tiene columna de moneda: el documento la deja escrita."""
    from app.models.suppliers import SupplierDocument
    from app.services.supplier_document_import_service import LEGACY_CURRENCY

    _crear_maestro_real(db)
    SupplierDocumentImportService(source=_FakeSource(tickets=[ticket()])).import_documents()

    documento = SupplierDocument.get()
    assert documento.currency == "ARS"
    assert LEGACY_CURRENCY == "ARS"


def test_el_saldo_importado_suma_lo_mismo_que_los_documentos(db):
    from app.models.suppliers import SupplierDocument

    _crear_maestro_real(db)
    tickets = [
        ticket(comp="000000044143", kg="1574", price="190000"),
        ticket(comp="000000044144", kg="3500", price="190000", supplier="0999"),
    ]
    service = SupplierDocumentImportService(source=_FakeSource(tickets=tickets))
    report = service.import_documents()

    total_en_base = sum(
        (documento.balance for documento in SupplierDocument.select()), Decimal("0")
    )
    assert total_en_base == report.imported_balance
