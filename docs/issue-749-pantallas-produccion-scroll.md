# Las pantallas de Producción se aplastaban en pantallas bajas

Registro del 21/10/2026. Issue **#749**, abierto junto con el #748.

## El problema

*Ingreso de materia prima* y *Partes de producción* se agregaban directo al
`QStackedWidget` de la ventana. Con la ventana en 1366x768 (el área de
contenido queda en 1075x610) las dos páginas son más altas que eso, así que Qt
comprimía los layouts y sus filas quedaban superpuestas.

Medido sobre el código anterior:

| pantalla | alto que necesita | alto que tenía |
|---|---|---|
| Ingreso de materia prima | 703 px | 610 px |
| Partes de producción | 1013 px | 610 px |

## El arreglo

**1. Área desplazable.** Las dos páginas van dentro de un `QScrollArea`
(`_scrollable_page()` de `app/ui/desktop_app.py`), como la de Importación DBF
del #748. El contenido conserva su alto y el operador lo recorre con la barra
vertical.

Cada área lleva su propio nombre de objeto (`rawMaterialIntakeScrollArea`,
`productionPartsScrollArea`): con el mismo nombre, un `findChild` devuelve la
primera y las pruebas miden la pantalla equivocada.

**2. Word wrap en los textos largos.** Este fue el detalle que apareció al
probar: dentro del área desplazable, *Partes de producción* quedaba **más
ancha que la ventana** (1627 px) y lo de la derecha se perdía, sin barra
horizontal con la que llegar.

La causa: los `QLabel` de los textos largos de estas dos pantallas no tenían
`setWordWrap(True)`, así que cada uno imponía su ancho de texto como ancho
mínimo (1571 px el subtítulo, 1026 px el aviso de peso, 966 px el aviso de
materia prima). El resto de las pantallas del repo lo tiene
(`customer_ledger`, `audit_query_page`, `f150`, ...); estas dos lo habían
olvidado.

Con el word wrap, el ancho mínimo de la página pasó de 1627 px a 512 px: entra
en la ventana y no se corta nada.

## Validaciones

| validación | resultado |
|---|---|
| `pytest tests/test_issue_749_pantallas_produccion_scroll.py -q` | 4 passed |
| `pytest` de las pantallas de producción y de la de DBF | 53 passed |
| `python -m compileall app` | ok |
| `python -m pytest -q` | ver el PR |

Los tests nuevos fijan el criterio:

- las dos páginas están dentro de un área desplazable y con la ventana chica
  tienen recorrido vertical;
- el contenido **entra** en el ancho del viewport (no se corta de un lado);
- los textos largos hacen word wrap y no imponen un ancho mínimo de 400 px o
  más;
- con la ventana en 1366x768, las filas del formulario conservan su alto y no
  se superponen.

## Evidencia visual

`docs/screenshots/issue_749/`: `antes_*` y `despues_*` de las dos pantallas, a
1366x768 y a 1638x969.

## Auditoría del resto de las pantallas

Con el fix, ninguna de las 27 pantallas del stack queda comprimida a 1366x768:
las que lo estaban son ahora áreas desplazables y el resto entra.

| pantalla | alto que necesita | estado |
|---|---|---|
| dashboard | 948 px | ya tenía scroll |
| Importación DBF | 1321 px | scroll (#748) |
| Ingreso de materia prima | 703 px | scroll (este PR) |
| Partes de producción | 1013 px | scroll (este PR) |
| las otras 23 | <= 610 px | entran |

## Fuera de alcance

- No se cambió el comportamiento de las pantallas: ni la carga de materia
  prima, ni el registro de partes, ni los cálculos.
- No se tocó ninguna otra pantalla.
