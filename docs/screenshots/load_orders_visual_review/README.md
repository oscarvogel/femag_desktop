# Evidencia - revision visual Ordenes de carga

Fecha: 2026-06-24
Comando usado:

```powershell
py -3.12 -m app.main --demo-ui
```

Esta carpeta contiene PNGs reales capturados desde una ventana `FEMAG Desktop` abierta en modo demo visual.

## Archivos

- `01_dashboard_base_demo_ui.png`: dashboard/demo UI base con buscador superior, sidebar, acciones principales, contadores en 0 y estado `Sin registros`.
- `02_topbar_sidebar_demo_ui.png`: recorte de la misma ventana para evidenciar titulo, buscador, sidebar y dashboard inicial.

## Resultado

- Computer Use detecto y targeteo la ventana `FEMAG Desktop`.
- La app abrio sin tracebacks ni errores tecnicos visibles.
- La UI base coincide con la pantalla aprobada para dashboard/demo.
- Los accesos `Avisos`, `Ayuda`, `Config` y el usuario `demo_visual / Administrador` fueron confirmados por accesibilidad de Computer Use.

Pendiente explicito: validar la pantalla operativa de Ordenes de carga cuando #56 este implementado.
