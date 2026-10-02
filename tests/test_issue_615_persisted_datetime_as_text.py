"""#615 - Las fechas persistidas llegan como str y hay que coerciarlas.

peewee 3 devuelve los `DateTimeField` como texto cuando el valor guardado trae
offset UTC, y el proyecto los guarda asi (`BaseModel.utc_now()` es
`datetime.now(timezone.utc)`). Varios call sites asumen `datetime` y revientan
con `'str' object has no attribute 'tzinfo'`.

Este archivo fija la regla del helper y comprueba que cada pantalla que daba
formato a una fecha persistida deje de romper.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, timedelta, timezone


# --------------------------------------------------------------------------------------
# El helper
# --------------------------------------------------------------------------------------


def test_as_datetime_deja_pasar_un_datetime():
    from app.utils.datetime_utils import as_datetime

    value = datetime(2026, 10, 2, 12, 44, 59)
    assert as_datetime(value) is value


def test_as_datetime_parsea_un_string_con_offset():
    from app.utils.datetime_utils import as_datetime

    value = as_datetime("2026-10-02 12:44:59.974192+00:00")

    assert isinstance(value, datetime)
    assert value.year == 2026 and value.month == 10 and value.day == 2
    assert value.hour == 12 and value.minute == 44
    assert value.tzinfo is not None


def test_as_datetime_parsea_un_string_sin_offset():
    from app.utils.datetime_utils import as_datetime

    value = as_datetime("2026-10-02 12:44:59.974192")

    assert isinstance(value, datetime)
    assert value.tzinfo is None


def test_as_datetime_preserva_el_caracter_aware_o_naive():
    """La coercion repara el tipo, no cambia la semantica de zona horaria."""
    from app.utils.datetime_utils import as_datetime

    con_offset = as_datetime("2026-10-02 12:44:59+00:00")
    sin_offset = as_datetime("2026-10-02 12:44:59")

    assert con_offset.tzinfo is not None
    assert sin_offset.tzinfo is None


def test_as_datetime_acepta_date_y_none():
    from app.utils.datetime_utils import as_datetime

    assert as_datetime(None) is None
    value = as_datetime(date(2026, 10, 2))
    assert isinstance(value, datetime)
    assert (value.year, value.month, value.day) == (2026, 10, 2)


def test_as_datetime_tolera_texto_vacio():
    from app.utils.datetime_utils import as_datetime

    assert as_datetime("") is None
    assert as_datetime("   ") is None


# --------------------------------------------------------------------------------------
# La conversion a hora local sigue siendo la misma
# --------------------------------------------------------------------------------------


def test_utc_datetime_to_local_acepta_texto_con_offset():
    """La ventana de auditoria llama a esta funcion con occurred_at de la base."""
    from app.utils.datetime_utils import utc_datetime_to_local

    value = utc_datetime_to_local("2026-10-02 12:44:59.974192+00:00")

    assert isinstance(value, datetime)
    # Mismo instante, expresado en la hora local del puesto.
    esperado = datetime(2026, 10, 2, 12, 44, 59, 974192, tzinfo=timezone.utc).astimezone()
    assert value == esperado
    assert value.tzinfo is not None


def test_utc_datetime_to_local_sigue_tratando_naive_como_utc():
    from app.utils.datetime_utils import utc_datetime_to_local

    value = utc_datetime_to_local(datetime(2026, 10, 2, 12, 44, 59))

    assert value.tzinfo is not None
    assert value.astimezone(timezone.utc).hour == 12


# --------------------------------------------------------------------------------------
# Los call sites que hoy revientan
# --------------------------------------------------------------------------------------


def _widget(module_name, class_name, **kwargs):
    from PyQt5.QtWidgets import QApplication

    # La referencia debe sobrevivir: si el QApplication se libera, Qt aborta.
    app = QApplication.instance() or QApplication([])
    module = __import__(f"app.ui.{module_name}", fromlist=[class_name])
    widget = getattr(module, class_name)(**kwargs)
    widget._test_app = app
    return widget


def test_la_columna_fecha_de_cuenta_corriente_no_revienta(db):
    """Sin movement_date, la columna cae a created_at, que llega como texto."""
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client

    client = Client.create(name="Cliente Sin Fecha", cuit="30700006510", iva_condition="RI")
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        total_amount=1_000.0,
        movement_date=None,
        description="Sin fecha de movimiento",
        source_ref="SIN-FECHA",
        created_at="2026-06-15 10:00:00",
    )

    page = _widget("customer_ledger", "CustomerLedgerPage", current_user="admin")
    page.refresh()
    for row in range(page.clients_table.rowCount()):
        if page.clients_table.item(row, 0).data(256) == client.id:
            page.clients_table.setCurrentCell(row, 0)
            break

    assert page.movements_table.rowCount() == 1
    assert page.movements_table.item(0, 0).text() == "15/06/2026 10:00"


def test_la_ventana_de_auditoria_abre_y_muestra_la_fecha(db):
    from app.models.audit import AuditLog

    AuditLog.create(
        module="SYS", action="create", record_ref="REFTEST", user="auditor615"
    )

    page = _widget("audit_query_page", "AuditQueryPage")
    page.refresh()

    assert page.table.rowCount() >= 1
    assert "/" in page.table.item(0, 0).text()


def test_el_diálogo_de_historial_financiero_abre(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client

    client = Client.create(name="Cliente Historial", cuit="30700006511", iva_condition="RI")
    movement = ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        total_amount=500.0,
        movement_date=date(2026, 6, 15),
        description="Movimiento con historial",
        source_ref="HIST-615",
    )
    # Releido de la base: created_at vuelve como texto.
    desde_base = ClientAccountMovement.get_by_id(movement.id)
    assert isinstance(desde_base.created_at, str)

    dialog = _widget("financial_history_dialog", "FinancialHistoryDialog", movement=desde_base)
    assert dialog is not None


def test_el_recibo_anulado_muestra_la_fecha(db):
    from app.services.payment_receipt_print_service import _display_datetime

    # annulled_at releido de la base llega como texto con offset.
    assert _display_datetime("2026-06-15 10:00:00+00:00") != ""


def test_el_extracto_de_cuenta_corriente_muestra_la_fecha(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.services.account_statement_print_service import _movement_date

    client = Client.create(name="Cliente Extracto", cuit="30700006512", iva_condition="RI")
    movement = ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        total_amount=750.0,
        movement_date=None,
        description="Sin fecha",
        source_ref="EXT-615",
        created_at="2026-06-15 10:00:00",
    )
    desde_base = ClientAccountMovement.get_by_id(movement.id)

    assert _movement_date(desde_base) == "15/06/2026"
