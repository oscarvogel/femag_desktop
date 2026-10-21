# Dos pruebas de conteo fallan todos los dias 21/10

Registro del 21/10/2026. Issue **#751**, encontrado al validar el PR de #748.

## El problema

Dos pruebas de `tests/test_issue_736_count_screens_keep_typed_values.py` fallan
**todos los dias 21/10** y pasan en cualquier otro:

- `test_cambiar_la_fecha_descarta_las_bolsas_escritas`
- `test_el_conteo_fisico_descarta_las_bolsas_al_cambiar_la_fecha`

Hacen esto:

```python
pagina.inputs[producto.id].setValue(40)
pagina.day.setDate(QDate(2026, 10, 21))
assert pagina.inputs[producto.id].value() == 0
```

El `QDateEdit` de la pantalla arranca en `QDate.currentDate()`. Si hoy **es** el
21/10/2026, `setDate(QDate(2026, 10, 21))` no cambia nada: no se emite
`dateChanged`, no se dispara `refresh()` y el valor escrito no se descarta. La
prueba falla.

Es la misma clase de problema que el issue #625 (pruebas que pasan en CI y
fallan en local por fecha).

## Por que era urgente

`release.ps1 candidate` corre `python -m pytest -q` y **aborta si el exit code
no es 0**. Con estas dos pruebas en rojo no se podia publicar ningun release.
El release del 20/10 paso porque ese dia la fecha fija si era distinta de hoy.

## El arreglo

Un helper en el archivo de pruebas:

```python
def _otra_fecha() -> QDate:
    """Una fecha que seguro es distinta de la de hoy."""
    return QDate.currentDate().addDays(1)
```

Las dos pruebas usan esa fecha. Ahora el cambio de fecha siempre ocurre, la
señal `dateChanged` siempre se emite y la prueba sigue comprobando lo mismo:
**al cambiar la fecha de corte, lo que el operador escribio se descarta**.

No se toco el comportamiento de las pantallas de conteo: solo la fecha que
usan las pruebas.

## Validaciones

| validacion | resultado |
|---|---|
| `pytest tests/test_issue_736_count_screens_keep_typed_values.py -q` | 7 passed |
| suite completa | 1842 passed, 3 skipped |
