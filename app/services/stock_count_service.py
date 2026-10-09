from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.masters import PRODUCT_KIND_PRODUCT, Product
from app.models.stock import StockMovement
from app.models.stock_count import StockCount, StockCountLine
from app.services.audit_service import AuditService
from app.models.base import utc_now
from app.services.stock_service import StockService, is_countable_in_bags

ZERO = Decimal("0.000")


class StockCountError(ValueError):
    pass


def _kg(valor: Decimal) -> str:
    """Kilos como se leen aca: punto de miles y coma decimal.

    ``format`` de Python separa miles con coma y decimales con punto, que
    es al reves de como se escriben los numeros aca. Se usa "X" de marcador
    para que los reemplazos no se pisen entre si.
    """
    return f"{valor:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")


def count_source_prefix(line_id: int) -> str:
    """Prefijo del movimiento de ajuste de una linea de conteo.

    Va por la linea y no por la sesion: cada linea es una diferencia propia y
    una sesion puede tener varias. El indice unico de ``StockMovement`` hace que
    cerrar dos veces la misma linea no duplique el ajuste.
    """
    return f"StockCountLine:{line_id}:Adjustment"


class StockCountService:
    """Conteo fisico y ajustes auditables (#574).

    El conteo **nunca** reescribe movimientos: lo que hace es agregar el
    movimiento de ajuste que lleva el saldo del libro a la realidad contada. El
    libro queda mostrando la foto completa -lo que entro, lo que salio, lo que
    se devolvio y lo que se conto- en vez de un saldo forzado.

    Decidido con el owner: el conteo es **por producto**. El "lote" que menciona
    el issue no aplica: en ``femagfab`` la tabla ``lote`` es un registro de
    analisis de laboratorio (aerobios, levaduras, coliformes, humedad, pH), no
    un lote de stock, y en FEMAG el concepto no existe.
    """

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    # ------------------------------------------------------------------ conteo

    def open_count(
        self, count_date: date, *, notes: str | None = None
    ) -> StockCount:
        """Abre una sesion de conteo para esa fecha."""
        if count_date is None:
            raise StockCountError("Indicá la fecha del conteo.")
        abierta = StockCount.get_or_none(
            (StockCount.count_date == count_date) & (StockCount.status == StockCount.STATUS_OPEN)
        )
        if abierta is not None:
            return abierta
        return StockCount.create(
            count_date=count_date,
            counted_by=(self.current_user or "").strip() or None,
            notes=(notes or "").strip() or None,
        )

    def countable_products(self) -> list[Product]:
        """Productos que se pueden contar: los de venta activos.

        Acá NO se filtran los que no tienen peso de bolsa: la pantalla los
        muestra igual, bloqueados y con el motivo, para que el operador entienda
        que le falta cargar el dato en Productos en vez de preguntarse por que
        el producto no aparece. El filtro real esta en
        :meth:`is_countable_in_bags`, y el servicio igual se niega a contar en
        bolsas un producto sin peso.
        """
        return list(
            Product.select()
            .where((Product.active == True) & (Product.product_kind == PRODUCT_KIND_PRODUCT))  # noqa: E712
            .order_by(Product.name)
        )

    @staticmethod
    def is_countable_in_bags(product) -> bool:
        """Si el producto se puede contar en bolsas.

        Delega en :func:`app.services.stock_service.is_countable_in_bags`, que es
        la regla compartida: Inventario inicial cuenta en bolsas tambien (#651) y
        las dos pantallas tienen que decidir igual. Un producto sin
        ``peso_unitario_kg`` cargado **no** se puede contar en bolsas: los kilos
        se derivan multiplicando por el peso, asi que con peso cero N bolsas
        equivalen a 0 kg y el conteo generaria un ajuste que lleva el saldo del
        libro a cero.
        """
        return is_countable_in_bags(product)

    def add_line(
        self, count: StockCount, product, counted_units, *, reason: str | None = None
    ) -> StockCountLine:
        """Agrega un producto al conteo.

        ``counted_units`` son **bolsas**, no kilos: el operador cuenta lo que ve
        en el deposito. Los kilos se derivan con el peso de bolsa del producto,
        igual que en la pantalla de partes de produccion. Pedirle kilos seria
        volver a poner la cuenta manual en el operador.

        La copia del saldo del libro y del peso usados es **del momento de
        agregar la linea**, no del cierre. Es lo que permitio que el operador
        viera: si despues se emite una orden, el ajuste no se va a enterar de un
        cambio que no es del conteo.
        """
        self._require_open(count)
        if product is None or getattr(product, "id", None) is None:
            raise StockCountError("Seleccione un producto del conteo.")
        try:
            unidades = Decimal(str(counted_units or 0))
        except (TypeError, ValueError, ArithmeticError):
            raise StockCountError("La cantidad contada debe ser un número.") from None
        if unidades < ZERO:
            raise StockCountError("La cantidad contada no puede ser negativa.")
        unidades = unidades.quantize(Decimal("0.001"))

        peso = Decimal(str(product.peso_unitario_kg or 0))
        if peso <= ZERO:
            # Sin peso de bolsa, N bolsas darían 0 kg y la diferencia contra el
            # libro sería -saldo: al cerrar el conteo se generaría un ajuste que
            # deja el producto en cero. Es pérdida de inventario silenciosa, así
            # que acá se corta y se dice qué dato falta y dónde cargarlo.
            raise StockCountError(
                f"{product.name} no tiene peso de bolsa cargado, así que no se "
                "puede contar en bolsas. Cargá el peso de bolsa del producto en "
                "Productos y volvé a contar."
            )
        kilos = (unidades * peso).quantize(Decimal("0.001"))
        calculada = StockService.balance_for(product).balance_kg

        linea, creada = StockCountLine.get_or_create(
            count=count,
            product=product,
            defaults={
                "calculated_kg": calculada,
                "counted_units": unidades,
                "unit_weight_kg": peso,
                "counted_kg": kilos,
                "reason": (reason or "").strip() or None,
            },
        )
        if not creada:
            # Volver a cargar el mismo producto actualiza lo contado, pero no
            # recalcula contra el libro: el operador ya lo vio una vez.
            linea.counted_units = unidades
            linea.unit_weight_kg = peso
            linea.counted_kg = kilos
            linea.reason = (reason or "").strip() or linea.reason
            linea.save()
        return linea

    def remove_line(self, count: StockCount, line: StockCountLine) -> None:
        """Saca un producto del conteo antes de cerrarlo.

        Saco la linea, no ajusto: un producto que no se conto no genera
        movimiento. Ajustar a cero lo que no se conto seria la peor forma de
        romper un inventario.
        """
        self._require_open(count)
        if line is None or line.id is None or line.count_id != count.id:
            raise StockCountError("La línea no pertenece a este conteo.")
        line.delete_instance()

    # ------------------------------------------------------------------ cierre

    def close_count(self, count: StockCount) -> list[StockMovement]:
        """Cierra el conteo y genera los ajustes de las lineas que difieren.

        Idempotente: el indice unico de ``StockMovement`` sobre la linea impide
        que cerrar dos veces duplique los ajustes.
        """
        count = self._require_open(count)
        movimientos: list[StockMovement] = []

        with StockCount._meta.database.atomic():
            for linea in list(count.lines.order_by(StockCountLine.id)):
                if not linea.has_difference:
                    continue
                diferencia = linea.difference_kg
                tipo = (
                    StockMovement.TYPE_ADJUSTMENT_POSITIVE
                    if diferencia > ZERO
                    else StockMovement.TYPE_ADJUSTMENT_NEGATIVE
                )
                movimientos.append(
                    StockService.register(
                        product=linea.product,
                        movement_type=tipo,
                        quantity_kg=abs(diferencia),
                        source_ref=f"{count_source_prefix(linea.id)}",
                        description=(
                            f"Conteo físico del {count.count_date:%d/%m/%Y}: "
                            f"libro {_kg(linea.calculated_kg)} kg, "
                            f"contadas {_kg(linea.counted_units)} bolsa(s) "
                            f"de {_kg(linea.unit_weight_kg)} kg "
                            f"= {_kg(linea.counted_kg)} kg"
                        ),
                        movement_date=count.count_date,
                        observations=(linea.reason or "").strip() or None,
                        created_by=self.current_user,
                    )
                )

            count.status = StockCount.STATUS_CLOSED
            count.closed_at = utc_now()
            count.closed_by = (self.current_user or "").strip() or None
            count.save()

        if movimientos:
            self.audit_service.record(
                user=self.current_user,
                module="Stock",
                action="cerrar_conteo_fisico",
                record_ref=f"StockCount:{count.id}",
                new_value={
                    "count_date": count.count_date.isoformat(),
                    "movement_ids": [m.id for m in movimientos],
                    "kg_ajustado": str(sum(m.quantity_kg for m in movimientos)),
                },
            )
        return movimientos

    def _require_open(self, count: StockCount) -> StockCount:
        if count is None or not isinstance(count, StockCount) or count.id is None:
            raise StockCountError("Seleccione un conteo válido.")
        count = StockCount.get_by_id(count.id)
        if not count.is_open:
            raise StockCountError("El conteo ya está cerrado.")
        return count

    # ----------------------------------------------------------------- lectura

    @staticmethod
    def differences(count: StockCount) -> list[StockCountLine]:
        """Solo las lineas que difieren, que son las que generan ajuste."""
        return [linea for linea in count.lines.order_by(StockCountLine.id) if linea.has_difference]
