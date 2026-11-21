"""Importacion de los documentos de deuda de proveedores desde `femagfab` (#939).

El legacy no tiene una cuenta corriente: tiene el `SALDO` de cada ticket
(`movi`) y de cada pagare (`documentos`), y lo descuenta a mano cuando alguien
paga. Este servicio trae los documentos **que todavia se deben** y aplica una
politica **de solo lo confiable**: lo que no se puede defender queda afuera,
pero **queda registrado**, con su monto y su motivo, en
:class:`~app.models.suppliers.SupplierDocumentExclusion`.

Politica (medida sobre el dump del 20/11/2026):

**Tickets (`movi`)**

- 5.084 tickets tienen ``SALDO = 0``: ya estan pagados, no son deuda. No se
  importan (se cuentan aparte en ``already_paid``).
- De los 230 que tienen saldo:
  - 222 tienen ``SALDO`` igual al importe calculado: entran con ese saldo.
  - 6 tienen el ``PRECIO`` por tonelada escrito en el campo del saldo (el
    legacy los escribio mal): entran con el saldo **recalculado**
    (``kilos x precio / 1000``) y quedan marcados con ``balance_corrected``.
  - 2 no tienen kilos ni precio utilizable: **quedan afuera**.

No hay pagos parciales: ningun ticket tiene ``0 < SALDO < importe``, asi que
el saldo del legacy es siempre el total o un valor corrupto. Esa comprobacion
esta en el codigo, no en el supuesto: si mañana aparece un pago parcial, el
ticket queda afuera y no infla la deuda.

**Pagarés (`documentos`)**

- 86 tienen ``SALDO = 0``: ya pagados, no son deuda.
- 49 tienen ``0 < SALDO <= IMPORTE``: el saldo pendiente es coherente.
- 4 quedan afuera: 3 con saldo negativo (sobrepago) y 1 con saldo mayor que el
  importe, que no se puede defender.

**Fechas**

126 tickets tienen ``FECHA = 2002-01-01``: son de junio 2026 (el bloque va de
``COMP=000000046624`` a ``000000046750``) y los tickets vecinos con fecha
confiable los acotan entre el 16 y el 18 de junio de 2026. Se importan con la
fecha del vecino anterior, marcados como ``date_inferred``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from app.importers.femagfab import (
    FemagFabSource,
    LegacySupplierPromissoryNote,
    LegacySupplierTicket,
)
from app.models.suppliers import (
    SupplierDocument,
    SupplierDocumentExclusion,
    SupplierLegacyCode,
)


#: Por debajo de esta fecha la fecha del legacy no es confiable: no hay ni un
#: documento ni un movimiento de caja anterior a noviembre de 2016 en la base,
#: asi que una fecha mas antigua es un valor por defecto.
LEGACY_EPOCH = date(2016, 1, 1)

TWOPLACES = Decimal("0.01")

#: El legacy no tiene columna de moneda: es una sola moneda, la de la empresa.
#: La empresa es de Misiones, Argentina (`param`: GRAEF HNOS S.R.L., Capiovi,
#: tel. (03743)) y sus CUITs usan prefijos argentinos, asi que los importes son
#: pesos. Se deja explicito en el documento para que no dependa del supuesto.
LEGACY_CURRENCY = "ARS"


@dataclass
class SupplierDocumentImportReport:
    """Resultado de la importacion de documentos de deuda."""

    imported_tickets: int = 0
    imported_notes: int = 0
    corrected_balances: int = 0
    inferred_dates: int = 0
    already_imported: int = 0
    # Documentos que el legacy ya daba por pagados: no son deuda y no se
    # importan. Se cuentan para que el reporte sea completo.
    already_paid: int = 0
    excluded: list[SupplierDocumentExclusion] = field(default_factory=list)
    imported_amount: Decimal = Decimal("0")
    imported_balance: Decimal = Decimal("0")
    excluded_amount: Decimal = Decimal("0")

    @property
    def imported(self) -> int:
        return self.imported_tickets + self.imported_notes

    @property
    def excluded_count(self) -> int:
        return len(self.excluded)

    def summary(self) -> str:
        return (
            f"{self.imported_tickets} tickets y {self.imported_notes} pageres "
            f"importados por {self.imported_amount}; "
            f"{self.excluded_count} excluidos por {self.excluded_amount}; "
            f"{self.corrected_balances} con saldo corregido; "
            f"{self.inferred_dates} con fecha inferida; "
            f"{self.already_paid} ya pagados (no son deuda)"
        )


def _decimal(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _ticket_amount(ticket: LegacySupplierTicket) -> Decimal:
    """Importe del ticket segun la formula del legacy: kilos x precio / 1000."""
    return (ticket.payable_kg * ticket.price_per_ton / Decimal("1000")).quantize(
        TWOPLACES, rounding=ROUND_HALF_UP
    )


def _as_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_reliable_date(value) -> bool:
    """True cuando la fecha del legacy se puede tomar tal cual."""
    parsed = _as_date(value)
    if parsed is None:
        return False
    if parsed.year < 1:
        return False
    return parsed >= LEGACY_EPOCH


class SupplierDocumentImportService:
    """Importa tickets y pageres con su saldo, aplicando la politica."""

    def __init__(self, source: FemagFabSource | None = None):
        self.source = source or FemagFabSource()

    # -- lectura ---------------------------------------------------------

    def import_documents(self) -> SupplierDocumentImportReport:
        report = SupplierDocumentImportReport()
        tickets = self.source.fetch_supplier_tickets()
        notes = self.source.fetch_supplier_promissory_notes()
        inferred_dates = self._infer_dates(tickets)
        for ticket in tickets:
            self._import_ticket(ticket, inferred_dates, report)
        for note in notes:
            self._import_note(note, report)
        return report

    @staticmethod
    def _infer_dates(
        tickets: list[LegacySupplierTicket],
    ) -> dict[str, tuple[date, date, date | None]]:
        """Deduce la fecha de los tickets que el legacy dejo con fecha por defecto.

        El numero de `COMP` es correlativo y sigue el orden de carga: los
        tickets vecinos con fecha confiable acotan la fecha real dentro de una
        ventana. Se usa la fecha del vecino anterior y se guarda la ventana.
        """
        reliable = [
            (ticket.comp, _as_date(ticket.received_at))
            for ticket in tickets
            if _is_reliable_date(ticket.received_at)
        ]
        reliable.sort(key=lambda item: item[0])
        deduced: dict[str, tuple[date, date, date | None]] = {}
        for ticket in tickets:
            if _is_reliable_date(ticket.received_at):
                continue
            previous = None
            following = None
            for comp, value in reliable:
                if comp < ticket.comp:
                    previous = value
                elif comp > ticket.comp and following is None:
                    following = value
            chosen = previous or following
            if chosen is None:
                continue
            deduced[ticket.comp] = (chosen, previous or chosen, following or chosen)
        return deduced

    # -- escritura -------------------------------------------------------

    def _supplier_for(self, supplier_code: str):
        source_key = self.source.supplier_source_key(supplier_code)
        ficha = SupplierLegacyCode.get_or_none(
            SupplierLegacyCode.source_key == source_key
        )
        return ficha.supplier if ficha is not None else None

    def _import_ticket(
        self,
        ticket: LegacySupplierTicket,
        inferred_dates: dict[str, tuple[date, date, date | None]],
        report: SupplierDocumentImportReport,
    ) -> None:
        source_key = self.source.document_source_key("movi", ticket.comp)
        if SupplierDocument.get_or_none(SupplierDocument.source_key == source_key):
            report.already_imported += 1
            return

        # Un ticket con saldo 0 ya esta pagado: no es deuda.
        if ticket.legacy_balance == 0:
            report.already_paid += 1
            return

        if ticket.payable_kg <= 0 or ticket.price_per_ton <= 0:
            self._exclude(
                report,
                kind=SupplierDocument.KIND_TICKET,
                source_key=source_key,
                source_code=ticket.comp,
                supplier_code=ticket.supplier_code,
                amount=ticket.legacy_balance,
                reason=SupplierDocumentExclusion.REASON_NO_QUANTITY,
                detail=(
                    f"kilos={ticket.payable_kg}, precio={ticket.price_per_ton}; "
                    "el legacy guardo un saldo que no se puede recalcular"
                ),
            )
            return

        supplier = self._supplier_for(ticket.supplier_code)
        if supplier is None:
            self._exclude(
                report,
                kind=SupplierDocument.KIND_TICKET,
                source_key=source_key,
                source_code=ticket.comp,
                supplier_code=ticket.supplier_code,
                amount=ticket.legacy_balance,
                reason=SupplierDocumentExclusion.REASON_WITHOUT_SUPPLIER,
                detail="el codigo de proveedor no existe en el maestro importado",
            )
            return

        amount = _ticket_amount(ticket)
        balance = ticket.legacy_balance
        corrected = False
        if abs(amount - balance) <= Decimal("1"):
            # El saldo del legacy coincide con el importe: se respeta.
            balance = amount
        elif abs(ticket.price_per_ton - balance) <= Decimal("1"):
            # El legacy escribio el precio por tonelada en el campo del saldo.
            # El importe calculado es el valor correcto.
            balance = amount
            corrected = True
        else:
            # Un pago parcial u otra situacion que no se puede defender.
            self._exclude(
                report,
                kind=SupplierDocument.KIND_TICKET,
                source_key=source_key,
                source_code=ticket.comp,
                supplier_code=ticket.supplier_code,
                amount=ticket.legacy_balance,
                reason=SupplierDocumentExclusion.REASON_BALANCE_OUT_OF_RANGE,
                detail=(
                    f"importe={amount}, saldo={ticket.legacy_balance}; "
                    "el saldo no es ni el total ni el precio"
                ),
            )
            return
        if corrected:
            report.corrected_balances += 1

        if _is_reliable_date(ticket.received_at):
            issued_at = _as_date(ticket.received_at)
            bracket_from = bracket_to = None
            inferred = False
        else:
            deduced = inferred_dates.get(ticket.comp)
            if deduced is None:
                issued_at = None
                bracket_from = bracket_to = None
            else:
                issued_at, bracket_from, bracket_to = deduced
            inferred = True
            report.inferred_dates += 1

        SupplierDocument.create(
            supplier=supplier,
            kind=SupplierDocument.KIND_TICKET,
            source_key=source_key,
            source_instance=self.source.instance,
            source_code=ticket.comp,
            issued_at=issued_at,
            date_inferred=inferred,
            date_bracket_from=bracket_from,
            date_bracket_to=bracket_to,
            product_code=ticket.product_code or None,
            quantity_kg=ticket.payable_kg,
            price_per_ton=ticket.price_per_ton,
            amount=amount,
            balance=balance,
            currency=LEGACY_CURRENCY,
            balance_corrected=corrected,
            source_hash=ticket.source_hash,
        )
        report.imported_tickets += 1
        report.imported_amount += amount
        report.imported_balance += balance

    def _import_note(
        self,
        note: LegacySupplierPromissoryNote,
        report: SupplierDocumentImportReport,
    ) -> None:
        source_key = self.source.document_source_key("documentos", note.code)
        if SupplierDocument.get_or_none(SupplierDocument.source_key == source_key):
            report.already_imported += 1
            return

        if note.balance == 0:
            report.already_paid += 1
            return

        if not (Decimal("0") < note.balance <= note.amount):
            self._exclude(
                report,
                kind=SupplierDocument.KIND_PROMISSORY_NOTE,
                source_key=source_key,
                source_code=note.code,
                supplier_code=note.supplier_code,
                amount=note.balance,
                reason=SupplierDocumentExclusion.REASON_BALANCE_OUT_OF_RANGE,
                detail=(
                    f"importe={note.amount}, saldo={note.balance}; "
                    "el saldo no es un pendiente coherente"
                ),
            )
            return

        supplier = self._supplier_for(note.supplier_code)
        if supplier is None:
            self._exclude(
                report,
                kind=SupplierDocument.KIND_PROMISSORY_NOTE,
                source_key=source_key,
                source_code=note.code,
                supplier_code=note.supplier_code,
                amount=note.balance,
                reason=SupplierDocumentExclusion.REASON_WITHOUT_SUPPLIER,
                detail="el codigo de proveedor no existe en el maestro importado",
            )
            return

        SupplierDocument.create(
            supplier=supplier,
            kind=SupplierDocument.KIND_PROMISSORY_NOTE,
            source_key=source_key,
            source_instance=self.source.instance,
            source_code=note.code,
            issued_at=_as_date(note.issued_on),
            date_inferred=False,
            amount=note.amount,
            balance=note.balance,
            currency=LEGACY_CURRENCY,
            balance_corrected=False,
            description=note.concept or None,
            source_hash=note.source_hash,
        )
        report.imported_notes += 1
        report.imported_amount += note.amount
        report.imported_balance += note.balance

    def _exclude(
        self,
        report: SupplierDocumentImportReport,
        *,
        kind: str,
        source_key: str,
        source_code: str,
        supplier_code: str | None,
        amount: Decimal,
        reason: str,
        detail: str,
    ) -> None:
        """Registra la exclusion. Volver a importar no la duplica."""
        exclusion, _created = SupplierDocumentExclusion.get_or_create(
            source_key=source_key,
            defaults={
                "kind": kind,
                "source_code": source_code,
                "supplier_code": supplier_code or None,
                "amount": amount,
                "reason": reason,
                "detail": detail,
            },
        )
        if exclusion.reason != reason:
            exclusion.reason = reason
            exclusion.amount = amount
            exclusion.detail = detail
            exclusion.save()
        report.excluded.append(exclusion)
        report.excluded_amount += amount
