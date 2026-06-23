# Revisión visual UX base final

Fecha: 2026-06-23

## Estado visual

La base UX queda en estado presentable para una revisión funcional interna. La app ya no abre conceptualmente sobre un panel vacío: el shell muestra nombre del sistema, subtítulo, usuario, perfil, modo demo/conexión, menú lateral, dashboard operativo y barra inferior.

## Capturas generadas

Las capturas se generaron en `docs/screenshots/ux_base_final/`:

- `01_login.png`: login.
- `02_dashboard_datos_demo.png`: dashboard con datos demo.
- `03_menu_lateral.png`: menú lateral tipo árbol.
- `04_dashboard_accesos_rapidos.png`: accesos rápidos.
- `05_clientes.png`: patrón ABM de clientes.
- `06_productos.png`: patrón ABM de productos.
- `07_choferes.png`: patrón ABM de choferes.
- `08_nueva_orden_carga.png`: nueva orden de carga.
- `09_orden_varios_renglones.png`: orden con varios renglones.
- `10_chofer_ocupado.png`: mensaje de chofer ocupado.
- `11_impresion_a4.png`: impresión A4.
- `12_placeholder_modulo_futuro.png`: placeholder de módulo futuro.

## Observaciones

- El dashboard se entiende como pantalla de trabajo: muestra órdenes del día, pendientes, cerradas, choferes ocupados, último backup y alertas.
- El menú lateral conserva estructura por secciones y deja módulos futuros atenuados en lugar de parecer rotos.
- Los accesos rápidos priorizan acciones reales y muestran mensaje amable para remitos, F150, pagos y cuenta corriente.
- Los ABM comparten buscador, tabla, estado visible, mensaje vacío y campos agrupados.
- La pantalla de órdenes separa datos de carga, transporte, detalle y acciones principales.
- El estado de chofer disponible/ocupado queda visible con texto específico.
- La impresión A4 incluye empresa, título, número, fecha, cliente, destino, transporte, vehículo limpio y apto, tabla, totales, observaciones y firmas.

## Revisión con app abierta

Se abrió `FEMAG Desktop` en modo demo con PyQt y se navegó con Computer Use por:

- Dashboard operativo.
- Clientes.
- Órdenes de carga.
- Placeholder de Generar F150.

La app mostró datos demo, menú lateral, botones de módulos futuros deshabilitados, estado de chofer ocupado y barra inferior sin mensajes técnicos visibles.

## Pendientes UX

- Reemplazar las capturas generadas desde specs por capturas directas persistidas desde el widget PyQt cuando se defina el mecanismo oficial de screenshot.
- Completar la tabla real de detalle por destinatario cuando exista el modelo definitivo de renglones de despacho.
- Ajustar microespaciados finales contra la librería `pyqt5libs` real en una estación con sesión gráfica.
- Validar con usuario operativo si los nombres de menú y columnas coinciden exactamente con el vocabulario de FEMAG.

## Conclusión

La base queda lista para continuar con una revisión puntual y, después de aprobarla, avanzar con módulos nuevos como remitos o F150 sin arrastrar apariencia de prototipo.
