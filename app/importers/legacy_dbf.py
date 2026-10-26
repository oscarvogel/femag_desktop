from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from peewee import IntegrityError, fn

from app.models.base import utc_now
from app.models.dgr import DgrLocality
from app.models.masters import (
    CLIENT_ADDRESS_TYPE_DELIVERY,
    CLIENT_ADDRESS_TYPE_FISCAL,
    CLIENT_ADDRESS_TYPE_SHARED,
    Carrier,
    Client,
    ClientAddress,
    Driver,
    Product,
    TipoIVA,
    Truck,
)
from app.models.system import ImportBatch
from app.services.client_service import ClientService
from app.services.product_classification_service import analyze_legacy_product


ENTITY_KEYS = ("clients", "carriers", "drivers", "trucks", "products")
EXEMPT_VAT_NAME = "EXENTO"

#: Campos de los que la importacion es **dueña**: el operador no los edita en el
#: ABM (la localidad DGR, el tipo de chasis, los rubros DGR), asi que puede
#: corregirlos siempre. Son ademas los que el F150 exige.
#:
#: Todo lo demas es del operador: en modo ``patch`` la importacion solo lo
#: completa cuando esta vacio, para que una reimportacion en una base viva no
#: deshaga lo que el operador corrigio a mano.
IMPORT_OWNED_FIELDS: dict[str, tuple[str, ...]] = {
    "Client": (),
    "Carrier": ("codigo", "tipo", "locality"),
    "Driver": ("locality",),
    "Truck": ("chassis_type", "trailer_type"),
    "Product": (
        "rh1",
        "rh2",
        "rh3",
        "rh4",
        "unidad_dgr",
        "tipo_iva",
        "peso_unitario_kg",
        "product_kind",
        "classification_source",
        "weight_source",
        "review_required",
    ),
}

#: Ancho del campo ``DOMICILIO`` en ``transporte.dbf`` y ``chofer.dbf``. El F150
#: escribe ese domicilio en los campos 13 (transportista) y 31 (chofer) de la
#: cabecera C, y los archivos reales lo traen completo.
ADDRESS_WIDTH = 30

#: Tipos de dirección que el importador considera "la dirección del cliente".
#: Los tres valen: una dirección fiscal sola, una de entrega sola, o una
#: compartida (fiscal y entrega) que es lo que crea la importación.
CLIENT_ADDRESS_TYPES = (
    CLIENT_ADDRESS_TYPE_FISCAL,
    CLIENT_ADDRESS_TYPE_DELIVERY,
    CLIENT_ADDRESS_TYPE_SHARED,
)


@dataclass(frozen=True)
class ImportOutcome:
    action: str
    warnings: tuple[dict[str, str], ...] = ()
    related_actions: tuple[tuple[str, str], ...] = ()
    #: Contadores que se suman al resumen de la entidad (``nombre -> cantidad``).
    counters: tuple[tuple[str, int], ...] = ()


class LegacyDbfMasterImporter:
    """Importa los maestros del legacy.

    Hay dos modos y el default es el que no destruye trabajo:

    - ``patch`` (default): **solo completa lo que esta vacio**. Si el campo ya
      tiene un valor, no se toca. Es el modo para una base viva, donde el
      operador ya corrigio nombres, telefonos, domicilios o rubros, y una
      reimportacion no puede deshacer eso.
    - ``overwrite``: el legacy manda, como antes. Sirve para una carga limpia
      de una base vacia o para una recarga deliberada.
    """

    MODE_PATCH = "patch"
    MODE_OVERWRITE = "overwrite"
    MODES = (MODE_PATCH, MODE_OVERWRITE)

    def __init__(self, *, mode: str = MODE_PATCH):
        if mode not in self.MODES:
            raise ValueError(f"Modo de importacion desconocido: {mode!r}.")
        self.mode = mode

    def import_dbf_files(
        self,
        paths_by_entity: Mapping[str, str | Path],
        *,
        source_system: str = "legacy_dbf",
        encoding: str = "cp1252",
        mode: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        if mode is not None:
            self.mode = mode
        rows_by_entity = {
            entity: self._read_dbf(path, encoding=encoding)
            for entity, path in paths_by_entity.items()
            if entity in ENTITY_KEYS
        }
        return self.import_rows(rows_by_entity, source_system=source_system)

    def import_rows(
        self,
        rows_by_entity: Mapping[str, Iterable[Mapping[str, Any]]],
        *,
        source_system: str = "legacy_dbf",
    ) -> dict[str, dict[str, Any]]:
        batch = ImportBatch.create(source_system=source_system, status="running")
        summary = self._empty_summary()

        for entity in ENTITY_KEYS:
            rows = rows_by_entity.get(entity, [])
            handler = getattr(self, f"_import_{entity}")
            for raw_row in rows:
                row = self._normalize_row(raw_row)
                try:
                    outcome = handler(row, source_system, batch)
                    summary[entity][outcome.action] += 1
                    summary[entity]["warnings"].extend(outcome.warnings)
                    for related_entity, related_action in outcome.related_actions:
                        summary[related_entity][related_action] += 1
                    for counter_name, counter_value in outcome.counters:
                        summary[entity][counter_name] = (
                            summary[entity].get(counter_name, 0) + counter_value
                        )
                except ValueError as exc:
                    summary[entity]["errors"].append(
                        {"source_id": self._value(row, "CODIGO", "ID", "IDLEGACY"), "message": str(exc)}
                    )
                except IntegrityError as exc:
                    # Una fila que choca con un indice unico (por ejemplo dos
                    # filas del legacy con el mismo nombre de chofer) no puede
                    # frenar la importacion entera: si frena, los camiones, los
                    # productos y las direcciones se quedan sin importar y el
                    # F150 sigue sin poder emitir. Se anota la fila y se sigue.
                    summary[entity]["errors"].append(
                        {
                            "source_id": self._value(row, "CODIGO", "ID", "IDLEGACY"),
                            "message": f"choque con un indice unico: {exc}",
                        }
                    )

        batch.status = "success" if not any(summary[entity]["errors"] for entity in ENTITY_KEYS) else "partial"
        batch.finished_at = utc_now()
        batch.summary = json.dumps(summary, ensure_ascii=True, sort_keys=True)
        batch.save()
        return summary

    def _import_clients(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> ImportOutcome:
        source_id = self._required(row, "clients", "CODIGO", "ID", "IDLEGACY")
        name = self._required(row, "clients", "RAZON", "NOMBRE", "CLIENTE")
        # El CUIT es opcional a propósito (#686): el legacy no lo tiene siempre, y
        # donde no lo tiene pone un relleno que comparten varias filas.
        cuit = self._clean_cuit(self._value(row, "CUIT", "CUITCLI"))
        values = {
            "name": name,
            "cuit": cuit,
            "iva_condition": self._value(row, "IVA", "CONDIVA", default="RI"),
            "phone": self._value(row, "TELEFONO", "TEL", "PHONE"),
            "email": self._value(row, "EMAIL", "MAIL"),
            "contact": self._value(row, "CONTACTO"),
        }
        action, client, warnings, completados, pisados = self._upsert_client(
            values, source_system, source_id, batch
        )
        backfilled, updated, ignored, created, completed = self._ensure_client_addresses(client, row)
        return ImportOutcome(
            action,
            tuple(warnings),
            counters=(
                ("localidad_backfill", backfilled),
                ("localidad_actualizada", updated),
                ("localidad_respetada", ignored),
                ("direcciones_creadas", created),
                ("ciudad_provincia_completadas", completed),
                ("campos_completados", completados),
                ("campos_pisados", pisados),
            ),
        )

    def _upsert_client(
        self,
        values: dict[str, Any],
        source_system: str,
        source_id: str,
        batch: ImportBatch,
    ) -> tuple[str, Client, list[dict[str, str]]]:
        """Guarda el cliente buscándolo primero por su CODIGO del legacy (#686).

        La identidad es ``(source_system, source_id)``, que es lo que el legacy
        garantiza: un CODIGO por fila. Antes de esto la clave natural era el CUIT,
        y eso rompía con los clientes sin CUIT: el legacy los completa con ceros y
        guiones, ese relleno lo comparten varias filas distintas y todas terminaban
        en el mismo registro. Una se pisaba sobre otra y la importación abortaba
        con ``Duplicate entry '00000000000' for key 'client.client_cuit'``.

        Cuando la fila **no** tiene CUIT real no hay nada con qué adoptar: se crea
        el cliente y listo. Cuando sí lo tiene, se sigue adoptando un cliente que
        ya exista con ese CUIT, que es el comportamiento previo y evita duplicar
        clientes ya cargados a mano en FEMAG.

        Devuelve la acción, el cliente y los avisos.
        """
        now = utc_now()
        warnings: list[dict[str, str]] = []
        cuit = values.get("cuit")

        client = (
            Client.select()
            .where((Client.source_system == source_system) & (Client.source_id == source_id))
            .first()
        )
        if client is None and cuit:
            adopted = Client.select().where(Client.cuit == cuit).first()
            if adopted is not None:
                client = adopted
                # Dos filas distintas del legacy con el mismo CUIT real: la segunda
                # se pierde la primera. No es motivo para abortar toda la
                # importacion, pero el operador tiene que verlo en el resumen.
                if client.source_system or client.source_id:
                    warnings.append(
                        {
                            "code": "client_cuit_shared_by_two_rows",
                            "source_id": source_id,
                            "message": (
                                f"el CUIT {cuit} ya identifica a {client.source_system}:"
                                f"{client.source_id}; esta fila actualiza ese cliente "
                                "y la anterior queda absorbida"
                            ),
                        }
                    )

        if client is None:
            action = "created"
            completados, pisados = 0, 0
            client = Client(**values)
            client.imported_at = now
        else:
            action = "updated"
            values = self._cuit_that_does_not_belong_to_another(
                client, values, source_id, warnings
            )
            completados, pisados = self._aplicar_valores(client, values)
            if client.imported_at is None:
                client.imported_at = now

        client.source_system = source_system
        client.source_id = source_id
        client.updated_from_source_at = now
        client.last_import_batch = batch
        client.save()
        return action, client, warnings, completados, pisados

    def _cuit_that_does_not_belong_to_another(
        self,
        client: Client,
        values: dict[str, Any],
        source_id: str,
        warnings: list[dict[str, str]],
    ) -> dict[str, Any]:
        """No le saca el CUIT a otro cliente para ponérselo a este (#741).

        ``client.cuit`` es único. El legacy a veces tiene **dos filas con el
        mismo CUIT** (el mismo cliente con dos codigos, uno abreviado y otro
        completo) y a veces corrige el CUIT de una fila con el de otra. Cuando
        eso pasa, la fila que ya existe en la base por su ``source_id`` recibe
        el CUIT de la otra, y el guardado revienta con
        ``Duplicate entry ... for key 'client.client_cuit'``: la importacion
        entera se caia y con ella los camiones, los choferes y los productos
        que ya venian bien.

        El CUIT identifica al cliente, asi que no se lo sacamos a quien lo
        tiene: se deja el que ya estaba y se avisa, que es una decision del
        operador y no del importador.
        """
        cuit = values.get("cuit")
        if not cuit:
            return values
        if client.cuit == cuit:
            return values
        owner = Client.select().where((Client.cuit == cuit) & (Client.id != client.id)).first()
        if owner is None:
            return values
        warnings.append(
            {
                "code": "client_cuit_taken_by_another_row",
                "source_id": source_id,
                "message": (
                    f"el CUIT {cuit} ya lo tiene el cliente "
                    f"{owner.source_system or 'manual'}:{owner.source_id or owner.id}; "
                    f"este cliente conserva su CUIT {client.cuit or '(sin CUIT)'}"
                ),
            }
        )
        return {**values, "cuit": client.cuit}

    def _ensure_client_addresses(self, client: Client, row: dict[str, Any]) -> tuple[int, int, int, int, int]:
        """Deja las direcciones fiscal y de entrega con datos DGR coherentes.

        El legacy separa los dos domicilios:

        - ``DOMICILIO``/``CODPOS``/``LOCALIDAD``: domicilio legal o fiscal;
        - ``C_DOMI``/``C_CODPOS``/``C_LOCAL``: domicilio comercial o de entrega,
          que es el que usa el remito impreso.

        El importador anterior tomaba solo ``DOMICILIO`` como una dirección
        compartida. Eso confundía fiscal con entrega y, además, dejaba
        ``province = "Sin especificar"`` aunque la localidad DGR fuera válida
        (#688, #743, #790). Ahora, cuando los dos domicilios son distintos, se
        mantienen separados; cuando son iguales, se conserva una sola dirección
        compartida para no duplicar.

        El backfill de localidad/ciudad/provincia es conservador: en modo
        ``patch`` solo completa vacíos o ``Sin especificar`` y nunca pisa lo que
        el operador corrigió a mano.

        Devuelve ``(localidades completadas, localidades actualizadas,
        localidades respetadas, direcciones creadas, ciudades/provincias
        completadas)``.
        """
        fiscal = self._address_values(
            row,
            address_aliases=("DOMICILIO", "DIRECCION", "ADDRESS"),
            postal_aliases=("CODPOS", "CODIGOPOSTAL", "CP"),
            locality_aliases=("LOCALIDAD", "CODLOC"),
            city_aliases=("IMPOSITIVO", "CIUDAD", "CITY"),
        )
        delivery = self._address_values(
            row,
            address_aliases=("C_DOMI", "CDOMI"),
            postal_aliases=("C_CODPOS", "CCODPOS"),
            locality_aliases=("C_LOCAL", "CLOCAL"),
            city_aliases=("IMPOSITIVO", "CIUDAD", "CITY"),
        )
        if not fiscal["address"] and not delivery["address"]:
            return 0, 0, 0, 0, 0
        if not delivery["address"]:
            delivery = dict(fiscal)
        if not fiscal["address"]:
            fiscal = dict(delivery)

        totals = [0, 0, 0, 0, 0]
        if self._same_address(fiscal, delivery):
            ClientService.consolidate_identical_fiscal_delivery(client)
            totals = self._apply_address_totals(
                totals,
                self._ensure_client_address(
                    client, CLIENT_ADDRESS_TYPE_SHARED, fiscal
                ),
            )
            return tuple(totals)

        # La dirección fiscal puede estar cubierta por una compartida que ya
        # existe. En ese caso no se crea una fiscal duplicada.
        shared = (
            ClientAddress.select()
            .where(
                (ClientAddress.client == client)
                & (ClientAddress.address_type == CLIENT_ADDRESS_TYPE_SHARED)
            )
            .first()
        )
        if shared is not None and self._same_address_text(shared.address, fiscal["address"]):
            totals = self._apply_address_totals(
                totals, self._fill_address_fields(shared, fiscal)
            )
        else:
            totals = self._apply_address_totals(
                totals,
                self._ensure_client_address(
                    client, CLIENT_ADDRESS_TYPE_FISCAL, fiscal
                ),
            )
        totals = self._apply_address_totals(
            totals,
            self._ensure_client_address(
                client, CLIENT_ADDRESS_TYPE_DELIVERY, delivery
            ),
        )
        return tuple(totals)

    @staticmethod
    def _apply_address_totals(totals: list[int], partial: tuple[int, int, int, int, int]) -> list[int]:
        return [left + right for left, right in zip(totals, partial)]

    def _address_values(
        self,
        row: dict[str, Any],
        *,
        address_aliases: tuple[str, ...],
        postal_aliases: tuple[str, ...],
        locality_aliases: tuple[str, ...],
        city_aliases: tuple[str, ...],
    ) -> dict[str, Any]:
        from app.services.dgr_validation import derive_city_province

        address = " ".join(self._value(row, *address_aliases).split())
        postal_code = self._value(row, *postal_aliases)
        locality = self._find_locality(row, *locality_aliases)
        derived_city, derived_province = derive_city_province(locality)
        legacy_city = self._value(row, *city_aliases)
        city = derived_city or legacy_city or "Sin especificar"
        province = derived_province or "Sin especificar"
        observations = f"Código postal: {postal_code}" if postal_code else None
        return {
            "address": address,
            "city": city,
            "province": province,
            "locality": locality,
            "observations": observations,
        }

    @staticmethod
    def _same_address_text(left: str | None, right: str | None) -> bool:
        from app.services.dgr_validation import normalize_dgr_text

        return normalize_dgr_text(left) == normalize_dgr_text(right)

    def _same_address(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        return (
            self._same_address_text(left.get("address"), right.get("address"))
            and (left.get("locality_id") or (left.get("locality").id if left.get("locality") else None))
            == (right.get("locality_id") or (right.get("locality").id if right.get("locality") else None))
        )

    def _ensure_client_address(
        self, client: Client, address_type: str, values: dict[str, Any]
    ) -> tuple[int, int, int, int, int]:
        """Crea o completa una dirección del cliente sin duplicarla."""
        existing = (
            ClientAddress.select()
            .where(
                (ClientAddress.client == client)
                & (ClientAddress.address_type == address_type)
            )
            .order_by(ClientAddress.id)
            .first()
        )
        if existing is not None:
            return self._fill_address_fields(existing, values)

        # No duplicar una dirección del mismo domicilio que ya cubre la función
        # pedida (por ejemplo, una compartida cuando se importa la fiscal).
        compatible_types = {
            CLIENT_ADDRESS_TYPE_FISCAL: (
                CLIENT_ADDRESS_TYPE_FISCAL,
                CLIENT_ADDRESS_TYPE_SHARED,
            ),
            CLIENT_ADDRESS_TYPE_DELIVERY: (
                CLIENT_ADDRESS_TYPE_DELIVERY,
                CLIENT_ADDRESS_TYPE_SHARED,
            ),
            CLIENT_ADDRESS_TYPE_SHARED: CLIENT_ADDRESS_TYPES,
        }.get(address_type, (address_type,))
        for candidate in ClientAddress.select().where(
            (ClientAddress.client == client)
            & (ClientAddress.address_type.in_(compatible_types))
        ):
            if self._same_address_text(candidate.address, values["address"]):
                return self._fill_address_fields(candidate, values)

        has_primary = ClientAddress.select().where(
            (ClientAddress.client == client)
            & (ClientAddress.active == True)  # noqa: E712
            & (ClientAddress.is_primary == True)  # noqa: E712
        ).exists()
        ClientAddress.create(
            client=client,
            address_type=address_type,
            province=values["province"],
            city=values["city"],
            address=values["address"],
            locality=values["locality"],
            is_primary=address_type == CLIENT_ADDRESS_TYPE_SHARED
            or (address_type == CLIENT_ADDRESS_TYPE_DELIVERY and not has_primary),
            observations=values["observations"],
        )
        return 0, 0, 0, 1, 0

    def _fill_address_fields(
        self, address: ClientAddress, values: dict[str, Any]
    ) -> tuple[int, int, int, int, int]:
        """Completa localidad/ciudad/provincia sin pisar cambios humanos."""
        from app.services.dgr_validation import is_missing_dgr_text

        locality = values.get("locality")
        backfilled = updated = ignored = completed = 0
        fields: list = []
        if locality is not None:
            if address.locality_id is None:
                address.locality = locality
                backfilled += 1
                fields.append(ClientAddress.locality)
            elif address.locality_id != locality.id:
                if self.mode == self.MODE_PATCH:
                    ignored += 1
                else:
                    address.locality = locality
                    updated += 1
                    fields.append(ClientAddress.locality)

        for field, key in (
            (ClientAddress.city, "city"),
            (ClientAddress.province, "province"),
        ):
            current = getattr(address, field.name)
            value = values.get(key)
            if is_missing_dgr_text(current) and not is_missing_dgr_text(value):
                setattr(address, field.name, value)
                completed += 1
                fields.append(field)
        if address.observations is None and values.get("observations"):
            address.observations = values["observations"]
            fields.append(ClientAddress.observations)
        if fields:
            address.save(only=fields)
        return backfilled, updated, ignored, 0, completed

    def _import_carriers(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> ImportOutcome:
        source_id = self._required(row, "carriers", "CODIGO", "ID", "IDLEGACY")
        name = self._required(row, "carriers", "NOMBRE", "RAZON", "TRANSPORTISTA")
        values = {
            "name": name,
            "cuit": self._clean_cuit(self._value(row, "CUIT", "CUITTRA")) or None,
            "phone": self._value(row, "TELEFONO", "TEL", "PHONE"),
            "codigo": source_id,
            "tipo": self._value(row, "TIPO", "TIPOTRANSP") or None,
            "locality": self._find_locality(row),
            "address": self._address(row),
        }
        action, completados, pisados = self._upsert(
            Carrier, {"name": name}, values, source_system, source_id, batch
        )
        return ImportOutcome(
            action,
            counters=(("campos_completados", completados), ("campos_pisados", pisados)),
        )

    def _import_drivers(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> ImportOutcome:
        source_id = self._required(row, "drivers", "CODIGO", "ID", "IDLEGACY")
        name = self._required(row, "drivers", "NOMBRE", "CHOFER")
        existing_driver = (
            Driver.select()
            .where((Driver.source_system == source_system) & (Driver.source_id == source_id))
            .first()
        ) or Driver.select().where(Driver.name == name).first()
        explicit_carrier_source_id = self._value(row, "TRANSP", "TRANSPORTISTA", "CARRIER")
        if explicit_carrier_source_id:
            carrier = self._get_carrier(source_system, explicit_carrier_source_id)
            warnings = ()
        else:
            carrier, warnings = self._resolve_driver_carrier(row, source_system)
        if carrier is None and existing_driver is not None and existing_driver.carrier_id is not None:
            carrier = existing_driver.carrier
        usual_truck, truck_action, truck_warnings = self._upsert_habitual_truck(
            row,
            carrier,
            source_system,
            source_id,
            batch,
        )
        if usual_truck is None and existing_driver is not None and existing_driver.usual_truck_id is not None:
            usual_truck = existing_driver.usual_truck
        values = {
            "name": name,
            "carrier": carrier,
            "usual_truck": usual_truck,
            "cuit": self._clean_cuit(self._value(row, "CUIT", "CUITCHOFER")) or None,
            "document": self._value(row, "DNI", "DOCUMENTO", "DOC"),
            "phone": self._value(row, "TELEFONO", "TEL", "PHONE"),
            "locality": self._find_locality(row),
            "address": self._address(row),
        }
        action, completados, pisados = self._upsert(
            Driver, {"name": name}, values, source_system, source_id, batch
        )
        related_actions = (("trucks", truck_action),) if truck_action is not None else ()
        return ImportOutcome(
            action,
            warnings + truck_warnings,
            related_actions,
            counters=(("campos_completados", completados), ("campos_pisados", pisados)),
        )

    def _import_trucks(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> ImportOutcome:
        source_id = self._required(row, "trucks", "CODIGO", "ID", "IDLEGACY")
        domain = self._clean_domain(self._required(row, "trucks", "PATENTE", "DOMINIO", "DOMAIN"))
        carrier_source_id = self._required(row, "trucks", "TRANSP", "TRANSPORTISTA", "CARRIER")
        carrier = self._get_carrier(source_system, carrier_source_id)
        values = {"domain": domain, "carrier": carrier}
        action, completados, pisados = self._upsert(
            Truck, {"domain": domain}, values, source_system, source_id, batch
        )
        return ImportOutcome(
            action,
            counters=(("campos_completados", completados), ("campos_pisados", pisados)),
        )

    def _import_products(self, row: dict[str, Any], source_system: str, batch: ImportBatch) -> ImportOutcome:
        source_id = self._required(row, "products", "CODIGO", "ID", "IDLEGACY")
        name = self._required(row, "products", "NOMBRE", "PRODUCTO", "DESCRIP")
        exempt_vat = self._ensure_exempt_vat()
        existing = (
            Product.select().where((Product.source_system == source_system) & (Product.source_id == source_id)).first()
            or Product.select().where(Product.name == name).first()
        )
        inference = analyze_legacy_product(name)
        if (
            existing is not None
            and existing.peso_unitario_kg > 0
            and existing.peso_unitario_kg != inference.peso_unitario_kg
            and existing.weight_source != "manual"
        ):
            existing.weight_source = "manual"
            existing.save(only=[Product.weight_source])
        legacy_unit = self._value(row, "UNIDADDGR", "UNIDAD", "UNI", default="unidad")
        values = {
            "name": name,
            "unit": {"K": "kg", "U": "unidad"}.get(legacy_unit.upper(), legacy_unit),
            "tipo_iva": exempt_vat,
            "rh1": self._value(row, "RH1") or None,
            "rh2": self._value(row, "RH2") or None,
            "rh3": self._value(row, "RH3") or None,
            "rh4": self._value(row, "RH4") or None,
            "unidad_dgr": self._value(row, "UNIDADDGR") or None,
        }
        if existing is None or existing.classification_source != "manual":
            values.update(product_kind=inference.product_kind, classification_source="inferido")
        if existing is None or existing.weight_source != "manual":
            values.update(peso_unitario_kg=inference.peso_unitario_kg, weight_source="inferido")
        effective_kind = values.get("product_kind", existing.product_kind if existing else inference.product_kind)
        effective_weight = values.get("peso_unitario_kg", existing.peso_unitario_kg if existing else inference.peso_unitario_kg)
        values["review_required"] = effective_kind == "revisar" or (effective_kind == "producto" and effective_weight <= 0)
        action, completados, pisados = self._upsert(
            Product, {"name": name}, values, source_system, source_id, batch
        )
        return ImportOutcome(
            action,
            counters=(("campos_completados", completados), ("campos_pisados", pisados)),
        )

    def _ensure_exempt_vat(self) -> TipoIVA:
        exempt_vat = (
            TipoIVA.select()
            .where(fn.Lower(TipoIVA.nombre) == EXEMPT_VAT_NAME.lower())
            .first()
        )
        if exempt_vat is None:
            return TipoIVA.create(nombre=EXEMPT_VAT_NAME, porcentaje=0.0)
        if exempt_vat.porcentaje != 0.0:
            exempt_vat.porcentaje = 0.0
            exempt_vat.save(only=[TipoIVA.porcentaje])
        return exempt_vat

    def _resolve_driver_carrier(
        self,
        row: dict[str, Any],
        source_system: str,
    ) -> tuple[Carrier | None, tuple[dict[str, str], ...]]:
        source_id = self._value(row, "CODIGO", "ID", "IDLEGACY")
        driver_cuit = self._clean_cuit(self._value(row, "CUIT", "CUITCHOFER"))
        driver_name = self._clean_identity_name(self._value(row, "NOMBRE", "CHOFER"))
        by_code = self._find_carrier_by_source_id(source_system, source_id)

        if by_code is not None and self._carrier_identity_matches(by_code, driver_cuit, driver_name):
            return by_code, ()

        cuit_matches = self._find_carriers_by_cuit(driver_cuit)
        if len(cuit_matches) == 1:
            return cuit_matches[0], ()
        if len(cuit_matches) > 1:
            return None, ({"code": "carrier_cuit_ambiguous", "source_id": source_id},)
        if by_code is not None:
            return None, ({"code": "carrier_code_collision", "source_id": source_id},)
        return None, ({"code": "carrier_not_found", "source_id": source_id},)

    def _upsert_habitual_truck(
        self,
        row: dict[str, Any],
        carrier: Carrier | None,
        source_system: str,
        driver_source_id: str,
        batch: ImportBatch,
    ) -> tuple[Truck | None, str | None, tuple[dict[str, str], ...]]:
        domain = self._clean_domain(self._value(row, "CHASIS"))
        trailer_domain = self._clean_domain(self._value(row, "ACOPLADO")) or None
        if not domain:
            warnings = (
                ({"code": "habitual_truck_missing", "source_id": driver_source_id},)
                if "CHASIS" in row
                else ()
            )
            return None, None, warnings

        now = utc_now()
        warnings: list[dict[str, str]] = []
        truck = Truck.select().where(Truck.domain == domain).first()
        if truck is None:
            truck = Truck.create(
                domain=domain,
                trailer_domain=trailer_domain,
                carrier=carrier,
                chassis_type=self._value(row, "TIPOPATE", "TIPOPATENTE") or None,
                trailer_type=self._value(row, "TIPOPATEAC", "TIPOPATENTEAC") or None,
                source_system=source_system,
                source_id=f"driver:{driver_source_id}",
                imported_at=now,
                updated_from_source_at=now,
                last_import_batch=batch,
            )
            return truck, "created", ()

        if truck.carrier_id is None and carrier is not None:
            truck.carrier = carrier
        elif carrier is not None and truck.carrier_id != carrier.id:
            warnings.append({"code": "truck_carrier_conflict", "source_id": driver_source_id})

        if not truck.trailer_domain and trailer_domain:
            truck.trailer_domain = trailer_domain
        elif trailer_domain and truck.trailer_domain != trailer_domain:
            warnings.append({"code": "truck_trailer_conflict", "source_id": driver_source_id})

        if truck.source_system == source_system and truck.source_id == f"driver:{driver_source_id}":
            truck.updated_from_source_at = now
            truck.last_import_batch = batch
        chassis_type = self._value(row, "TIPOPATE", "TIPOPATENTE")
        if chassis_type and not truck.chassis_type:
            truck.chassis_type = chassis_type
        trailer_type = self._value(row, "TIPOPATEAC", "TIPOPATENTEAC")
        if trailer_type and not truck.trailer_type:
            truck.trailer_type = trailer_type
        truck.save()
        return truck, "updated", tuple(warnings)

    def _find_locality(self, row: dict[str, Any], *aliases: str) -> DgrLocality | None:
        code = self._value(row, *(aliases or ("LOCALIDAD", "C_LOCAL", "CODLOC")))
        if not code:
            return None
        return DgrLocality.select().where(DgrLocality.code == code).first()

    def _find_carrier_by_source_id(self, source_system: str, source_id: str) -> Carrier | None:
        if not source_id:
            return None
        return (
            Carrier.select()
            .where((Carrier.source_system == source_system) & (Carrier.source_id == source_id))
            .first()
        )

    def _find_carriers_by_cuit(self, cuit: str) -> list[Carrier]:
        if not cuit:
            return []
        return [carrier for carrier in Carrier.select() if self._clean_cuit(carrier.cuit or "") == cuit]

    def _carrier_identity_matches(self, carrier: Carrier, driver_cuit: str, driver_name: str) -> bool:
        carrier_cuit = self._clean_cuit(carrier.cuit or "")
        if carrier_cuit and driver_cuit:
            return carrier_cuit == driver_cuit
        return self._clean_identity_name(carrier.name) == driver_name

    def _aplicar_valores(self, row, values: dict[str, Any]) -> tuple[int, int]:
        """Escribe los valores del legacy sobre una fila que ya existe.

        En modo ``patch`` la importacion es dueña de algunos campos (los que el
        operador no edita en el ABM: la localidad DGR, los rubros, el tipo de
        chasis) y de los demas **solo completa los que estan vacios**. Asi una
        reimportacion en una base viva no deshace lo que el operador corrigio a
        mano.

        En modo ``overwrite`` el legacy manda en todos los campos, como antes.

        Un valor vacio del legacy nunca borra lo que ya hay: si el legacy no
        trae el dato, no tiene por que decir nada.

        Devuelve ``(campos completados, campos pisados)``.
        """
        propios = IMPORT_OWNED_FIELDS.get(type(row).__name__, ())
        completados = 0
        pisados = 0
        for field, value in values.items():
            if self.mode == self.MODE_PATCH:
                if self._vacio(value):
                    continue
                actual = getattr(row, field, None)
                if field not in propios and not self._vacio(actual):
                    continue
            actual = getattr(row, field, None)
            if self._vacio(actual):
                completados += 1
            else:
                pisados += 1
            setattr(row, field, value)
        return completados, pisados

    @staticmethod
    def _vacio(value: Any) -> bool:
        """True cuando el campo esta sin dato (``NULL`` o texto en blanco)."""
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        return False

    def _upsert(
        self,
        model,
        natural_lookup: dict[str, Any],
        values: dict[str, Any],
        source_system: str,
        source_id: str,
        batch: ImportBatch,
    ) -> str:
        now = utc_now()
        row = (
            model.select()
            .where((model.source_system == source_system) & (model.source_id == source_id))
            .first()
        )
        if row is None:
            row = model.select().filter(**natural_lookup).first()

        action = "updated" if row is not None else "created"
        completados = 0
        pisados = 0
        if row is None:
            row = model(**values)
            row.imported_at = now
        else:
            completados, pisados = self._aplicar_valores(row, values)
            if row.imported_at is None:
                row.imported_at = now

        row.source_system = source_system
        row.source_id = source_id
        row.updated_from_source_at = now
        row.last_import_batch = batch
        row.save()
        return action, completados, pisados

    def _get_carrier(self, source_system: str, source_id: str) -> Carrier:
        carrier = (
            Carrier.select()
            .where((Carrier.source_system == source_system) & (Carrier.source_id == source_id))
            .first()
        )
        if carrier is None:
            raise ValueError(f"No existe transportista legacy {source_id}.")
        return carrier

    def _required(self, row: dict[str, Any], entity: str, *aliases: str) -> str:
        value = self._value(row, *aliases)
        if not value:
            raise ValueError(f"{entity} requiere CODIGO, RAZON y CUIT.")
        return value

    def _value(self, row: dict[str, Any], *aliases: str, default: str = "") -> str:
        for alias in aliases:
            value = row.get(alias.upper())
            if value is not None:
                text = str(value).strip()
                if text:
                    return text
        return default

    def _normalize_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {str(key).upper().strip(): value for key, value in row.items()}

    def _clean_cuit(self, value: str) -> str | None:
        """Devuelve el CUIT sin separadores, o ``None`` cuando el legacy no trae uno real.

        El legacy completa el campo con ceros y guiones cuando el cliente no
        tiene CUIT (``'  -        -0'``, ``'00-00000000-0'``). Limpiado eso da
        ``'0'`` y ``'00000000000'``, que son valores de relleno, no CUITs: los
        comparten varias filas distintas. Como ``Client.cuit`` es único, guardar
        el relleno hacía que el importador resolviera todos esos clientes al
        mismo registro y los pisara entre sí (#686).

        Solo se descarta lo que no tiene ningún dígito con valor: un CUIT real
        empieza con 20, 23, 24, 27, 30, 33 o 34, así que la prueba de "no es todo
        ceros" alcanza para separar relleno de dato.
        """
        digits = re.sub(r"\D", "", value or "")
        if not digits or not digits.strip("0"):
            return None
        return digits

    def _clean_domain(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", value).upper()

    def _address(self, row: Mapping[str, Any]) -> str | None:
        """Domicilio del transportista o del chofer, que el F150 exige.

        Viene de ``DOMICILIO`` en ``transporte.dbf`` y ``chofer.dbf``, un texto
        libre de 30 caracteres que a veces trae espacios sobrantes. Se colapsan
        para que el ancho sea estable en el archivo. Los choferes cargados a
        mano no pasan por acá: su domicilio lo guarda el operador.
        """
        text = " ".join(self._value(row, "DOMICILIO", "DIRECCION", "DOMIC").split())
        return text[:ADDRESS_WIDTH] or None

    def _clean_identity_name(self, value: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", value.upper())

    def _empty_summary(self) -> dict[str, dict[str, Any]]:
        summary = {
            entity: {"created": 0, "updated": 0, "skipped": 0, "errors": [], "warnings": []}
            for entity in ENTITY_KEYS
        }
        # Cuántas direcciones de cliente quedaron con la localidad DGR puesta y
        # cuántas cambiaron de localidad por culpa del legacy (#688).
        summary["clients"]["localidad_backfill"] = 0
        summary["clients"]["localidad_actualizada"] = 0
        summary["clients"]["localidad_respetada"] = 0
        summary["clients"]["direcciones_creadas"] = 0
        summary["clients"]["ciudad_provincia_completadas"] = 0
        return summary

    def _read_dbf(self, path: str | Path, *, encoding: str) -> list[dict[str, Any]]:
        try:
            from dbfread import DBF
        except ImportError as exc:
            raise RuntimeError("Instalar dbfread para leer archivos DBF legacy.") from exc

        return [dict(record) for record in DBF(str(path), encoding=encoding, char_decode_errors="ignore")]
