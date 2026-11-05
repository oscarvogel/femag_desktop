"""El normalizador de WhatsApp no debe inventar celulares (#759)."""

import pytest

from app.services.account_statement_share_service import normalize_whatsapp_phone
from app.services.whatsapp_phone_classifier import (
    ESTADO_POSIBLE,
    clasificar_telefono,
)


def test_local_ten_digit_number_is_rejected_as_ambiguous():
    classification = clasificar_telefono("376 4123456")

    assert classification.estado == ESTADO_POSIBLE
    with pytest.raises(ValueError, match="dudoso"):
        normalize_whatsapp_phone("376 4123456")


def test_landline_with_area_is_rejected():
    classification = clasificar_telefono("011 4441-2835")

    assert classification.estado == ESTADO_POSIBLE
    with pytest.raises(ValueError, match="dudoso"):
        normalize_whatsapp_phone("011 4441-2835")


def test_real_mobile_with_15_still_normalizes():
    assert normalize_whatsapp_phone("0376 15 4123456") == "5493764123456"
    assert normalize_whatsapp_phone("+54 9 376 412-3456") == "5493764123456"


@pytest.mark.parametrize("raw", ["+55 11 98765-4321", "sin telefono", "123"])
def test_foreign_or_invalid_numbers_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize_whatsapp_phone(raw)
