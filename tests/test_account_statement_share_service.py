from urllib.parse import parse_qs, urlparse

import pytest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+54 9 376 412-3456", "5493764123456"),
        ("0376 15 4123456", "5493764123456"),
        ("376 4123456", "5493764123456"),
        ("+55 11 98765-4321", "5511987654321"),
    ],
)
def test_normalize_whatsapp_phone(raw, expected):
    from app.services.account_statement_share_service import normalize_whatsapp_phone

    assert normalize_whatsapp_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "sin telefono", "123"])
def test_normalize_whatsapp_phone_rejects_unusable_values(raw):
    from app.services.account_statement_share_service import normalize_whatsapp_phone

    with pytest.raises(ValueError, match="telefono"):
        normalize_whatsapp_phone(raw)


def test_build_whatsapp_url_targets_client_and_encodes_message():
    from app.services.account_statement_share_service import build_whatsapp_url

    url = build_whatsapp_url("Aserradero Ñandú", "0376 15 4123456")
    parsed = urlparse(url)

    assert parsed.scheme == "https"
    assert parsed.netloc == "wa.me"
    assert parsed.path == "/5493764123456"
    assert parse_qs(parsed.query)["text"] == [
        "Hola Aserradero Ñandú, le compartimos su extracto de cuenta corriente."
    ]
