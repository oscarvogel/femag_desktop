"""Puente entre la webapp movil y el servicio de partes de produccion (#754).

La regla del circuito no cambia: se reutiliza tal cual
``app.services.production_part_service.ProductionPartService``, que ya es
transaccional, idempotente y escribe los movimientos del libro de stock.

Lo que aporta la webapp es **donde** se carga: desde el celular de la planta,
con la persona que embolo identificada. Por eso cada parte guarda
``recorded_by`` y no solo ``confirmed_by``.
"""

from __future__ import annotations

from datetime import date, datetime

from app.models.masters import PRODUCT_KIND_PRODUCT, STOCK_ROLE_RAW, Product
from app.models.production import ProductionPart
from app.services.production_part_service import ProductionPartService
from app.services.stock_service import StockService

#: Turnos de la planta. Son los mismos que ofrece la pantalla de escritorio
#: (``app.ui.production_parts``): "Mañana", "Tarde" y "Noche".
SHIFTS = ("Mañana", "Tarde", "Noche")

#: Cuantas filas de cada tipo trae el formulario. Es un limite de pantalla, no
#: de modelo: un turno con mas productos se carga en mas de un parte.
BAG_ROWS = 6
CONSUMPTION_ROWS = 4


def products_for_bags():
    """Productos terminados que se pueden embolsar.

    Mismo criterio que la pantalla de escritorio: activo, con peso de bolsa
    cargado y de kind producto. Un producto sin peso no se puede convertir a
    kilos, asi que no tiene sentido ofrecerlo.

    La materia prima queda **fuera**: si un mismo producto se pudiera embolsar
    y además consumirse, el mismo kilo entraria y saldría del stock en el
    mismo parte, y el saldo quedaria falseado.

    El filtro es NULL-safe: en SQL, ``stock_role != 'materia_prima'`` es NULL
    (y por lo tanto excluye la fila) cuando ``stock_role`` es NULL. Un producto
    sin rol cargado tiene que seguir apareciendo como embolsable.
    """
    return list(
        Product.select()
        .where(
            (Product.active == True)  # noqa: E712
            & (Product.peso_unitario_kg > 0)
            & (Product.product_kind == PRODUCT_KIND_PRODUCT)
            & (
                (Product.stock_role != STOCK_ROLE_RAW)
                | (Product.stock_role.is_null())
            )
        )
        .order_by(Product.name)
    )


def raw_materials():
    """Materias primas que el turno puede consumir.

    Mismo filtro que la pantalla de escritorio: activo, con peso cargado y con
    rol de stock "Materia prima".
    """
    return list(
        Product.select()
        .where(
            (Product.active == True)  # noqa: E712
            & (Product.peso_unitario_kg > 0)
            & (Product.stock_role == STOCK_ROLE_RAW)
        )
        .order_by(Product.name)
    )


def available_kg(product) -> float:
    """Disponible en el libro de movimientos, en kilos.

    Ya descuenta lo que consumieron los partes confirmados anteriores, asi que
    es el numero contra el que la confirmacion va a bloquear si no alcanza.
    """
    if product is None:
        return 0.0
    return float(StockService.balance_for(product).balance_kg)


def _int_or_none(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def kg_text(value, decimals: int = 2) -> str:
    """Kilos como se leen aca: punto de miles y coma decimal.

    ``format`` de Python separa miles con coma y decimales con punto, que al
    reves de como se escriben los numeros aca. Se usa "X" de marcador para
    que los reemplazos no se pisen entre si. Es el mismo criterio que usa
    ``app.services.stock_count_service``.
    """
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    text = f"{amount:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def parse_bag_lines(form, products_by_id):
    """Lineas de bolsas del formulario: ``(producto, cantidad de bolsas)``.

    Las filas sin producto o sin cantidad se ignoran: el operador carga solo
    las que usa y las demas quedan vacias.
    """
    lines = []
    for index in range(BAG_ROWS):
        product_id = _int_or_none(form.get(f"product_{index}"))
        product = products_by_id.get(product_id) if product_id else None
        raw = (form.get(f"bags_{index}") or "").strip()
        if product is None or not raw:
            continue
        lines.append((product, raw))
    return lines


def parse_consumptions(form, raw_materials_by_id):
    """Consumo de materia prima del formulario: ``(producto, kilos)``."""
    consumptions = []
    for index in range(CONSUMPTION_ROWS):
        product_id = _int_or_none(form.get(f"materia_{index}"))
        product = raw_materials_by_id.get(product_id) if product_id else None
        raw = (form.get(f"kg_{index}") or "").strip()
        if product is None or not raw:
            continue
        consumptions.append((product, raw))
    return consumptions


def parse_date(raw: str | None) -> date:
    raw = (raw or "").strip()
    if not raw:
        return date.today()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return date.today()


def create_part(*, production_date, shift, lines, consumptions, observations, recorded_by):
    return ProductionPartService.create(
        production_date=production_date,
        shift=shift,
        lines=lines,
        consumptions=consumptions,
        observations=observations,
        recorded_by=recorded_by,
    )


def confirm_part(part, *, current_user):
    return ProductionPartService.confirm(part, current_user=current_user)


def annul_part(part, *, current_user, reason):
    ProductionPartService.annul(part, current_user=current_user, reason=reason)


def parts_for_day(day):
    return ProductionPartService.for_day(day)


def lines_of(part):
    return ProductionPartService.lines_of(part)


def consumptions_of(part):
    return ProductionPartService.consumptions_of(part)


def combo_options(products, *, sufijo=None):
    """Opciones para el combo con busqueda.

    Cada opcion lleva la etiqueta que ve el operador y un detalle, para que
    se pueda distinguir de un vistazo sin abrir la lista. ``sufijo`` arma ese
    detalle; por defecto es el peso de bolsa.
    """
    opciones = []
    for product in products:
        detalle = (
            f"{product.peso_unitario_kg} kg c/u"
            if sufijo is None
            else sufijo(product)
        )
        opciones.append(
            {
                "id": product.id,
                "nombre": product.name,
                "etiqueta": f"{product.name} · {detalle}",
            }
        )
    return opciones


def combo_labels(options):
    """Mapa id -> etiqueta, para repintar la seleccion cuando se vuelve a cargar."""
    return {str(option["id"]): option["etiqueta"] for option in options}


def totals(rows):
    return ProductionPartService.totals(rows)


def part_by_id(part_id):
    return ProductionPart.get_or_none(ProductionPart.id == part_id)
