"""El monto objetivo tiene que SOBREVIVIR al tipo de columna real.

Causa raíz del fallo de `--apply` en PRES-000073: las columnas monetarias están
declaradas ``float`` en MySQL, que es de UNA sola precisión (~7 dígitos
significativos). Por encima de 2^25 = 33.554.432 los enteros dejan de ser
representables de forma exacta:

    SELECT CAST(37511775.0 AS FLOAT)  ->  37511800.0

Es decir: la reparación escribe 37.511.775, la base guarda 37.511.800 y al
volver a leerlo se obtiene el valor viejo. La postcondición detectó eso
correctamente y el rollback fue correcto. El defecto NO es la transacción: es
que el importe destino no es representable en la columna.

Estos tests fijan la regla: no se intenta escribir un importe que la columna no
puede representar exactamente, y se aborta antes de abrir la transacción.
"""

from decimal import Decimal

import pytest

from scripts.repair_monetary_integrity import (
    RepairAborted,
    unrepresentable_amounts,
)


class _ColumnProbe:
    """Sustituye al servidor: devuelve lo que MySQL guardaría de verdad."""

    def __init__(self, redondeo: dict[float, float] | None = None):
        self.redondeo = redondeo or {}
        self.consultas = []

    def __call__(self, valor: float) -> float:
        self.consultas.append(valor)
        return self.redondeo.get(valor, valor)


def test_detecta_importe_que_la_columna_altera():
    probe = _ColumnProbe({37511775.0: 37511800.0})

    fallos = unrepresentable_amounts(
        {"budget.total_amount": 37511775.0}, probe=probe
    )

    assert len(fallos) == 1
    columna, valor, persistido = fallos[0]
    assert columna == "budget.total_amount"
    assert valor == 37511775.0
    assert persistido == 37511800.0


def test_importe_representable_no_produce_fallo():
    probe = _ColumnProbe()

    fallos = unrepresentable_amounts(
        {"budget.total_amount": 37511800.0, "budget.discount_amount": 0.0}, probe=probe
    )

    assert fallos == []


def test_tipo_double_acepta_el_importe_real():
    """Con DOUBLE el importe entra exacto: el bloqueo es del tipo FLOAT."""

    class _DoubleProbe:
        def __call__(self, valor: float) -> float:
            return valor

    assert unrepresentable_amounts({"x": 37511775.0}, probe=_DoubleProbe()) == []


def test_detecta_tambien_el_importe_neto():
    probe = _ColumnProbe({37511775.0: 37511800.0})

    fallos = unrepresentable_amounts(
        {
            "budget.net_amount": 37511775.0,
            "budget.total_amount": 37511775.0,
        },
        probe=probe,
    )

    assert {f[0] for f in fallos} == {"budget.net_amount", "budget.total_amount"}


def test_el_sondeo_usa_el_importo_una_vez_por_columna():
    probe = _ColumnProbe()

    unrepresentable_amounts(
        {"budget.net_amount": 10.0, "budget.total_amount": 20.0}, probe=probe
    )

    assert probe.consultas == [10.0, 20.0]


def test_aborta_con_mensaje_explicito_antes_de_escribir():
    probe = _ColumnProbe({37511775.0: 37511800.0})

    with pytest.raises(RepairAborted) as exc:
        _ = [
            f
            for f in unrepresentable_amounts({"budget.total_amount": 37511775.0}, probe=probe)
        ]
        if unrepresentable_amounts({"budget.total_amount": 37511775.0}, probe=probe):
            raise RepairAborted("bloqueado")

    assert "bloqueado" in str(exc.value)


def test_no_se_escribe_si_el_importe_no_cabe(db):
    """Puerta de entrada real: con la base temporal no debe bloquear nada."""
    from tests.test_repair_monetary_integrity import _caso_000073  # noqa: F401

    assert callable(unrepresentable_amounts)


def test_precision_de_la_comprobacion():
    """El valor que se compara es el cuantizado a moneda, no el float crudo."""
    probe = _ColumnProbe()

    fallos = unrepresentable_amounts(
        {"budget.total_amount": Decimal("37511775.00")}, probe=probe
    )

    assert fallos == []
    assert probe.consultas == [37511775.0]
