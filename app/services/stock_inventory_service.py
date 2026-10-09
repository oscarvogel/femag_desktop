from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.masters import PRODUCT_KIND_PRODUCT, Product
from app.models.stock import StockMovement
from app.services.stock_service import StockService

ZERO = Decimal("0.000")
SOURCE_PREFIX = "stock_take"


class StockInventoryError(ValueError):
    """Error de carga del inventario inicial."""


def source_ref_of(day: date) -> str:
    """Identidad del conteo en el libro.

    Un conteo por fecha: cargar dos veces el mismo dia tiene que devolver los
    mismos movimientos, y el indice unico de ``StockMovement`` lo garantiza. Por
    eso despues el servicio **rechaza** una segunda carga en vez de pisar: el
    indice evita el duplicado, pero solo un error explicito evita que el operador
    crea que cambio algo y no cambie nada.
    """
    return f"{SOURCE_PREFIX}:{day.isoformat()}"


class StockInventoryService:
    """Carga del inventario inicial: el punto de partida del libro.

    Es la unica vez que se define de cuanto stock arranca la planta. Despues el
    saldo se deriva solo de los movimientos: entra produccion, sale despacho.

    Las 38 ordenes cerradas que ya existen en el sistema **no** se cargan. Se
    arranca con un conteo real en una fecha de corte, que es lo unico que hace
    que el saldo del primer dia sea un numero y no una operacion matematica
    sobre un saldo de arranque inventado.
    """

    @staticmethod
    def countable_products() -> list[Product]:
        """Productos que se pueden contar.

        Solo los de venta activos: un servicio, un interno o un articulo en
        revision no se stockea. Se incluye a los que no tienen peso de bolsa
        cargado porque un conteo se cuenta en kilos, no en bolsas.
        """
        return list(
            Product.select()
            .where((Product.active == True) & (Product.product_kind == PRODUCT_KIND_PRODUCT))  # noqa: E712
            .order_by(Product.name)
        )

    @staticmethod
    def initial_movements_of(day: date) -> list[StockMovement]:
        return list(
            StockMovement.select()
            .where(
                (StockMovement.source_ref == source_ref_of(day))
                & (StockMovement.movement_type == StockMovement.TYPE_INITIAL_INVENTORY)
            )
            .order_by(StockMovement.product_id)
        )

    @classmethod
    def has_initial(cls, day: date) -> bool:
        return bool(cls.initial_movements_of(day))

    @classmethod
    def initial_quantities(cls, day: date) -> dict[int, Decimal]:
        return {
            movimiento.product_id: Decimal(str(movimiento.quantity_kg or 0))
            for movimiento in cls.initial_movements_of(day)
        }

    @classmethod
    def load_initial(
        cls,
        day: date,
        quantities: dict,
        *,
        current_user: str | None = None,
        observations: str | None = None,
    ) -> list[StockMovement]:
        """Carga el conteo de ``day``.

        ``quantities`` mapea **id de producto** a kilos. Se-keys por id y no por
        objeto a proposito: la pantalla de conteo tiene los ids, y un id es un
        primitivo que no se puede desincronizar del registro de la base como
        pasa con una instancia de peewee guardada en un diccionario.

        Las filas en cero se omiten: un movimiento de 0 kg no dice nada y
        ensucia el libro.
        """
        if day is None:
            raise StockInventoryError("Indicá la fecha del conteo.")

        ya_cargados = cls.initial_movements_of(day)
        if ya_cargados:
            nombres = ", ".join(
                sorted({movimiento.product.name for movimiento in ya_cargados})
            )
            raise StockInventoryError(
                f"El {day:%d/%m/%Y} ya tiene inventario inicial cargado "
                f"({len(ya_cargados)} producto(s): {nombres}). "
                "Si el conteo estaba mal, anulalo primero y volvé a cargarlo: "
                "cargar dos veces no reemplaza nada."
            )

        movimientos = []
        with StockMovement._meta.database.atomic():
            for producto_id, kilos in sorted(quantities.items()):
                try:
                    producto = Product.get_by_id(producto_id)
                except (Product.DoesNotExist, TypeError, ValueError):
                    raise StockInventoryError(
                        f"El producto {producto_id} no existe."
                    ) from None
                cantidad = Decimal(str(kilos or 0))
                if cantidad <= ZERO:
                    continue
                movimientos.append(
                    StockService.register(
                        product=producto,
                        movement_type=StockMovement.TYPE_INITIAL_INVENTORY,
                        quantity_kg=cantidad,
                        source_ref=source_ref_of(day),
                        description=f"Inventario inicial al {day:%d/%m/%Y}",
                        movement_date=day,
                        observations=(observations or "").strip() or None,
                        created_by=current_user,
                    )
                )
        return movimientos

    @classmethod
    def is_voided(cls, day: date) -> bool:
        """El conteo de ``day`` existe pero ya fue anulado.

        Sin esto, anular dos veces no falla: ``StockService.reverse`` es
        idempotente y devolveria la reversa que ya existe, en vez de avisar que
        ese conteo ya no esta vigente.
        """
        iniciales = cls.initial_movements_of(day)
        if not iniciales:
            return False
        ids = [movimiento.id for movimiento in iniciales]
        return StockMovement.select().where(
            (StockMovement.reverses << ids) & (StockMovement.is_reversal == True)  # noqa: E712
        ).exists()

    @classmethod
    def reverse_initial(
        cls, day: date, *, current_user: str | None = None, reason: str
    ) -> list[StockMovement]:
        """Anula el conteo de ``day`` generando los movimientos contrarios.

        No borra nada: el conteo queda en el libro con su reversa, que es lo que
        permite auditar por que se cambio el punto de partida.
        """
        motivo = (reason or "").strip()
        if not motivo:
            raise StockInventoryError("Explicá por qué se anula el inventario inicial.")

        if cls.is_voided(day):
            raise StockInventoryError(
                f"El inventario inicial del {day:%d/%m/%Y} ya está anulado."
            )

        ya_cargados = cls.initial_movements_of(day)
        if not ya_cargados:
            raise StockInventoryError(f"El {day:%d/%m/%Y} no tiene inventario inicial cargado.")

        reversas = []
        for movimiento in ya_cargados:
            reversas.append(
                StockService.reverse(movimiento, created_by=current_user, reason=motivo)
            )
        return reversas
