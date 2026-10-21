# El remito pide transporte, camion y acoplado por separado, pero todo sale del chofer

Registro del 21/10/2026. Issue **#756**.

## El problema

El dialogo de remito (`RemittanceDialog`, `app/ui/remittances.py`) tiene tres campos
de transporte: **Transportista**, **Camion** y **Chofer**. Los tres son el mismo
dato visto desde tres angulos, y el sistema ya los tiene relacionados:

| campo de la pantalla | de donde sale |
|---|---|
| Chofer | el que elige el operador |
| Transportista | `Driver.carrier` del chofer |
| Camion | `Driver.usual_truck` del chofer (o el unico camion de su transportista) |
| Acoplado | `Truck.trailer_domain` del camion |

Para emitir un remito el operador tenia que buscar los tres datos por separado
(`RemittanceService.issue` exige transportista con CUIT, camion y chofer), aunque
elegir el chofer los determina a los tres.

El operador lo reporto asi: *"al cargar el remito me pide transporte, camion,
acoplado siendo que todo se relaciona con chofer, al poner el chofer ya el resto de
los datos se deben autocompletar, tal cual tenemos en las ordenes de carga"*.

En las Ordenes de carga esto ya estaba resuelto: `LoadOrderEntryDialog._refresh_from_driver`
arma el bloque de transporte a partir del chofer.

## El arreglo

`RemittanceDialog` ahora tiene la misma cascada que las Ordenes de carga.

**1. El chofer manda.** `driver_combo.currentIndexChanged` dispara
`_refresh_from_driver()`, que:

- busca el chofer y su transportista (`Driver.carrier`);
- deja el combo Transportista en ese transportista;
- deja el combo Camion en el camion habitual del chofer (`Driver.usual_truck`), o
  en el unico camion activo del transportista cuando el chofer no tiene uno;
- el acoplado sigue al camion.

**2. El acoplado sigue al camion, salvo que el operador lo escriba.** La patente
del acoplado se completa con `Truck.trailer_domain` del camion elegido y se
actualiza sola si el operador cambia de camion. Si la escribe a mano, manda la
suya: se escucha `trailer_input.textEdited` y a partir de ahi el autocompletado no
toca mas el campo. Si el operador borra el campo, el autocompletado vuelve a
mandear.

**3. Nada de lo que ya esta cargado se borra.** Elegir "Sin asignar" en el combo
Chofer no toca el transporte que el operador ya cargo a mano, y un chofer sin
transportista o sin camion habitual simplemente no completa nada.

**4. Editar un remito no cambia lo guardado.** Mientras se cargan los datos del
remito (`_load_remittance`) la cascada esta desactivada (`_syncing_transport`), asi
que abrir un borrador no puede pisarle el camion que tiene guardado. La patente
del acoplado tambien se carga despues de los combos, por el mismo motivo.

El combo Chofer lleva un tooltip que explica el comportamiento: *"Elegi el chofer:
el transportista, el camion y el acoplado se completan solos. Si escribis la
patente del acoplado a mano, esa manda."*

## Archivos tocados

| archivo | que cambio |
|---|---|
| `app/ui/remittances.py` | la cascada del chofer, el acoplado que sigue al camion y el resguardo de lo cargado |
| `tests/test_remittance_ui.py` | 7 pruebas del comportamiento nuevo |
| `scripts/generate_issue_756_remito_transport_screenshot.py` | captura de la evidencia visual |
| `docs/screenshots/issue-756-remito-transporte-chofer/` | las dos capturas |

No se toco el modelo de datos, los maestros, la impresion del formulario ni las
reglas de emision del remito.

## Validaciones

| validacion | resultado |
|---|---|
| `python -m pytest tests/test_remittance_ui.py -q` | 37 passed |
| `python -m pytest -q` (suite completa) | 1853 passed, 3 skipped (364 s) |
| `python -m compileall app webapp` | ok, exit 0 |
| `python -m app.main --smoke` | `FEMAG smoke OK`, exit 0 |
| `python scripts/generate_ux_screenshots.py --output-dir <tmp>` | exit 0 (el script es del #178, no cubre remitos) |
| `python scripts/generate_issue_756_remito_transport_screenshot.py` | 2 capturas |

Las 7 pruebas nuevas fijan el criterio:

- elegir el chofer completa transportista, camion y acoplado;
- sin camion habitual, se toma el unico camion del transportista;
- un chofer sin transportista no completa nada y la ayuda del combo lo dice;
- la patente escrita a mano no se pisa cuando el operador cambia de camion;
- "Sin asignar" en el chofer no borra el transporte cargado a mano;
- editar un borrador no cambia el transporte ya guardado;
- lo autocompletado se guarda con el remito.

Nota: `docs/prints/issue_131_load_order_footer_cutoff/load_order_footer_at_min_height.png`
lo regenera `tests/test_load_order_dialog_smoke_131.py` al correr la suite. Se
restauro con `git restore` para que no entre en el PR.

## Evidencia visual

`docs/screenshots/issue-756-remito-transporte-chofer/`:

- `01_remito_sin_chofer.png`: el dialogo con los tres combos en "Sin asignar".
- `02_remito_chofer_completa_transporte.png`: despues de elegir el chofer, con
  Transportista, Camion y Acoplado ya cargados.

## Fuera de alcance

- No se filtraron ni deshabilitaron los combos: el operador puede corregir el
  camion a mano.
- No se cambio el modelo de datos ni la relacion entre chofer, transportista y
  camion.
- No se toco la impresion del formulario ni las reglas de emision.

## Pendientes

- La pantalla de *Remitos* como UX loop completo (esta pantalla esta en la lista
  de candidatas de `docs/LOOP_ENGINEERING.md` y no tiene todavia su
  `docs/ux/remitos.md`). Este PR solo arregla el comportamiento del transporte.
- Si el operador necesita cambiar de camion con frecuencia, se puede evaluar que
  el combo Camion se filtre por el transportista del chofer, como en las Ordenes
  de carga. Queda para un issue aparte con su propio criterio de aceptacion.
