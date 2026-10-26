"""Validaciones compartidas del destino DGR de remitos y F150.

El legacy separa el domicilio legal/fiscal (``DOMICILIO``/``LOCALIDAD``) del
comercial/de entrega (``C_DOMI``/``C_LOCAL``). El F150 y el remito usan datos
distintos, pero los dos necesitan una localidad DGR completa y congruente con
la ciudad y la provincia que se imprimen. Estas reglas viven aca para que el
importador, el alta de domicilios, la emision del remito y la generacion del
F150 no apliquen criterios distintos.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from app.models.dgr import DgrLocality, DgrProvince


UNSPECIFIED = "sin especificar"

#: Formas equivalentes que el legacy y los operadores usan para la misma
#: jurisdiccion. No se usan para inventar un codigo DGR: solo para no bloquear
#: una localidad que el operador ya eligio de la tabla DGR.
_PROVINCE_ALIASES = (
    frozenset({"caba", "capitalfederal", "ciudadautonomadebuenosaires", "buenosairescaba"}),
)


def normalize_dgr_text(value: object) -> str:
    """Clave de comparacion sin tildes, mayusculas ni separadores."""
    text = unicodedata.normalize("NFKD", "" if value is None else str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def is_missing_dgr_text(value: object) -> bool:
    """True para vacio o para el relleno historico ``Sin especificar``."""
    normalized = normalize_dgr_text(value)
    return not normalized or normalized == normalize_dgr_text(UNSPECIFIED)


def _texts_compatible(left: object, right: object) -> bool:
    a = normalize_dgr_text(left)
    b = normalize_dgr_text(right)
    if not a or not b:
        return True
    if a == b or a in b or b in a:
        return True
    if any(a in alias and b in alias for alias in _PROVINCE_ALIASES):
        return True
    tokens_a = set(re.findall(r"[a-z0-9]+", normalize_dgr_text(left)))
    tokens_b = set(re.findall(r"[a-z0-9]+", normalize_dgr_text(right)))
    if tokens_a and tokens_b:
        shared = len(tokens_a & tokens_b)
        if shared and shared / min(len(tokens_a), len(tokens_b)) >= 0.6:
            return True
    return SequenceMatcher(None, a, b).ratio() >= 0.82


def locality_province_name(locality: DgrLocality | None) -> str:
    if locality is None or locality.province_code is None:
        return ""
    province = DgrProvince.get_or_none(DgrProvince.code == locality.province_code)
    return province.name if province is not None else ""


def locality_label(locality: DgrLocality | None) -> str:
    """Etiqueta buscable y desambiguada: nombre, codigo, provincia y pais."""
    if locality is None:
        return ""
    country = locality.country.name if locality.country else "sin pais"
    province = locality_province_name(locality) or "sin provincia"
    return (
        f"{locality.name} - codigo {locality.code} - DGR {locality.dgr_code_4} - "
        f"{province} - {country}"
    )


def derive_city_province(locality: DgrLocality | None) -> tuple[str, str]:
    """Ciudad y provincia que surgen de la localidad DGR elegida.

    Devuelve textos vacios cuando no hay localidad: nunca inventa un valor.
    """
    if locality is None:
        return "", ""
    return (locality.name or "").strip(), locality_province_name(locality)


def locality_issues(locality: DgrLocality | None, *, section: str = "destino") -> list[str]:
    if locality is None:
        return [f"{section}: falta localidad DGR"]
    missing = []
    if locality.dgr_code is None:
        missing.append("localidad")
    if locality.department_code is None:
        missing.append("departamento")
    if locality.province_code is None:
        missing.append("provincia")
    if locality.country is None:
        missing.append("pais")
    if missing:
        return [f"{section}: faltan codigos DGR ({', '.join(missing)})"]
    return []


def consistency_issues(
    *, city: object, province: object, locality: DgrLocality | None, section: str = "destino"
) -> list[str]:
    """Marca una provincia que no corresponde a la localidad DGR elegida.

    La ciudad no se compara por texto: el legacy y los operadores usan variantes
    (``CORDOBA``/``CORDOBA CAPITAL``, ``JUSTINIANO POSE``/``JUSTINIANO POSSE``) y
    el codigo DGR elegido es el dato autoritativo. La provincia si es una
    incompatibilidad objetiva y bloquea.
    """
    if locality is None:
        return []
    province_name = locality_province_name(locality)
    if is_missing_dgr_text(province) or not province_name:
        return []
    if _texts_compatible(province, province_name):
        return []
    return [
        f"{section}: la provincia {str(province).strip()!r} no coincide con "
        f"la localidad DGR {locality.name!r} ({locality.code})"
    ]


def destination_address_issues(
    address, *, section: str = "destino", require_locality: bool = True
) -> list[str]:
    """Valida el domicilio maestro que se usa como entrega."""
    if address is None:
        return [f"{section}: falta domicilio de entrega"]
    issues = []
    if is_missing_dgr_text(address.address):
        issues.append(f"{section}: falta calle/domicilio de entrega")
    if is_missing_dgr_text(address.city):
        issues.append(f"{section}: falta ciudad de entrega")
    if is_missing_dgr_text(address.province):
        issues.append(f"{section}: falta provincia de entrega")
    if require_locality or address.locality is not None:
        issues.extend(locality_issues(address.locality, section=section))
    issues.extend(
        consistency_issues(
            city=address.city,
            province=address.province,
            locality=address.locality,
            section=section,
        )
    )
    return issues


def snapshot_destination_issues(remittance, *, section: str = "destino") -> list[str]:
    """Valida los campos congelados que el F150 imprime del remito."""
    issues = []
    if is_missing_dgr_text(remittance.delivery_address_text):
        issues.append(f"{section}: falta calle/domicilio de entrega en el remito")
    if is_missing_dgr_text(remittance.delivery_city):
        issues.append(f"{section}: falta ciudad de entrega en el remito")
    if is_missing_dgr_text(remittance.delivery_province):
        issues.append(f"{section}: falta provincia de entrega en el remito")
    return issues
