"""Limite simple de importaciones con IA por usuario (#913).

No agrega tabla ni escritura en la base: se lleva en memoria del proceso que
atiende la webapp. Waitress usa un solo proceso con hilos, asi que alcanza para
frenar un uso accidental o abusivo. Si el servidor se reinicia, el contador se
reinicia; se documenta como mitigacion, no como cuota contable.
"""

from __future__ import annotations

import threading
import time

WINDOW_SECONDS = 60 * 60

_attempts: dict[str, list[float]] = {}
_lock = threading.Lock()


def is_rate_limited(username: str, limit: int, *, now: float | None = None) -> bool:
    if limit <= 0 or not username:
        return False
    current = time.monotonic() if now is None else now
    with _lock:
        entries = [
            stamp
            for stamp in _attempts.get(username, [])
            if current - stamp < WINDOW_SECONDS
        ]
        _attempts[username] = entries
        return len(entries) >= limit


def register_attempt(username: str, *, now: float | None = None) -> None:
    if not username:
        return
    current = time.monotonic() if now is None else now
    with _lock:
        _attempts.setdefault(username, []).append(current)


def reset() -> None:
    """Solo para tests: limpia todos los contadores."""

    with _lock:
        _attempts.clear()
