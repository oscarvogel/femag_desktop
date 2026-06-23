# Revisión visual Entrega 2 - FEMAG Desktop

Fecha: 2026-06-23
Rama: feature/ui-review-entrega2

## Estado general

La interfaz ya abre en modo gráfico demo, permite iniciar sesión, muestra dashboard, menú lateral, maestros principales, órdenes de carga, bloqueo de chofer y exportación HTML de orden/resumen.

Estado para mostrar al cliente: amarillo. Sirve para una demo interna guiada, pero todavía no como ABM final para secretaría.

## Semáforo

- Verde: login demo, dashboard operativo, menú lateral, placeholders de módulos futuros, datos demo, orden con productos/pallets, bloqueo de chofer, HTML A4 de orden y hoja resumen.
- Amarillo: maestros se ven y se leen, pero son vista de consulta; no hay formularios reales de alta/edición desde esos botones.
- Rojo: no se detectaron bloqueantes que impidan abrir o navegar la app demo.

## Capturas generadas

- `02_dashboard_inicial.png`
- `03_menu_lateral.png`
- `04_ordenes_carga.png`
- `05_clientes.png`
- `06_domicilios.png`
- `07_productos.png`
- `08_menu_lateral_scroll_maestros.png`
- `09_choferes.png`
- `10_transportistas.png`
- `11_camiones.png`
- `12_tipos_pallets.png`
- `13_nueva_orden_formulario_productos_pallets.png`
- `14_chofer_bloqueado_validacion.png`
- `19_login_post_fix.png`
- `20_dashboard_post_fix.png`
- `21_clientes_post_fix.png`

## Impresión/exportación

- `exports/orden_carga_1.html`
- `exports/hoja_resumen_1.html`
- `exports/orden_y_resumen_1.html`

## Hallazgos

### Bloqueantes

Ninguno en el modo demo agregado.

### Importantes

- La app no tenía un modo gráfico lanzable desde `python -m app.main`; se agregó `--demo` para revisión visual sin tocar MySQL real.
- Los ABM todavía no son ABM completos en pantalla: por ahora son vistas de consulta con búsqueda y actualización.
- La pantalla de órdenes permite validar el flujo base, pero el formulario todavía es compacto/provisorio y no filtra domicilios por cliente.

### Menores

- Las tablas inicialmente mostraban encabezados técnicos en inglés y columnas truncadas; se ajustaron a español y ancho completo.
- El menú lateral inicialmente mostraba scroll horizontal y textos cortados; se desactivó el scroll horizontal y se mejoró la lectura.
- Se quitaron botones Nuevo/Editar de las vistas de consulta para no prometer acciones no implementadas.

## Correcciones realizadas

- `scripts/seed_demo_data.py`: seed demo idempotente con usuarios, clientes, domicilios, productos, choferes, transportistas, camiones, pallets y una orden activa.
- `app.main`: nuevo `--demo`, `--demo-db` y `--no-show`.
- `app/ui/login_window.py`: login Qt real con usuario demo y error amigable.
- `app/ui/main_window.py`: dashboard, menú, vistas de consulta, órdenes de carga, bloqueo de chofer y exportación.
- `tests/test_demo_runtime.py`: cobertura del seed demo y del arranque demo sin ventana.

## Validación visual

Se abrió FEMAG con Computer Use, se inició sesión con `secretaria/demo`, se recorrió dashboard, menú, maestros, órdenes, bloqueo de chofer y se repitió una navegación básica luego de las correcciones.

## Validaciones técnicas

- `python -m pytest` -> 28 passed
- `python -m compileall app` -> OK
- `python -m app.main --smoke` -> FEMAG smoke OK
