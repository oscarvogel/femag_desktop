from __future__ import annotations

from datetime import date, datetime, timezone

# peewee guarda los DateTimeField como texto y, en la 3, no parsea el offset UTC:
# un valor generado con `BaseModel.utc_now()` vuelve como
# '2026-10-02 12:44:59.974192+00:00'. Estos formatos son el respaldo para cuando
# `fromisoformat` no alcanza.
_FALLBACK_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f%z",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def as_datetime(value) -> datetime | None:
    """Repara el tipo de una fecha persistida sin cambiar su significado.

    Acepta `datetime`, `date`, texto y `None`. Si el texto trae offset, el
    resultado queda *aware*; si no, queda *naive*: la coercion solo arregla el
    tipo, la zona horaria la sigue aplicando cada call site como hasta ahora.
    """
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
        for pattern in _FALLBACK_FORMATS:
            try:
                return datetime.strptime(text, pattern)
            except ValueError:
                continue
    return value


def utc_datetime_to_local(value) -> datetime | None:
    """Interpret persisted datetimes as UTC and convert them to local workstation time.

    Peewee can return DATETIME values as text (with or without a UTC offset) and
    can return them without tzinfo even when they were generated from UTC-aware
    values. In those cases we coerce the value first and then restore UTC
    explicitly; otherwise Python treats the value as local time and the UI shows
    the UTC clock unchanged.
    """
    value = as_datetime(value)
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone()
