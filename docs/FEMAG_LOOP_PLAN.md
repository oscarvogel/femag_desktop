# Plan FEMAG por loops

Este documento ordena el avance de FEMAG Desktop en loops chicos, trazables y
validables. Loop Engineering es metodologia de trabajo: no agrega funcionalidad
productiva por si misma.

## Estado auditado

- Repo: `oscarvogel/femag_desktop`.
- Checkout local: `O:\dante\femag_desktop`.
- Rama base auditada: `main`.
- Estado de `main`: alineado con `origin/main` en `7d68542` al iniciar este
  plan.
- Rama documental: `codex/femag-loop-plan-roadmap`.
- PRs abiertos relevantes detectados:
  - #53 `docs: define load orders UX flow` (draft, viejo).
  - #40 `Implementar ordenes de carga funcionales` (draft, rama vieja).
  - #39 `Definir UX base profesional de FEMAG Desktop` (draft, viejo).
  - #28 `Implementar menu lateral tipo arbol desde tablas` (abierto).
  - #27 `Ajustar ordenes de carga al formato real FEMAG` (draft, viejo).
  - #26 `Revisar y ajustar UI de Entrega 2` (abierto).
- No trackeados locales previos detectados y fuera de alcance:
  `.codegraph/`, `.cursor/`, `.github/`, `docs/prints/`,
  `docs/screenshots/hotfix_client_abm_demo/`, `femag_manual_integral.sqlite3`,
  `femag_manual_smoke.sqlite3`.

## Correcciones funcionales vigentes

### Remitos

- Remito queda fuera del flujo de Orden de carga / Despacho.
- Remito se genera e imprime en forma individual.
- No debe generarse automaticamente desde una Orden de carga.
- No implementar "crear remito desde orden".
- No acoplar remito al cierre de orden.

### Rendicion de transportistas

- Rendicion no se relaciona con remitos.
- Rendicion se relaciona con pagos y Orden de carga / Despacho.
- No usar remitos como base de rendicion.
- No asumir que un remito dispara una rendicion.
- Si hay documentos impresos, son independientes del circuito de rendicion.

## Estado funcional consolidado

- Proyecto desktop PyQt.
- MySQL/Peewee.
- Shell/sidebar profesional.
- Flujo piloto de Ordenes de carga funcionando.
- Orden pendiente: editar, imprimir pendiente, abrir PDF y botones segun estado.
- Orden emitida: cerrar orden y liberar chofer.
- Modal nueva/editar orden reorganizado.
- Chofer es el dato principal.
- Transportista se autocompleta desde el chofer seleccionado.
- Camion se filtra/relaciona segun el flujo existente.
- ABMs de transporte agrupados bajo `Transporte`:
  - Transportistas.
  - Choferes.
  - Camiones.
- Ultimas validaciones informadas en el pedido:
  - `git diff --check` OK.
  - `py -3.12 -m compileall app` OK.
  - `py -3.12 -m pytest` OK, 102 passed.

## Issues existentes relevantes

| Issue | Estado | Uso en este plan |
| --- | --- | --- |
| #34 `UX-6 - Mejorar diseno imprimible A4 de orden de despacho` | Abierto | Bloque 4. Documento propio de Orden de carga / Despacho, sin remito. |
| #10 `Implementar registro manual de remitos` | Abierto | Bloque 9. Actualizado para depender del diseno independiente de remitos. |
| #12 `Implementar cuenta corriente basica multimoneda de clientes` | Abierto | Implementacion futura; primero disenar #103. |
| #13 `Implementar pagos manuales y recibos numerados` | Abierto | Implementacion futura; primero disenar pagos/despacho #99. |
| #14 `Implementar importacion incremental desde sistema anterior MySQL y DBF` | Abierto | Implementacion futura; primero disenar importacion #104. |
| #11 `Implementar generacion de archivo F150 por lote de remitos` | Abierto | Fuera del plan inmediato. Depende de remitos independientes y definicion fiscal posterior. |
| #16 `Preparar instalacion en servidor y puestos de trabajo` | Abierto | Fuera del roadmap funcional inmediato. |
| #69 `Ordenes de carga - Loop definitivo operativo` | Cerrado | Historico; no reabrir para el nuevo roadmap. |
| #67 `Milestone - Ordenes de carga operativa` | Cerrado | Historico; reemplazado por loops posteriores. |
| #85 `UI/UX: agrupar ABMs de transporte en el sidebar` | Cerrado | Estado consolidado del sidebar Transporte. |

## Issues nuevos creados

| Orden | Issue | Tipo | Objetivo |
| --- | --- | --- | --- |
| 0 | #95 `Tracking - Plan FEMAG por loops corregido` | Tracking | Hilo vivo del roadmap corregido. |
| 1 | #96 `Validar datos maestros minimos para ordenes de carga` | Bug/validacion | Primer loop tecnico recomendado. |
| 2 | #97 `Mejorar seleccion de cliente y lugares de entrega en ordenes` | UX/funcional | Blindar cliente -> lugar de entrega. |
| 3 | #98 `Endurecer relacion Chofer, Transportista y Camion en ordenes` | Bug/regresion | Mantener Chofer como dato principal. |
| 5 | #99 `Disenar pagos vinculados a despacho y transportista` | Diseno | Definir pagos antes de implementarlos. |
| 6 | #100 `Disenar rendicion de transportistas por despacho y pagos` | Diseno | Modelar rendicion sin remitos. |
| 7 | #101 `Implementar rendicion minima de transportistas` | Feature | Implementacion dependiente de #99 y #100. |
| 8 | #102 `Disenar modulo independiente de remitos` | Diseno | Definir remitos individuales, sin Orden ni rendicion. |
| 10 | #103 `Disenar cuenta corriente cliente minima` | Diseno | Definir impactos antes de ampliar #12. |
| 11 | #104 `Disenar importacion inicial de datos desde MySQL y DBF` | Diseno | Mapear fuentes antes de ampliar #14. |
| 12 | #105 `Crear smoke operativo de flujo FEMAG` | Tests/smoke | Validacion transversal reproducible. |

## Orden recomendado de avance

### 0. Tracking y roadmap documental

- Issue: #95.
- PR: este cambio documental.
- Resultado: roadmap e issues alineados.
- No implementa funcionalidad.

### 1. Validar datos maestros minimos para Ordenes de carga

- Issue: #96.
- Objetivo: evitar ordenes incompletas o inconsistentes.
- Casos:
  - Chofer sin transportista asociado.
  - Chofer/transportista inactivo si existe campo de estado.
  - Camion inexistente o no disponible si existe regla.
  - Cliente faltante.
  - Lugar de entrega faltante.
  - Producto faltante o invalido.
  - Fecha vacia o invalida.
  - Cantidad vacia, cero o invalida.
- Validaciones:
  - `git diff --check`.
  - `py -3.12 -m compileall app`.
  - `py -3.12 -m pytest`.
  - Smoke/manual si cambia UI.

### 2. Mejorar cliente y lugares de entrega en Ordenes

- Issue: #97.
- Objetivo: dejar clara la relacion cliente -> lugar de entrega.
- No tocar remitos ni rendiciones.

### 3. Endurecer Chofer -> Transportista -> Camion

- Issue: #98.
- Objetivo: evitar regresiones del flujo Chofer primero.
- Regla: no pedir transportista antes que chofer.

### 4. Documento de Orden de carga / Despacho

- Issue existente: #34.
- Objetivo: mejorar el documento propio de la orden.
- Regla: no generar remito.

### 5. Disenar pagos vinculados a despacho y transportista

- Issue: #99.
- Objetivo: definir estados, vinculos y pantallas antes de ampliar pagos.
- Relacionado con #13 como implementacion futura.

### 6. Disenar rendicion de transportistas por despacho y pagos

- Issue: #100.
- Objetivo: modelar rendicion sin usar remitos.
- Depende de #99.

### 7. Implementar rendicion minima de transportistas

- Issue: #101.
- Depende de #99 y #100.
- No usar remitos.
- No impactar cuenta corriente salvo definicion explicita.

### 8. Disenar modulo independiente de remitos

- Issue: #102.
- Objetivo: definir carga, listado, impresion, numeracion y validaciones.
- Regla: individual, sin Orden de carga y sin rendicion.

### 9. Implementar carga e impresion individual de remitos

- Issue existente: #10.
- Depende de #102.
- Regla: no generar desde orden, no cerrar orden, no aparecer en rendicion.

### 10. Disenar cuenta corriente cliente minima

- Issue: #103.
- Relacionado con #12 como implementacion futura.
- No asumir impacto de remitos.

### 11. Disenar importacion inicial MySQL / DBF

- Issue: #104.
- Relacionado con #14 como implementacion futura.
- No tocar produccion.

### 12. Smoke operativo FEMAG

- Issue: #105.
- Objetivo: comando, script o documento reproducible.
- Debe declarar que modulos cubre y cuales aun no existen.

## Riesgos y dependencias

- Los PRs abiertos viejos (#26, #27, #28, #39, #40, #53) pueden confundir el
  estado del proyecto. Antes de implementar loops nuevos, conviene revisarlos y
  cerrarlos como superseded si ya no aportan cambios validos contra `main`.
- #10, #12, #13 y #14 nacieron desde `plan_implementacion.md` y algunos textos
  eran mas grandes que el loop actual. Deben ejecutarse solo despues del diseno
  correspondiente.
- Remitos, F150, importacion DBF/MySQL, modelos/migraciones y datos demo son
  areas protegidas. No tocarlas sin issue explicito.
- La validacion visual PyQt puede estar limitada por la incompatibilidad de
  captura ya documentada en runs anteriores; si falla, declarar la brecha y no
  venderla como evidencia visual completa.

## Validaciones minimas por loop

Para cada PR funcional, intentar:

```powershell
git diff --check
py -3.12 -m compileall app
py -3.12 -m pytest
```

Agregar smoke o validacion manual segun el tipo de cambio y `VALIDATION.md`.
Si un comando no existe o falla por causa conocida, documentarlo en el PR.

## Criterio de listo del roadmap

Este roadmap queda ordenado cuando:

- existe tracking vivo (#95);
- el primer loop tecnico es #96;
- los disenos previos existen antes de las implementaciones grandes;
- #10 queda corregido como remito independiente;
- el PR documental no toca codigo productivo;
- las validaciones documentales pasan.
