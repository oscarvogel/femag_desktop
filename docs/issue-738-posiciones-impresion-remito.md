# Issue #738 — Posiciones de impresión del remito: domicilio, CUIT, IVA y detalle

- **GitHub:** https://github.com/oscarvogel/femag_desktop/issues/738
- **PR:** https://github.com/oscarvogel/femag_desktop/pull/739 (squash, `1ffeccc`)
- **Estado:** mergeado a `main` y publicado como candidate `2026.10.20.14.38.48`
- **Rama:** `fix/issue-738-remito-print-positions`
- **Registrado:** 2026-10-20
- **Alcance:** solo coordenadas de impresión del remito. No se toco emision, talonario, F150 ni datos.

## Contexto

El operador pidio corregir la impresion del remito sobre el talonario preimpreso: el
domicilio quedaba pisado por un renglon del formulario, y el CUIT, el IVA y el inicio
del detalle tambien.

## Que cambio

Solo `RemittancePrintTemplate` en `app/services/remittance_print_service.py`. Las
coordenadas estan en milimetros sobre la base de la hoja A4 (eje Y desde abajo). El
desplazamiento global de 5 pt que aplica `_text()` a todos los campos (excepto la
fecha) se mantiene: las posiciones de la tabla ya son las impresas.

| Campo | Antes | Ahora | Desplazamiento |
|---|---|---|---|
| domicilio (direccion) | 223 mm | 228 mm | +5 mm |
| ciudad | 223 mm | 228 mm | +5 mm |
| provincia | 223 mm | 228 mm | +5 mm |
| CUIT del cliente | 212 mm | 222 mm | +10 mm |
| condicion de IVA | 202 mm | 212 mm | +10 mm |
| detalle (primer renglon) | 186 mm | 196 mm | +10 mm |

La linea del domicilio sube **completa**: direccion, ciudad y provincia comparten
baseline, asi que mover solo una dejaba la linea rota.

Sin cambios: fecha (264), cliente (234), documento (207), transportista y patente (58),
chofer (47), paso entre renglones del detalle (7,2 mm) y maximo de renglones (16).

Ademas, `export_preview` reacomodó los rectangulos de referencia: el inicio del
detalle ahora cae por encima del borde inferior del bloque de cliente, y el esquema
habria quedado mostrando un renglon arriba del lugar donde lo dibuja.

## Validaciones

- `python -m pytest tests/test_remittance_ui.py -q` -> 30 passed.
- `python -m pytest` (suite completa) -> **1763 passed, 3 skipped**.
- `git diff --check` -> limpio.
- `python -m compileall app scripts/render_remito_print_evidence.py` -> sin errores.
- CI del PR #739: `Tests, compile and smoke` OK (4m45s) y
  `Windows frozen EXE and installer smoke` OK (13m36s).
- Artefacto del candidate: `--smoke` OK, `--production-health-check` OK
  (config, logging, models, ui-components, pyqt, database-readonly), sin secretos ni
  configuracion en el artefacto, y el SHA256 publicado coincide con el del manifiesto.

## Herramienta nueva

`scripts/render_remito_print_evidence.py` renderiza el preimpreso y la vista previa
del layout anterior y del actual (PDF y PNG) e imprime la tabla de posiciones en mm.
Sirve para las proximas rondas de ajuste milimetrico, sin tener que volver a
calcular las coordenadas a mano.

```bash
python scripts/render_remito_print_evidence.py docs/prints/issue_738_remito_posiciones
```

`docs/prints/` esta en `.gitignore`: la evidencia renderizada queda local y no se
versiona. Requiere `pymupdf`.

## Candidate publicado

- **Version:** `2026.10.20.14.38.48`
- **SHA256:** `43e404a06c6d7414a0a7cf7de11622a0b549512d7a609c624ff701cb05332cf7`
- **source_sha:** `1ffeccc0890d16d428025c5211bd33a30de87d0d` (`main` con el merge de #739)
- **source_dirty:** `false`
- **Canal:** `femag-candidate` en `oscarvogel/vogel-releases`
  (`apps/femag/candidate.json`)

## Pendientes (operativos)

1. **Imprimir un remito de prueba sobre el talonario real.** Este es el unico
   pendiente que importa: las posiciones se validaron contra el PDF preimpreso y la
   vista previa, no contra una hoja del formulario. Hay que confirmar que ningun
   valor pisa un renglon preimpreso.
2. **Revisar el bloque de detalle.** Sube 10 mm; con 16 renglones el ultimo queda en
   88 mm, por encima del bloque de transporte (58 mm), pero se reduce el espacio
   libre entre el detalle y el transporte.
3. **Promover a produccion** cuando el operador confirme la impresion:
   `scripts/publish_femag_release.ps1 -Mode promote -Confirmation PROMOTE`.

> Nota de entorno (este puesto): `pytest` sin `--basetemp` puede terminar con
> `PermissionError` al limpiar el symlink `pytest-current` del TEMP, **aunque los
> tests pasen todos**. Es un problema de permisos de Windows sobre un reparse point
> viejo, no del codigo. Rompe el script de release, que aborta si `pytest` devuelve
> codigo distinto de 0. Workaround: correr con `TEMP`/`TMP` apuntando a una carpeta
> limpia, o `python -m pytest --basetemp=<carpeta del repo>`. En CI el runner no
> tiene el problema.
