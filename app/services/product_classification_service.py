from dataclasses import dataclass
from decimal import Decimal
import re
import unicodedata


@dataclass(frozen=True)
class ProductInference:
    product_kind: str
    peso_unitario_kg: Decimal
    review_required: bool


def _normalized(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return " ".join("".join(char for char in text if not unicodedata.combining(char)).upper().split())


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", "."))


def _infer_weight(text: str) -> Decimal:
    multi = re.search(r"(?:PACK\s*)?(\d+)\s*(?:UNIDADES|UNIDAD|UNID|UNI)\.?\s*X\s*(\d+(?:[.,]\d+)?)\s*(KG|KGS|GR|GRS|GMS|GRAMOS?)\b", text)
    if multi:
        count, amount, unit = multi.groups()
        weight = Decimal(count) * _decimal(amount)
        if unit.startswith(("GR", "GM")):
            weight /= Decimal("1000")
        return weight.quantize(Decimal("0.001"))

    amount = re.search(r"\bX\s*(\d+(?:[.,]\d+)?)\s*(KG|KGS|GR|GRS|GMS|GRAMOS?)\b", text)
    if amount:
        value, unit = amount.groups()
        weight = _decimal(value)
        if unit.startswith(("GR", "GM")):
            weight /= Decimal("1000")
        return weight.quantize(Decimal("0.001"))
    if re.search(r"\bX\s*(?:EL\s+)?KG\b", text):
        return Decimal("1.000")
    return Decimal("0.000")


def analyze_legacy_product(name: str) -> ProductInference:
    text = _normalized(name)
    financial = ("CREDITO", "DIFERENCIA", "AJUSTE", "CHEQUE DEVUELTO", "GASTOS ADMINISTRATIVOS", "SIN CARGO", "NOTA DE DEBITO")
    services = ("FLETE", "ALQUILER", "LABORES", "CARGA YERBA")
    internal = ("CONSUMO", "BOBINA", "BANDA FILTRO")
    products = ("FECULA", "ALMIDON", "ALMID.", "BOLSA", "PACK")

    if any(keyword in text for keyword in financial):
        kind = "financiero"
    elif any(keyword in text for keyword in services):
        kind = "servicio"
    elif any(keyword in text for keyword in internal):
        kind = "interno"
    elif any(keyword in text for keyword in products):
        kind = "producto"
    else:
        kind = "revisar"
    weight = _infer_weight(text) if kind == "producto" else Decimal("0.000")
    return ProductInference(kind, weight, kind == "revisar" or (kind == "producto" and weight == 0))
