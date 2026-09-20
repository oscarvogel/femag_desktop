from __future__ import annotations

from datetime import datetime, timezone


def utc_datetime_to_local(value: datetime) -> datetime:
    """Interpret persisted datetimes as UTC and convert them to local workstation time.

    Peewee/MySQL can return DATETIME values without tzinfo even when they were
    generated from UTC-aware values. In that case we must explicitly restore
    UTC before converting; otherwise Python treats the value as local time and
    the UI shows the UTC clock unchanged.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone()
