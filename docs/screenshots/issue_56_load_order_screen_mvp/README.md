# Evidencia visual - Issue #56

Fecha: 2026-06-24
Rama: `codex/issue-56-load-order-screen-mvp`
Comando:

```powershell
py -3.12 -m app.main --demo-ui
```

## Capturas

- `01_load_orders_mvp_empty_form.png`: pantalla real `FEMAG Desktop` en el modulo `Ordenes de carga`, con KPIs, filtros, formulario MVP, boton `Guardar orden`, acciones `Nuevo`, `Emitir`, `Anular` y tabla operativa vacia.

## Validacion visual

- Computer Use targeteo la ventana `FEMAG Desktop`.
- Computer Use navego desde Dashboard hasta `Ordenes de carga`.
- El arbol accesible confirmo campos de cliente, domicilio de entrega, transportista, camion, chofer, producto y cantidad.
- No se observaron tracebacks ni errores tecnicos visibles.
- La captura PNG fue tomada desde la ventana real usando Win32/PrintWindow porque Windows Graphics Capture devolvio `0x80004002` en esta sesion.

Fuera de alcance confirmado: no se implementa impresion, remitos, F150, cuenta corriente ni importaciones.
