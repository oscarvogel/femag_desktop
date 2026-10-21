# Importación DBF: la pantalla se aplastaba en pantallas bajas

Registro del 21/10/2026. Issue **#748**, reportado por el cliente con la versión
`2026.10.20.18.55.30` en la máquina donde se iba a hacer la importación de los
maestros.

## El síntoma

En la pantalla **Importación -> Importación DBF** las filas del formulario se
superponían: los campos de ruta y los botones "Examinar" quedaban encimados
entre sí, y las etiquetas ("Clientes", "Transportistas", ...) se apilaban una
sobre otra. En la práctica no se podía elegir un archivo para importar.

## La causa

La página mide **~1290 px de alto** y se agregaba **directamente** al
`QStackedWidget` de la ventana (`self.stack`), sin `QScrollArea`. Cuando la
ventana es más baja que el mínimo de la página, Qt no achica el contenido: le
**comprime los layouts**, y los widgets hijos se salen de la caja que los
contiene.

Medido sobre el código anterior (ventana forzada a 1366x768):

| bloque | alto que recibía | alto que necesita |
|---|---|---|
| `QFrame#formSection` (maestros) | 26 px | 348 px |
| `QGroupBox` Referencia DGR | 26 px | 208 px |

Con 1638x969 (la resolución del cliente) pasaba lo mismo: el bloque de maestros
recibía 43 px para 7 filas.

## El arreglo

1. Un helper `_scrollable_page(page)` que envuelve una página en un
   `QScrollArea` con `setWidgetResizable(True)`, sin marco y sin scroll
   horizontal.
2. La página de Importación DBF se devuelve dentro de ese scroll area.
3. Las dos tablas de resumen quedan con `setMinimumHeight(150)`: dentro del
   área desplazable se llevan el espacio sobrante, pero nunca quedan como una
   franja de 26 px.

Con el scroll, el área desplazable le da a la página el alto que pide (o más),
así que las grillas conservan el alto de fila y **nada se superpone**. El
contenido que sobra se recorre con la barra vertical.

## Validaciones

| validación | resultado |
|---|---|
| `pytest tests/test_issue_748_importacion_dbf_layout.py tests/test_legacy_dbf_import_ui.py` | 8 passed |
| `python -m compileall app` | ok |
| `git diff --check` | ok |
| suite completa | 2 failed, 1840 passed, 3 skipped (10 min) |

Los 2 que fallan son **preexistentes**: `tests/test_issue_736_count_screens_keep_typed_values.py`
fija la fecha `2026-10-21` en el `QDateEdit`, que arranca en la fecha de hoy. Hoy
(21/10) no hay cambio de fecha, no se dispara `dateChanged` y el valor escrito no
se descarta. Fallan todos los días 21/10 y pasan en cualquier otro. Se corrigen
en el issue **#750** (además hay que arreglarlo para poder publicar el release:
`release.ps1` aborta si la suite no sale con exit code 0).

Los tests nuevos fijan el criterio:

- con la ventana en 1366x768, las 7 filas del formulario conservan su alto
  (>= 38 px) y **ninguna fila se superpone con la siguiente**;
- la página conserva su alto dentro del área desplazable y la barra vertical
  tiene recorrido (el contenido no se comprime, se desplaza);
- la barra horizontal está desactivada (la página se adapta al ancho).

## Evidencia visual

`docs/screenshots/issue_748/`: `antes_*` (el defecto, a 1366x768 y a 1638x969) y
`despues_*` (la pantalla usable). Se renderizaron con el plugin de Windows
porque en `offscreen` Qt dibuja los widgets sin texto (issue #652).

## Fuera de alcance

- No se cambió el importador, los modos (`patch`/`overwrite`) ni los
  contadores: la importación sigue siendo la misma.
- No se tocó ninguna otra pantalla. Auditando todas las páginas con la
  ventana en 1366x768 (el área de contenido queda en 1075x610), el patrón
  "página larga sin scroll" aparece además en **Ingreso de materia prima**
  (necesita 703 px) y en **Partes de producción** (necesita 1013 px). Se
  siguen en el issue **#749** para no mezclar alcances en este PR.

## Release

| dato | valor |
|---|---|
| version | `2026.10.21.08.47.41` |
| source_sha | `6b78ee98d1ef3689e63423b59fd2c540a5eb5ce0` |
| SHA256 | `9b5718ca0015d9cb89e8c7db30ec91e91ebc34344c9237f6154ba6a3fc989932` |
| tag candidate | `femag-candidate`, publicado el 2026-10-21 11:49Z |
| tag produccion | `latest`, promovido el 2026-10-21 11:51Z (run `39595021785`) |

En ese build la pantalla ya sale con el area desplazable: instalado en la PC
piloto del canal candidate, con health-check en verde
(`FEMAG production health OK`).

