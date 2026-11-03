"""Carga de lotes por linea de despacho en la ficha web de la orden (#873).

La ficha no pide el lote pallet por pallet: pide la linea de despacho (producto +
cliente + destino) y, dentro de la linea, uno o mas grupos de pallets que
comparten lote y fecha. La fecha de elaboracion pertenece al lote, asi que se
escribe una vez por grupo y no una vez por pallet.

La captura es del celular. El escritorio no captura: recibe los cambios por
sync y los muestra en la hoja de despacho y en el informe de trazabilidad.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import date

# Slot de la mercaderia suelta: no tiene numero de pallet, pero tambien lleva
# su propio lote y sus propias fechas.
LOOSE_SLOT = "S"

# Techo de grupos por linea. Es una red de seguridad: la pantalla deja agregar
# grupos hasta este numero, y mas alla se avisa en lugar de cortar el guardado.
MAX_GROUPS = 8


@dataclass(frozen=True)
class LoadContent:
    """Un contenido de pallet (o mercaderia suelta) dentro de una linea."""

    id: str
    kind: str
    slot: str
    slot_label: str
    pallet_sequence: int | None
    product: str
    quantity: float
    unit: str
    lote: str | None = None
    fecha_elaboracion: date | None = None
    fecha_envasado: date | None = None


@dataclass(frozen=True)
class LoadGroup:
    """Grupo de pallets de una linea que comparten lote y fecha."""

    index: int
    lote: str = ""
    fecha_elaboracion: str = ""
    fecha_envasado: str = ""
    slots: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoadLine:
    """Linea de despacho a cargar: producto + cliente + destino."""

    key: str
    product: str
    client: str
    destination: str
    quantity: float
    unit: str
    contents: tuple[LoadContent, ...] = ()
    groups: tuple[LoadGroup, ...] = ()
    line_id: int | None = None
    line_uid: str | None = None

    @property
    def slots(self) -> tuple[str, ...]:
        return tuple(content.slot for content in self.contents)

    @property
    def slot_labels(self) -> dict[str, str]:
        return {content.slot: content.slot_label for content in self.contents}

    @property
    def content_by_slot(self) -> dict[str, LoadContent]:
        return {content.slot: content for content in self.contents}


def fallback_key(product: str, client: str, destination: str) -> str:
    """Clave estable para agrupar contenidos sin ``line_uid`` publicado.

    Se usa un hash y no el texto crudo porque la clave va al nombre de los
    campos del formulario y no puede traer espacios ni acentos.
    """

    raw = f"{product}|{client}|{destination}".encode("utf-8")
    return "g" + hashlib.sha1(raw).hexdigest()[:12]


def _iso(value: date | None) -> str:
    return value.isoformat() if value else ""


def build_groups(
    contents: tuple[LoadContent, ...],
    line_values: tuple[str, str, str] | None = None,
) -> tuple[LoadGroup, ...]:
    """Arma los grupos iniciales de una linea a partir de lo ya cargado.

    Los contenidos que comparten lote y fechas quedan en el mismo grupo. Los que
    todavia no tienen lote van a un grupo vacio al final, que es donde el
    operador carga el lote nuevo.

    ``line_values`` son el lote y las fechas de la linea de despacho. Se usan
    solo cuando ningun contenido trae lote: en ese caso la linea tiene el dato
    cargado y los pallets todavia no, y el operador tiene que verlo.
    """

    groups: list[dict] = []
    index_by_key: dict[tuple[str, str, str], int] = {}
    pending: list[str] = []

    for content in contents:
        lote = (content.lote or "").strip()
        if not lote:
            pending.append(content.slot)
            continue
        key = (lote, _iso(content.fecha_elaboracion), _iso(content.fecha_envasado))
        position = index_by_key.get(key)
        if position is None:
            position = len(groups)
            index_by_key[key] = position
            groups.append(
                {
                    "lote": key[0],
                    "fecha_elaboracion": key[1],
                    "fecha_envasado": key[2],
                    "slots": [],
                }
            )
        groups[position]["slots"].append(content.slot)

    if pending or not groups:
        # Siempre hay un grupo donde cargar: si la linea todavia no tiene nada
        # cargado, ese grupo vacio es donde entra el lote nuevo.
        seed = ("", "", "")
        if not groups and line_values:
            seed = line_values
        groups.append(
            {
                "lote": seed[0],
                "fecha_elaboracion": seed[1],
                "fecha_envasado": seed[2],
                "slots": pending,
            }
        )

    return tuple(
        LoadGroup(
            index=position,
            lote=group["lote"],
            fecha_elaboracion=group["fecha_elaboracion"],
            fecha_envasado=group["fecha_envasado"],
            slots=tuple(group["slots"]),
        )
        for position, group in enumerate(groups)
    )


def parse_slots(raw: str | None) -> tuple[str, ...]:
    """Lee la lista de slots que manda el formulario."""

    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def unique_slots(contents: tuple[LoadContent, ...]) -> tuple[LoadContent, ...]:
    """Garantiza que cada pallet tenga un slot unico dentro de la linea.

    En la practica un pallet lleva un solo contenido por linea, pero un payload
    armado a mano podria traer dos. Con el slot repetido, el reparto de lotes
    quedaria ambiguo, asi que al segundo se le agrega su identificador.
    """

    seen: set[str] = set()
    result: list[LoadContent] = []
    for content in contents:
        slot = content.slot
        if slot in seen:
            slot = f"{slot}#{content.id}"
        seen.add(slot)
        result.append(
            content if slot == content.slot else replace(content, slot=slot)
        )
    return tuple(result)


def parse_groups(form, line: LoadLine) -> list[LoadGroup]:
    """Lee los grupos que mand el formulario para una linea."""

    groups: list[LoadGroup] = []
    index = 0
    while True:
        lote_field = f"lote_{line.key}_{index}"
        if lote_field not in form:
            break
        groups.append(
            LoadGroup(
                index=index,
                lote=(form.get(lote_field) or "").strip(),
                fecha_elaboracion=(
                    form.get(f"fecha_{line.key}_{index}") or ""
                ).strip(),
                fecha_envasado=(
                    form.get(f"fecha_envasado_{line.key}_{index}") or ""
                ).strip(),
                slots=parse_slots(form.get(f"pallets_{line.key}_{index}")),
            )
        )
        index += 1
    return groups


def validate_groups(line: LoadLine, groups: list[LoadGroup]) -> list[str]:
    """Revisa que ningun pallet quede en dos grupos ni fuera de la linea."""

    errors: list[str] = []
    valid = set(line.slots)
    seen: set[str] = set()
    for group in groups:
        for slot in group.slots:
            if slot not in valid:
                errors.append(
                    f"El pallet {slot} no pertenece a la linea de {line.product}."
                )
            elif slot in seen:
                errors.append(
                    f"El pallet {slot} quedo asignado a dos lotes de {line.product}."
                )
            else:
                seen.add(slot)
    return errors


def unassigned_slots(line: LoadLine, groups: list[LoadGroup]) -> tuple[str, ...]:
    """Slots de la linea que ningun grupo Tomo."""

    assigned = {slot for group in groups for slot in group.slots}
    return tuple(slot for slot in line.slots if slot not in assigned)


def main_group(groups: list[LoadGroup]) -> LoadGroup | None:
    """Grupo que define el lote de la linea: el que mas pallets tiene.

    La linea solo puede guardar un lote. Cuando la linea va con mas de un lote,
    el que prima es el que cubre mas pallets; a igualdad, el que esta primero.
    """

    with_lote = [group for group in groups if group.lote]
    if not with_lote:
        return None
    return max(with_lote, key=lambda group: (len(group.slots), -group.index))
