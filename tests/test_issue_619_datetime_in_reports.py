"""#619 - Quedan call sites del bug de fechas en logica de negocio y reportes.

El #615 cubrio los sitios de presentacion. Estos son los que llaman metodos de
`datetime` sobre un `DateTimeField` releido de la base, donde peewee 3 devuelve
texto y peewee 4 no. Con peewee 4 el bug pasa desapercibido; con 3.17.8 (lo que
corren los puestos y produccion) reventan.

Los tests pasan los valores **como texto**, que es lo que devuelve peewee 3, para
que el camino roto se ejercite con cualquier version del ORM.

Nota de alcance: el path de la nota de credito por devolucion
(`load_order_return_credit_service.py`) ya esta cubierto por los seis tests de
`test_load_order_returns.py` y `test_load_order_return_credits.py`, que son
justamente los que fallan con peewee 3.17.8. Lo que no tenia cobertura eran los
informes, y por eso el bug paso inadvertido.
"""

from datetime import date, datetime, timezone
from types import SimpleNamespace


def _texto(valor: datetime) -> str:
    """Como lo deja peewee 3 al releer un DateTimeField con offset."""
    return valor.isoformat(sep=" ")


def test_as_datetime_repara_el_texto_de_pewee_3():
    """El contrato que hace posible el fix."""
    from app.utils.datetime_utils import as_datetime

    valor = as_datetime("2026-09-25 14:30:00.123456+00:00")

    assert isinstance(valor, datetime)
    assert valor.date() == date(2026, 9, 25)


# --------------------------------------------------------------------------------------
# Informe de cobranzas diarias: este path no tenia ninguna cobertura
# --------------------------------------------------------------------------------------


def _movimiento_con_pago_anulado():
    return SimpleNamespace(
        movement_date=None,
        is_reversal=True,
        payment_id=7,
        payment=SimpleNamespace(
            annulled_at=_texto(datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)),
            payment_date=date(2026, 9, 18),
        ),
        load_order_id=None,
        load_order=None,
    )


def test_cobranzas_diarias_usa_la_fecha_de_anulacion_que_llega_texto():
    """`movement.payment.annulled_at.date()` con el valor como texto."""
    from app.reports.daily_collections import DailyCollectionsReportService

    fecha = DailyCollectionsReportService._movement_effective_date(
        _movimiento_con_pago_anulado()
    )

    assert fecha == date(2026, 9, 20)


def test_cobranzas_diarias_no_toca_los_demas_casos():
    """Los otros tres caminos de la misma funcion ya funcionaban y siguen igual."""
    from app.reports.daily_collections import DailyCollectionsReportService

    con_movimiento = _movimiento_con_pago_anulado()
    con_movimiento.movement_date = date(2026, 9, 1)

    sin_anular = SimpleNamespace(
        movement_date=None,
        is_reversal=True,
        payment_id=7,
        payment=SimpleNamespace(annulled_at=None, payment_date=date(2026, 9, 18)),
        load_order_id=None,
        load_order=None,
    )
    con_orden = SimpleNamespace(
        movement_date=None,
        is_reversal=False,
        payment_id=None,
        payment=None,
        load_order_id=3,
        load_order=SimpleNamespace(date=date(2026, 8, 30)),
    )
    sin_nada = SimpleNamespace(
        movement_date=None,
        is_reversal=False,
        payment_id=None,
        payment=None,
        load_order_id=None,
        load_order=None,
    )

    assert DailyCollectionsReportService._movement_effective_date(con_movimiento) == date(2026, 9, 1)
    assert DailyCollectionsReportService._movement_effective_date(sin_anular) == date(2026, 9, 18)
    assert DailyCollectionsReportService._movement_effective_date(con_orden) == date(2026, 8, 30)
    assert DailyCollectionsReportService._movement_effective_date(sin_nada) is None
