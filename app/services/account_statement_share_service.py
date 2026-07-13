from __future__ import annotations

import re
from urllib.parse import urlencode


def normalize_whatsapp_phone(phone: str) -> str:
    raw = (phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 8:
        raise ValueError("El cliente no tiene un telefono valido para WhatsApp.")

    if raw.startswith("+"):
        return digits

    local_mobile = re.fullmatch(r"\s*0?(\d{2,4})[\s-]*15[\s-]*(\d{6,8})\s*", raw)
    if local_mobile:
        return f"549{local_mobile.group(1)}{local_mobile.group(2)}"

    local_digits = digits.lstrip("0")
    if local_digits.startswith("54"):
        return local_digits
    return f"549{local_digits}"


def build_whatsapp_url(client_name: str, phone: str) -> str:
    normalized_phone = normalize_whatsapp_phone(phone)
    message = f"Hola {client_name}, le compartimos su extracto de cuenta corriente."
    return f"https://wa.me/{normalized_phone}?{urlencode({'text': message})}"
