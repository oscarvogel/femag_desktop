from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.models.base import utc_now
from app.models.masters import product_is_raw_material
from app.models.production import RawMaterialIntake, RawMaterialIntakeLine
from app.models.stock import StockMovement
from app.services.stock_service import StockService

TWO_PLACES = Decimal("0.01")
THREE_PLACES = Decimal("0.001")

SOURCE_REF_PREFIX = "raw_material_intake"


@dataclass(frozen=True)
class IntakeTotals:
    intakes: int
    lines: int
    bags: int
    kg: Decimal


class RawMaterialIntakeService:
    """Ingreso de materia prima comprada en big bags (#656).

    Es lo que hoy no existe: el legacy `femagfab` recibe raiz de mandioca, no
    big bags de almidon, y FEMAG Desktop no tenia ningun modulo de compras.
    `StockMovement.TYPE_PURCHASE` estaba declarado desde #572 sin que ningun
    servicio lo escribiera, asi que el libro de stock no tenia ninguna entrada.

    El operador **cuenta big bags**, no kilos: en planta el almidon suelto no se
    pesa, se cuentan las unidades que llegan. Los kg se derivan del peso del big
    bag, que queda congelado en la linea igual que el peso de la bolsa en
    ``ProductionBag``. El libro sigue trabajando en kg, asi que no cambia de
    esquema.
    """

    @staticmethod
    def _unit_weight(product) -> Decimal:
        try:
            weight = Decimal(str(product.peso_unitario_kg or 0))
        except InvalidOperation:
            weight = Decimal("0")
        if weight <= 0:
            raise ValueError(
                f"El producto '{product.name}' no tiene peso unitario cargado. "
                "Cargalo en Maestros > Productos, columna «Peso»: en materia prima "
                "ese peso es el de un big bag. Sin el no se pueden calcular los kg."
            )
        return weight.quantize(THREE_PLACES, rounding=ROUND_HALF_UP)

    @classmethod
    def _lines(cls, lines) -> list[tuple]:
        lines = list(lines or [])
        if not lines:
            raise ValueError("Cargá al menos una materia prima en el ingreso.")
        prepared = []
        seen: set[int] = set()
        for product, raw_bags in lines:
            if product is None:
                raise ValueError("Cada línea necesita un producto.")
            if not product_is_raw_material(product):
                raise ValueError(
                    f"'{product.name}' no es materia prima. Marcá su «Rol en el "
                    "stock» como Materia prima en Maestros > Productos: un producto "
                    "terminado se vende tal cual y no se fracciona."
                )
            if product.id in seen:
                raise ValueError(
                    f"El producto '{product.name}' está cargado dos veces en el mismo ingreso."
                )
            seen.add(product.id)
            try:
                bags = Decimal(str(raw_bags))
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError(
                    f"La cantidad de big bags de '{product.name}' debe ser un número entero."
                ) from None
            if bags != bags.to_integral_value():
                raise ValueError(
                    f"La cantidad de big bags de '{product.name}' debe ser un número entero."
                )
            if bags <= 0:
                raise ValueError(
                    f"La cantidad de big bags de '{product.name}' debe ser mayor a cero."
                )
            weight = cls._unit_weight(product)
            kg = (weight * bags).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            prepared.append((product, int(bags), weight, kg))
        return prepared

    @staticmethod
    def _observations(observations: str):
        return (observations or "").strip() or None

    @classmethod
    def create(cls, *, received_at: date, lines, observations: str = "") -> RawMaterialIntake:
        prepared = cls._lines(lines)
        with RawMaterialIntake._meta.database.atomic():
            intake = RawMaterialIntake.create(
                received_at=received_at, observations=cls._observations(observations)
            )
            cls._write_lines(intake, prepared)
        return intake

    @classmethod
    def update(
        cls, intake: RawMaterialIntake, *, received_at: date, lines, observations: str = ""
    ) -> RawMaterialIntake:
        # El orden importa: un ingreso anulado tambien esta confirmado, y decirle
        # "esta confirmado" manda al operador al motivo equivocado.
        if intake.is_voided:
            raise ValueError("El ingreso está anulado y no se puede editar.")
        if intake.is_confirmed:
            raise ValueError(
                "El ingreso está confirmado: ya entró al stock y no se puede editar. "
                "Anulalo para generar el movimiento contrario."
            )
        prepared = cls._lines(lines)
        with RawMaterialIntake._meta.database.atomic():
            intake.received_at = received_at
            intake.observations = cls._observations(observations)
            intake.save()
            cls._delete_lines(intake)
            cls._write_lines(intake, prepared)
        return intake

    @staticmethod
    def source_ref_of(intake: RawMaterialIntake) -> str:
        """Identidad del ingreso en el libro de stock.

        Es la misma que usa ``StockMovement.source_ref``. Como el libro tiene un
        indice unico sobre esa referencia, un ingreso no puede generar dos veces
        el mismo movimiento: confirmar dos veces no duplica stock.
        """
        return f"{SOURCE_REF_PREFIX}:{intake.id}"

    @classmethod
    def confirm(
        cls, intake: RawMaterialIntake, *, current_user: str | None = None
    ) -> RawMaterialIntake:
        """El operador confirma el ingreso y la materia prima entra al stock.

        Idempotente. Si el ingreso ya esta confirmado devuelve el mismo ingreso
        sin volver a escribir movimientos, gracias al indice unico del libro.
        """
        if intake.is_voided:
            raise ValueError("El ingreso está anulado y no se puede confirmar.")
        if intake.is_confirmed:
            return intake

        lineas = cls.lines_of(intake)
        if not lineas:
            raise ValueError("El ingreso no tiene big bags cargados, no hay nada que confirmar.")

        with RawMaterialIntake._meta.database.atomic():
            intake.confirmed_at = utc_now()
            intake.confirmed_by = (current_user or "").strip() or None
            intake.save()
            for line in lineas:
                StockService.register(
                    product=line.product,
                    movement_type=StockMovement.TYPE_PURCHASE,
                    quantity_kg=line.kg,
                    source_ref=cls.source_ref_of(intake),
                    description=(
                        f"Ingreso de {line.bags} big bag(s) de {line.product.name} "
                        f"del {intake.received_at.isoformat()}"
                    ),
                    movement_date=intake.received_at,
                    created_by=intake.confirmed_by,
                )
        return intake

    @staticmethod
    def _write_lines(intake: RawMaterialIntake, prepared: list[tuple]) -> None:
        for product, bags, weight, kg in prepared:
            RawMaterialIntakeLine.create(
                intake=intake, product=product, bags=bags, unit_weight_kg=weight, kg=kg
            )

    @classmethod
    def annul(
        cls, intake: RawMaterialIntake, *, current_user: str | None = None, reason: str = ""
    ) -> None:
        """Anula el ingreso.

        Un **borrador** se borra: todavia no toco el stock, no hay nada que
        corregir en el libro. Un ingreso **confirmado** ya entró al stock, asi que
        borrarlo desincronizaria el saldo: en ese caso se generan los movimientos
        contrarios y el ingreso queda marcado como anulado, con quien lo hizo y
        por que. Ninguna de las dos cosas reescribe el libro.
        """
        if intake.is_voided:
            raise ValueError("El ingreso ya está anulado.")

        if not intake.is_confirmed:
            RawMaterialIntakeService._delete_lines(intake)
            intake.delete_instance()
            return

        motivo = (reason or "").strip()
        if not motivo:
            raise ValueError("Explicá por qué se anula un ingreso ya confirmado.")

        with RawMaterialIntake._meta.database.atomic():
            movements = StockMovement.select().where(
                (StockMovement.source_ref == cls.source_ref_of(intake))
                & (StockMovement.movement_type == StockMovement.TYPE_PURCHASE)
                & (StockMovement.is_reversal == False)  # noqa: E712
            )
            for movement in list(movements):
                StockService.reverse(movement, created_by=current_user, reason=motivo)
            intake.voided_at = utc_now()
            intake.voided_by = (current_user or "").strip() or None
            intake.void_reason = motivo
            intake.save()

    @staticmethod
    def for_day(day: date):
        return list(
            RawMaterialIntake.select()
            .where(RawMaterialIntake.received_at == day)
            .order_by(RawMaterialIntake.id)
            .prefetch(RawMaterialIntakeLine)
        )

    @staticmethod
    def lines_of(intake: RawMaterialIntake):
        """Lineas del ingreso, tolerando que ``intake.lines`` venga prefetcheado."""
        lineas = intake.lines
        if isinstance(lineas, (list, tuple)):
            return sorted(lineas, key=lambda line: line.id)
        return list(lineas.order_by(RawMaterialIntakeLine.id))

    @staticmethod
    def _delete_lines(intake: RawMaterialIntake) -> None:
        RawMaterialIntakeLine.delete().where(RawMaterialIntakeLine.intake == intake).execute()

    @staticmethod
    def totals(rows) -> IntakeTotals:
        """Totales del dia. Los ingresos anulados no cuentan.

        Se los muestra igual en la tabla para que quede el rastro, pero su
        entrada ya fue revertida en el libro y sumarla volveria a mostrar
        big bags que ya no estan en el stock.
        """
        rows = list(rows)
        lines = 0
        bags = 0
        kg = Decimal("0")
        for row in rows:
            if row.is_voided:
                continue
            for line in RawMaterialIntakeService.lines_of(row):
                lines += 1
                bags += int(line.bags or 0)
                kg += Decimal(str(line.kg or 0))
        return IntakeTotals(len(rows), lines, bags, kg)
