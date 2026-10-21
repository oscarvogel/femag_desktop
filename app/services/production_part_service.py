from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.models.base import utc_now
from app.models.masters import STOCK_ROLE_RAW
from app.models.production import ProductionBag, ProductionConsumption, ProductionPart
from app.models.stock import StockMovement
from app.services.stock_service import StockService

TWO_PLACES = Decimal("0.01")
THREE_PLACES = Decimal("0.001")

SOURCE_REF_PREFIX = "production_part"


@dataclass(frozen=True)
class ProductionTotals:
    parts: int
    lines: int
    bags: int
    kg: Decimal
    consumed_kg: Decimal = Decimal("0")


class ProductionPartService:
    """Registro de produccion real por bolsas embolsadas (#580).

    En planta no se pueden medir los kg de mandioca procesada ni los kg de
    fecula producida por turno, asi que el parte carga cuantas bolsas de cada
    producto se embolsaron y deriva los kg del peso del producto.
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
                "Cargalo en el maestro de productos antes de registrar bolsas: "
                "sin ese peso no se pueden calcular los kg."
            )
        return weight.quantize(THREE_PLACES, rounding=ROUND_HALF_UP)

    @classmethod
    def _lines(cls, lines) -> list[tuple]:
        lines = list(lines or [])
        if not lines:
            raise ValueError("Cargá al menos un producto embolsado en el turno.")
        prepared = []
        seen: set[int] = set()
        for product, raw_bags in lines:
            if product is None:
                raise ValueError("Cada línea necesita un producto.")
            if product.id in seen:
                raise ValueError(
                    f"El producto '{product.name}' está cargado dos veces en el mismo turno."
                )
            seen.add(product.id)
            try:
                bags = Decimal(str(raw_bags))
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError(
                    f"La cantidad de bolsas de '{product.name}' debe ser un número entero."
                ) from None
            if bags != bags.to_integral_value():
                raise ValueError(
                    f"La cantidad de bolsas de '{product.name}' debe ser un número entero."
                )
            if bags <= 0:
                raise ValueError(
                    f"La cantidad de bolsas de '{product.name}' debe ser mayor a cero."
                )
            weight = cls._unit_weight(product)
            kg = (weight * bags).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            prepared.append((product, int(bags), weight, kg))
        return prepared

    @classmethod
    def _consumptions(cls, consumptions) -> list[tuple]:
        """Materia prima que consume el turno, en kilos.

        A diferencia del ingreso (#656), que se cuenta en big bags, el consumo
        se mide en kilos: un big bag abierto se puede terminar en otro turno,
        asi que el big bag no es la unidad real de consumo (decision del
        operador, 2026-10-20).
        """
        consumptions = list(consumptions or [])
        if not consumptions:
            raise ValueError(
                "Cargá la materia prima que consumió el turno: sin eso las bolsas "
                "entran al stock y el almidón nunca sale."
            )
        prepared = []
        seen: set[int] = set()
        for product, raw_kg in consumptions:
            if product is None:
                raise ValueError("Cada línea de consumo necesita un producto.")
            if product.id in seen:
                raise ValueError(
                    f"La materia prima '{product.name}' está cargada dos veces en el mismo turno."
                )
            seen.add(product.id)
            if product.stock_role != STOCK_ROLE_RAW:
                raise ValueError(
                    f"'{product.name}' no es materia prima. Solo se consume material con "
                    "Rol en el stock = Materia prima."
                )
            try:
                kg = Decimal(str(raw_kg))
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError(
                    f"Los kilos consumidos de '{product.name}' deben ser un número."
                ) from None
            if kg <= 0:
                raise ValueError(
                    f"Los kilos consumidos de '{product.name}' deben ser mayores a cero."
                )
            prepared.append((product, kg.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)))
        return prepared

    @staticmethod
    def _values(*, shift: str, observations: str = "", recorded_by: str | None = None):
        shift = (shift or "").strip()
        if not shift:
            raise ValueError("El turno es obligatorio.")
        recorded_by = (recorded_by or "").strip() or None
        return shift, (observations or "").strip() or None, recorded_by

    @classmethod
    def create(
        cls, *, production_date: date, shift: str, lines, consumptions=(), observations: str = "",
        recorded_by: str | None = None,
    ) -> ProductionPart:
        shift, observations, recorded_by = cls._values(
            shift=shift, observations=observations, recorded_by=recorded_by
        )
        prepared = cls._lines(lines)
        prepared_consumptions = cls._consumptions(consumptions)
        with ProductionPart._meta.database.atomic():
            part = ProductionPart.create(
                production_date=production_date,
                shift=shift,
                observations=observations,
                recorded_by=recorded_by,
            )
            cls._write_lines(part, prepared)
            cls._write_consumptions(part, prepared_consumptions)
        return part

    @classmethod
    def update(
        cls, part: ProductionPart, *, production_date: date, shift: str, lines,
        consumptions=(), observations: str = "", recorded_by: str | None = None,
    ) -> ProductionPart:
        # El orden importa: un parte anulado tambien esta confirmado, y decirle
        # "esta confirmado" manda al operador al motivo equivocado.
        if part.is_voided:
            raise ValueError("El parte está anulado y no se puede editar.")
        if part.is_confirmed:
            raise ValueError(
                "El parte está confirmado: ya entró al stock y no se puede editar. "
                "Anulalo para generar el movimiento contrario."
            )
        shift, observations, recorded_by = cls._values(
            shift=shift, observations=observations, recorded_by=recorded_by
        )
        prepared = cls._lines(lines)
        prepared_consumptions = cls._consumptions(consumptions)
        with ProductionPart._meta.database.atomic():
            part.production_date = production_date
            part.shift = shift
            part.observations = observations
            part.recorded_by = recorded_by
            part.save()
            cls._delete_lines(part)
            cls._write_lines(part, prepared)
            cls._write_consumptions(part, prepared_consumptions)
        return part

    @staticmethod
    def source_ref_of(part: ProductionPart) -> str:
        """Identidad del parte en el libro de stock.

        Es la misma que usa ``StockMovement.source_ref``. Como el libro tiene un
        indice unico sobre esa referencia, un parte no puede generar dos veces el
        mismo movimiento: confirmar dos veces no duplica stock.
        """
        return f"{SOURCE_REF_PREFIX}:{part.id}"

    @classmethod
    def confirm(cls, part: ProductionPart, *, current_user: str | None = None) -> ProductionPart:
        """El operador confirma el turno: la produccion entra al stock y la
        materia prima consumida sale.

        Idempotente. Si el parte ya esta confirmado devuelve el mismo parte sin
        volver a escribir movimientos, gracias al indice unico del libro.

        Antes de escribir nada se verifica que haya materia prima suficiente
        (#730): no se puede producir material que no se compro. Si no alcanza,
        la confirmacion se bloquea y el stock no se toca.
        """
        if part.is_voided:
            raise ValueError("El parte está anulado y no se puede confirmar.")
        if part.is_confirmed:
            return part

        lineas = cls.lines_of(part)
        if not lineas:
            raise ValueError("El parte no tiene bolsas cargadas, no hay nada que confirmar.")

        consumos = cls.consumptions_of(part)
        if not consumos:
            raise ValueError(
                "El parte no tiene materia prima consumida, no se puede confirmar: "
                "las bolsas entrarían al stock y el almidón no saldría."
            )

        with ProductionPart._meta.database.atomic():
            # El control va adentro de la transaccion y antes de escribir
            # cualquier movimiento: si el material no alcanza, no se toca el
            # libro y el parte queda como borrador.
            cls._verificar_stock_disponible(consumos)
            part.confirmed_at = utc_now()
            part.confirmed_by = (current_user or "").strip() or None
            part.save()
            for bag in lineas:
                StockService.register(
                    product=bag.product,
                    movement_type=StockMovement.TYPE_PRODUCTION,
                    quantity_kg=bag.kg,
                    source_ref=cls.source_ref_of(part),
                    description=(
                        f"Producción del {part.production_date.isoformat()} "
                        f"turno {part.shift}"
                    ),
                    movement_date=part.production_date,
                    created_by=part.confirmed_by,
                )
            for consumo in consumos:
                StockService.register(
                    product=consumo.product,
                    movement_type=StockMovement.TYPE_PRODUCTION_CONSUMPTION,
                    quantity_kg=consumo.kg,
                    source_ref=cls.source_ref_of(part),
                    description=(
                        f"Consumo de {consumo.product.name} del "
                        f"{part.production_date.isoformat()} turno {part.shift}"
                    ),
                    movement_date=part.production_date,
                    created_by=part.confirmed_by,
                )
        return part

    @staticmethod
    def _verificar_stock_disponible(consumos) -> None:
        """Bloquea la confirmacion si la materia prima no alcanza (#730).

        El disponible sale del libro de movimientos, asi que ya descuenta lo que
        consumieron los partes confirmados anteriores. La comprobacion es por
        producto: cada linea se compara contra el saldo de su propia materia
        prima.
        """
        for consumo in consumos:
            disponible = StockService.balance_for(consumo.product).balance_kg
            if disponible < consumo.kg:
                raise ValueError(
                    f"No hay materia prima suficiente para confirmar: de "
                    f"«{consumo.product.name}» hay {disponible:,.3f} kg en stock y el "
                    f"parte consume {consumo.kg:,.3f} kg. Registrá la compra del big "
                    "bag (Producción > Ingreso de materia prima) o el inventario "
                    "inicial antes de confirmar."
                )

    @staticmethod
    def _write_lines(part: ProductionPart, prepared: list[tuple]) -> None:
        for product, bags, weight, kg in prepared:
            ProductionBag.create(
                part=part, product=product, bags=bags, unit_weight_kg=weight, kg=kg
            )

    @staticmethod
    def _write_consumptions(part: ProductionPart, prepared: list[tuple]) -> None:
        for product, kg in prepared:
            ProductionConsumption.create(part=part, product=product, kg=kg)

    @classmethod
    def annul(
        cls, part: ProductionPart, *, current_user: str | None = None, reason: str = ""
    ) -> None:
        """Anula el parte.

        Un **borrador** se borra: todavia no toco el stock, no hay nada que
        corregir en el libro. Un parte **confirmado** ya entró al stock, asi que
        borrarlo desincronizaria el saldo: en ese caso se generan los movimientos
        contrarios y el parte queda marcado como anulado, con quien lo hizo y por
        que. Ninguna de las dos cosas reescribe el libro.
        """
        if part.is_voided:
            raise ValueError("El parte ya está anulado.")

        if not part.is_confirmed:
            ProductionPartService._delete_lines(part)
            part.delete_instance()
            return

        motivo = (reason or "").strip()
        if not motivo:
            raise ValueError("Explicá por qué se anula un parte ya confirmado.")

        with ProductionPart._meta.database.atomic():
            # Se revierten los dos movimientos del parte: las bolsas que
            # entraron y la materia prima que salio. Anular solo uno dejaria el
            # stock desbalanceado (#730).
            movements = StockMovement.select().where(
                (StockMovement.source_ref == cls.source_ref_of(part))
                & (
                    (StockMovement.movement_type == StockMovement.TYPE_PRODUCTION)
                    | (
                        StockMovement.movement_type
                        == StockMovement.TYPE_PRODUCTION_CONSUMPTION
                    )
                )
                & (StockMovement.is_reversal == False)  # noqa: E712
            )
            for movement in list(movements):
                StockService.reverse(movement, created_by=current_user, reason=motivo)
            part.voided_at = utc_now()
            part.voided_by = (current_user or "").strip() or None
            part.void_reason = motivo
            part.save()

    @staticmethod
    def for_day(day: date):
        return list(
            ProductionPart.select()
            .where(ProductionPart.production_date == day)
            .order_by(ProductionPart.id)
            .prefetch(ProductionBag, ProductionConsumption)
        )

    @staticmethod
    def lines_of(part: ProductionPart):
        """Lineas del parte, tolerando que ``part.bags`` venga prefetcheado."""
        bags = part.bags
        if isinstance(bags, (list, tuple)):
            return sorted(bags, key=lambda bag: bag.id)
        return list(bags.order_by(ProductionBag.id))

    @staticmethod
    def consumptions_of(part: ProductionPart):
        """Materia prima consumida por el parte, tolerando prefetch."""
        consumptions = part.consumptions
        if isinstance(consumptions, (list, tuple)):
            return sorted(consumptions, key=lambda consumo: consumo.id)
        return list(consumptions.order_by(ProductionConsumption.id))

    @staticmethod
    def _delete_lines(part: ProductionPart) -> None:
        ProductionBag.delete().where(ProductionBag.part == part).execute()
        # El borrado explicito importa: en SQLite las claves foraneas no estan
        # activas por defecto, asi que la cascada de la base no siempre corre y
        # las lineas de consumo podrian quedar colgando de un parte borrado.
        ProductionConsumption.delete().where(ProductionConsumption.part == part).execute()

    @staticmethod
    def totals(rows) -> ProductionTotals:
        """Totales del dia. Los partes anulados no cuentan.

        Se los muestra igual en la tabla para que quede el rastro, pero su
        produccion ya fue revertida en el libro y sumarla volveria a mostrar
        kg que no existen.
        """
        rows = list(rows)
        lines = 0
        bags = 0
        kg = Decimal("0")
        consumed_kg = Decimal("0")
        for row in rows:
            if row.is_voided:
                continue
            for bag in ProductionPartService.lines_of(row):
                lines += 1
                bags += int(bag.bags or 0)
                kg += Decimal(str(bag.kg or 0))
            for consumo in ProductionPartService.consumptions_of(row):
                consumed_kg += Decimal(str(consumo.kg or 0))
        return ProductionTotals(len(rows), lines, bags, kg, consumed_kg)
