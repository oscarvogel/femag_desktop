from decimal import Decimal

import pytest

from app.services.product_classification_service import analyze_legacy_product


@pytest.mark.parametrize(
    ("name", "kind", "weight", "review"),
    [
        ("PACK 10 UNIDADES X 1 KG", "producto", Decimal("10.000"), False),
        ("FECULA X 25 KG", "producto", Decimal("25.000"), False),
        ("ALMIDON PACK X 900 GR", "producto", Decimal("0.900"), False),
        ("ALMIDON X 500 GRS", "producto", Decimal("0.500"), False),
        ("FECULA X KG", "producto", Decimal("1.000"), False),
        ("FLETE", "servicio", Decimal("0.000"), False),
        ("ALQUILER MAQUINAS AGRICOLAS", "servicio", Decimal("0.000"), False),
        ("CHEQUE DEVUELTO", "financiero", Decimal("0.000"), False),
        ("CONSUMO KG. BOBINAS", "interno", Decimal("0.000"), False),
        ("YERBA MATE PUESTA EN PLANTA", "revisar", Decimal("0.000"), True),
        ("BOLSAS SIN PRESENTACION", "producto", Decimal("0.000"), True),
    ],
)
def test_analyze_legacy_product(name, kind, weight, review):
    result = analyze_legacy_product(name)

    assert result.product_kind == kind
    assert result.peso_unitario_kg == weight
    assert result.review_required is review
