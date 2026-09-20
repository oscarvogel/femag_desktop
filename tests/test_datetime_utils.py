from datetime import datetime, timezone

from app.utils.datetime_utils import utc_datetime_to_local


def test_utc_datetime_to_local_restores_utc_for_naive_values(monkeypatch):
    # MySQL/Peewee may return a UTC DATETIME without tzinfo.
    naive_utc = datetime(2026, 9, 19, 21, 16, 0)
    local = utc_datetime_to_local(naive_utc)

    assert local.tzinfo is not None
    # The instant must remain 21:16 UTC regardless of workstation timezone.
    assert local.astimezone(timezone.utc) == datetime(
        2026, 9, 19, 21, 16, 0, tzinfo=timezone.utc
    )


def test_utc_datetime_to_local_preserves_aware_instant():
    aware = datetime(2026, 9, 19, 21, 16, 0, tzinfo=timezone.utc)
    local = utc_datetime_to_local(aware)

    assert local.astimezone(timezone.utc) == aware
