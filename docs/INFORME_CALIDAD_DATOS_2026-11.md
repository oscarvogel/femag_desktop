# Informe de calidad de datos — FEMAG

**Para:** Dirección / Dueño

**De:** Equipo de sistemas

**Fecha:** 7 de noviembre de 2026

**Fuente:** copia de seguridad `femag_desktop.sql` (MySQL 5.7), tomada el 7/11/2026 a las 08:56.

**Alcance:** 65 tablas relevadas; 48 con datos y 17 vacías. No se modificó la base ni el sistema. Los importes se expresan en pesos argentinos; **M = millones**.

> **Alcance fiscal:** la facturación se emite en **Holistor**, fuera de FEMAG. Por eso FEMAG no tiene tabla de facturas y las órdenes y presupuestos se manejan con **IVA 0%**: son documentos comerciales, no fiscales. FEMAG lleva la **cuenta corriente operativa** y el puente con Holistor se carga a mano. Este informe no evalúa la facturación fiscal; evalúa los datos operativos de FEMAG y la calidad de ese puente.

---

## Estado de avance — 9 de noviembre de 2026

Esta sección se agregó después de la entrega inicial para reflejar lo corregido y lo que queda del lado del negocio.

**Corregido en producción (versión `2026.11.09.14.59.41`):**

- Se corrigió el movimiento de cuenta corriente con fecha 31/08/2027: quedó en 31/08/2026, sin cambiar el saldo del cliente.
- Se agregó una validación para que los movimientos manuales no acepten fechas a más de 180 días en el futuro.
- Se anularon presupuestos históricos de clientes que ya no estaban en la orden; el flujo nuevo ya lo hace automáticamente.
- Se normalizaron los estados del resumen gerencial y se limpiaron envíos trabados.
- Se clasificaron las advertencias de la importación legacy: 54 esperadas, 119 choferes para asignar transportista y 1 fila con dato faltante.

**Pendiente del negocio:**

- Producción real, inventario físico y trazabilidad de lote (prioridad 90 días).
- Conciliación estructurada FEMAG ↔ Holistor.
- Completar maestros: vendedor, provincia, teléfono y carga máxima de camiones.
- Mantener el rinde medido separado del estimado en los reportes.

**Nota:** los importes y hallazgos de este informe corresponden al corte del 7/11/2026. Las correcciones posteriores están reflejadas en esta sección.

---

## 1. Resumen para el dueño

**En una frase:** el sistema ya cubre bien el circuito comercial y de despacho, y la facturación fiscal vive correctamente en Holistor. Lo que todavía no está instrumentado es **la fábrica**: producción real, inventario físico y trazabilidad de lote. Con los datos actuales se puede gestionar ventas, cobranza operativa y logística; todavía **no** se puede saber con precisión cuánto cuesta producir un kilo, cuánto stock real hay ni qué lote se despachó a cada cliente.

### Lo más importante

1. **No hay datos de producción ni de inventario físico.** Las tablas de producción, consumo, bolsas y conteo de stock están en cero. Producción y stock son prioridad para los próximos 90 días: sin eso no se cierra la cadena materia prima → producción → stock → despacho.
2. **El lote no se registra en producción ni en despacho.** Los ítems de orden y las asignaciones de pallet no tienen lote ni fechas. Si calidad necesita trazabilidad, hay que resolverlo en producción y despacho: **el remito es un documento legal independiente y no debe usarse para eso**.
3. **El puente con Holistor es manual y sin estructura de conciliación.** FEMAG no factura (correcto), pero los comprobantes de Holistor se referencian como texto libre ("FC 2232", "FCE 0070"), hay **ARS 1.602 M** de saldos iniciales cargados como "SALDO" sin comprobante y **ARS 166 M** de IVA/percepciones cargados a mano. No es un error de facturación: es una oportunidad de ordenar la conciliación.
4. **El rinde se mide por muestreo y el 22,33% es una estimación aceptada.** El dato está bien gobernado: el sistema distingue `medido` (205 recepciones, 39% del volumen) de `estimado` (405, 61%). El valor fijo está alineado con el promedio medido (22,30%), pero como el rango real va de 12,74% a 30,28%, no alcanza para comparar proveedores individualmente. Hay que usar el rinde medido para el scorecard y marcar siempre en los informes si el dato es estimado.
5. **Faltan datos maestros que limitan el análisis.** El 84% de los clientes no tiene vendedor, el 87% de las direcciones no tiene provincia y el 99% de los camiones no tiene carga máxima. Sin eso no hay comisiones, rutas, flete por kilo ni ventas por zona confiables.

### Semáforo general

| Dominio | Estado | Motivo principal |
|---|---|---|
| Clientes | 🟠 Mejorar | 84% sin vendedor, 14% sin teléfono, CUIT inválidos y duplicados |
| Productos y precios | 🟠 Mejorar | 4 de 12 sin precio base y 2 sin costo; el IVA 0% es correcto por diseño |
| Órdenes y ventas | 🟠 Mejorar | Cantidades, precios y totales completos; falta lote y fechas de elaboración |
| Despacho y logística | 🟠 Mejorar | Camiones sin carga máxima, choferes sin transportista, pallets sin peso |
| Remitos y F150 | 🟢 Aceptable | Documento legal independiente por diseño; 26/26 con F150 generado |
| Trazabilidad de lote | 🟠 Mejorar | Lote no registrado en producción, ítems de orden ni pallets |
| Cuenta corriente | 🟠 Mejorar | Operativa y bien registrada; el puente con Holistor es manual y sin conciliación estructurada |
| Materia prima | 🟠 Mejorar | Rinde por muestreo aceptado; falta maestro de proveedores y disciplina de reporte |
| Producción e inventario | 🔴 Crítico | Sin registros de producción ni conteos de stock; es prioridad a 90 días |

---

## 2. Qué contiene el sistema hoy

| Módulo | Qué registra | Volumen | Estado |
|---|---|---|---|
| Clientes | Altas, CUIT, condición IVA, domicilios, vendedor | 907 clientes (904 activos), 924 direcciones | Importado en gran parte del sistema anterior (872 clientes) |
| Productos | 12 productos de fécula, almidón y packs | 12 productos | Precio base en 8, costo en 10 |
| Órdenes de carga | Órdenes con destinos múltiples, transportista, chofer y camión | 120 órdenes; 564 ítems; 137.400 unidades; 3.026.515 kg; ARS 4.498 M netos | 96 cerradas, 22 emitidas, 1 anulada, 1 pendiente |
| Presupuestos | Presupuesto por destino, manual o desde orden | 317 presupuestos (292 desde orden, 25 manuales) | Se emiten por destino y también en forma manual |
| Despacho y stock | Movimientos de salida por producto | 156 movimientos; 1.392.305 kg | Sólo desde el 6/10/2026 |
| Remitos | Documento legal independiente de la operación, con datos congelados del cliente, transporte y carga | 26 remitos | Todos emitidos entre 20/10 y 6/11; no se vincula a órdenes por diseño |
| F150 | Archivo para Rentas generado desde el remito | 26 lotes F150 | 26 de 26 remitos con F150 |
| Cuenta corriente | Documentos operativos, pagos, débitos y créditos manuales, saldos | 1.209 movimientos; 392 recibos | Saldo operativo ARS 2.349 M |
| Facturación fiscal | Emitida en **Holistor** | Fuera de FEMAG | Correcto por diseño; FEMAG sólo referencia comprobantes |
| Materia prima | Recepciones de mandioca con bruto, tara, neto, descuentos y rinde | 610 viajes; 3.777.955 kg netos; 147 proveedores | Importado desde `femagfab` hasta el 20/10 |
| Producción | Partes, bolsas, consumo, ingresos internos | 0 registros | Sin uso; prioridad 90 días |
| Inventario físico | Conteos y líneas de conteo | 0 registros | Sin uso; prioridad 90 días |
| Auditoría | Eventos por usuario, módulo, acción y equipo | 5.092 eventos | Activa |

---

## 3. Calidad de datos: hallazgos priorizados

### 3.1 Críticos

#### 3.1.1 No hay producción real ni inventario físico

- `production_part`, `production_bag`, `production_consumption`, `raw_material_intake`, `stock_count` y `stock_count_line` están **vacías**.
- El único stock registrado son **salidas por despacho** (156 movimientos) desde el 6/10/2026.
- No hay entrada de producción terminada, consumo de materia prima, merma, ajuste ni conteo físico.

**Impacto:** no se puede responder cuántas bolsas se produjeron, cuánta fécula quedó en stock, cuánto se perdió ni si el stock del sistema coincide con el depósito. Tampoco se puede calcular el costo real por kilo.

**Prioridad:** es la brecha más importante y ya está en el plan de producción y stock. Debe cerrarse en los próximos 90 días.

### 3.2 Altos

#### 3.2.1 El puente con Holistor es manual y sin conciliación estructurada

- **No es un error que FEMAG no facture:** la facturación se emite en Holistor y el IVA 0% de órdenes y presupuestos es correcto porque son documentos comerciales, no fiscales.
- El problema es **cómo se refleja Holistor en FEMAG**:
  - **42 débitos manuales** referencian comprobantes externos como texto libre ("FC 2232", "FCE 0070", "FC 2244"), por **ARS 229,7 M**.
  - **112 movimientos "SALDO"** por **ARS 1.602 M** de saldos iniciales, sin un campo estructurado de comprobante.
  - **35 débitos por IVA/percepciones** por **ARS 166 M**, también como texto libre ("IVA 21%", "IVA - PERC. IVA - PERC. IIBB MNES").
  - La cuenta corriente tiene 1.209 movimientos, pero sólo 412 tienen el campo de referencia cargado y no existe una tabla de comprobantes fiscales.

**Impacto:** la conciliación entre FEMAG y Holistor depende de una persona y de leer textos. Se pueden duplicar u omitir documentos, y no hay un reporte automático de diferencias.

**Recomendación:** mantener la facturación en Holistor y construir una **conciliación estructurada FEMAG ↔ Holistor**: tipo de comprobante, punto de venta, número, fecha, importe neto, IVA, percepciones y saldo. Con un reporte mensual de diferencias y un responsable definido. No se propone facturar desde FEMAG.

#### 3.2.2 El rinde se mide por muestreo: el dato es válido, pero hay que gobernarlo

- **610 recepciones**, **3.777.955 kg netos**, **3.742.048 kg liquidables**.
- **205 recepciones (1.458.256 kg, 39% del volumen)** tienen rinde **medido**: promedio **22,30%**, con un rango real de **12,74% a 30,28%**.
- **405 recepciones (2.283.792 kg, 61% del volumen)** tienen rinde **estimado** con un valor fijo de **22,33%**.
- El sistema **sí distingue** el origen (`yield_source = measured / estimated`), lo cual es una buena práctica.
- El valor fijo está bien calibrado contra el promedio medido (22,33% vs 22,30%), pero el rango por camión es muy amplio.

**Impacto:** el 22,33% sirve para costeo global y para el pago corriente, pero **no permite comparar proveedores individualmente**. Un proveedor que rinde 13% y otro que rinde 30% pueden terminar con el mismo rinde estimado si no se usa la muestra.

**Recomendación:** usar el rinde **medido** para el scorecard y las decisiones por proveedor; marcar siempre en los informes si el dato es estimado; y revisar periódicamente el 22,33% contra el promedio medido. No hace falta medir todos los camiones: alcanza con que el reporte no mezcle estimado y medido sin avisar.

#### 3.2.3 El stock histórico no está completo

- Los movimientos de stock comienzan el **6/10/2026**.
- Hay **62 órdenes anteriores** a esa fecha sin movimiento de stock.
- Total despachado según ítems: **3.026.515 kg**. Total en movimientos de stock: **1.392.305 kg (46%)**.
- Desde el 6/10, **57 de 58 órdenes** tienen movimiento; la orden pendiente 120 es la única sin movimiento.

**Impacto:** cualquier informe de stock o de kilos despachados antes del 6/10 va a estar incompleto. Hay que definir una línea base de inventario o completar el histórico.

#### 3.2.4 Maestro de clientes incompleto

- **764 de 907 clientes (84,2%)** no tienen vendedor asignado.
- **131 clientes (14,4%)** no tienen teléfono; **40 (4,4%)** no tienen email ni contacto.
- **13 clientes** tienen CUIT inválido o vacío; **17** tienen CUIT con formato inconsistente (guiones/espacios).
- **8 pares de clientes están duplicados** por CUIT normalizado: BAREIRO JAVIER, GUIZZETTI MARÍA DE LOS ÁNGELES, GIMÉNEZ ROMINA JAQUELINE, MIRANDA ZURITA EPIFANIO, MUSLI WOLKEN S.A., BUENOS ALIMENTOS, CÓDIGO ANIMAL S.R.L. y PRINWEY ALIMENTOS / PANYMAX (mismo CUIT, distinto nombre).
- **18 registros** comparten nombre con otro cliente.
- Sólo **205 de 907 clientes (22,6%)** compraron en el período.

**Impacto:** no se pueden liquidar comisiones, segmentar cartera, hacer campañas ni analizar por zona con confianza.

#### 3.2.5 Datos logísticos incompletos

| Dato | Faltante |
|---|---|
| Camiones sin carga máxima (`max_load_kg`) | **107 de 108 (99,1%)** |
| Choferes sin transportista | **98 de 147 (66,7%)** |
| Direcciones sin provincia | **807 de 924 (87,3%)** |
| Direcciones sin localidad | **31 de 924 (3,4%)** |
| Clientes sin ningún domicilio | **9** |
| Camiones sin acoplado | **14 de 108 (13,0%)** |
| Choferes sin documento | **18 de 147 (12,2%)** |
| Choferes sin teléfono | **23 de 147 (15,6%)** |

**Impacto:** no se puede calcular utilización de camiones, costo por kilo, rutas por provincia ni validar bien el F150.

#### 3.2.6 Pallets sin peso/tipo y lote no registrado en la operación

- **2.101 pallets** en 119 órdenes.
- `weight` = **0 en todos**; `measure` vacío en todos; `pallet_type_id` nulo en todos; `quantity` = 1 en todos.
- El peso promedio implícito por pallet, calculado desde los ítems, es **~1.440 kg**, pero ese dato no está grabado.
- Las asignaciones de pallet tienen cantidad y peso unitario, pero **no tienen lote**.
- En los ítems de orden, **563 de 564** no tienen lote y **564** no tienen fecha de envasado.
- **El remito queda afuera de este punto por diseño:** es un documento legal independiente y no debe cargar lote ni vincularse a la orden.

**Impacto:** si calidad necesita trazabilidad, hoy no se puede reconstruir lote → pallet → despacho → cliente. El pallet tampoco sirve para flete o inventario; sólo cuenta bultos.

### 3.3 Medios

- **Productos sin precio base:** 4 de 12 (`BOL FECULA 2°CALIDAD`, `BOLSAS DE FECULA X 500 GRS`, `BOLSAS FECULA NATIVA 2º CALIDAD`, `PACK X 10 UNID. X 1 KG. MOL.GRÖN`). Uno de ellos igual se vendió (producto 32, 1.200 unidades).
- **Productos sin costo unitario:** 2 de 12.
- **Sin maestro de proveedores:** los 147 proveedores de materia prima viven como texto dentro de la recepción. Hay nombres como `TRANSPORTE GALGO` (transportista, no productor), un proveedor `"."` y 75 nombres de una sola palabra (`SILVERIO` concentra 74 viajes y 306.929 kg). Esto limita el scorecard de proveedores.

### 3.4 Lo que está bien (no perderlo)

- **Órdenes completas:** 120 de 120 con ítems, destino y precios; sin cantidades negativas ni precios cero.
- **Remitos completos:** 26 de 26 con cliente, CUIT, domicilio, transportista, chofer y camión; 26 de 26 con F150 generado. Es un documento legal independiente de la operación por diseño.
- **Pagos con detalle:** 392 recibos con detalle de medios de pago; sólo diferencias mínimas.
- **Trazabilidad contable operativa:** 378 movimientos documentales vinculados a órdenes, 393 vinculados a pagos y 305 a presupuestos.
- **Gobierno del rinde:** el sistema distingue explícitamente rinde medido y estimado (`yield_source`).
- **Alcance fiscal claro:** la facturación está en Holistor y FEMAG no la duplica; el IVA 0% de los documentos comerciales es correcto.
- **Auditoría activa:** 5.092 eventos con módulo, acción, usuario y equipo.
- **Recepciones completas en pesos:** 100% con bruto, tara, neto, kg liquidables y descuentos.
- **Clientes y productos con nombre:** 100% completos; 904 de 907 clientes activos.

---

## 4. Qué datos estamos sacando hoy

Con la información actual se pueden obtener estos informes:

1. **Ventas netas por período, producto, cliente y destino.** Valor neto de órdenes: **ARS 4.498 M**, **137.400 unidades**, **3.026.515 kg** (sep–nov). Son valores comerciales, sin IVA y sin validez fiscal.
2. **Concentración comercial.** El principal cliente representa **16,3%** de la venta; los tres primeros, **32,5%**. Fécula nativa: **75,2%** de la venta.
3. **Órdenes de carga y estado** (pendiente, emitida, cerrada, anulada), con transportista, chofer, camión y destinos múltiples.
4. **Presupuestos por destino** y su estado (aplicado a cuenta corriente, etc.).
5. **Remitos emitidos y F150 generados** (26 de cada uno desde el 20/10). Son documentos legales independientes de la operación, por diseño.
6. **Cuenta corriente operativa por cliente:** saldo, movimientos, recibos, débitos/créditos manuales y antigüedad por vencimiento. Los comprobantes fiscales se emiten en Holistor y se referencian manualmente.
7. **Cobranza:** 392 recibos, con detalle por medio de pago. Neto de la anulación por error de tipeo (ARS 2.910 M), la cobranza registrada es **ARS 3.563 M**.
8. **Stock de despacho desde el 6/10:** 1.392.305 kg.
9. **Recepciones de materia prima importadas:** 610 viajes, kilos, descuentos, rinde (medido o estimado) y fécula teórica.
10. **Reporte gerencial diario** por WhatsApp.
11. **Auditoría de operaciones** por usuario y módulo.

### Lo que hoy no se puede responder con confianza

- ¿Cuánto cuesta producir un kilo o una bolsa?
- ¿Cuánto stock real hay en el depósito?
- ¿Qué lote se despachó a qué cliente?
- ¿Cuánto vendió cada vendedor o cada zona?
- ¿Cuántos kilos se despacharon antes del 6/10?
- ¿La cuenta corriente de FEMAG coincide con Holistor y por qué no?

---

## 5. Qué datos vamos a poder obtener cuando se corrija

| Dato / indicador | Para qué sirve | Qué hay que corregir |
|---|---|---|
| Costo real por kg y por bolsa | Margen por producto, cliente y canal; decisiones de precio | Producción real, consumo, merma y costo de materia prima medido |
| Inventario real y valorizado | Evitar quiebres y diferencias de depósito | Conteos físicos y movimientos de ingreso/ajuste |
| Trazabilidad de lote en producción → pallet → despacho → cliente | Recall, reclamos de calidad, requisitos alimentarios | Lote y fechas en producción, ítems de orden y pallets (el remito queda aparte) |
| Rinde medido por proveedor y variedad | Scorecard, precio por rinde, detección de proveedores de baja calidad | Usar la muestra para el scorecard; marcar estimado vs medido en los reportes |
| Ventas por vendedor y zona | Comisiones, objetivos, cartera | Asignar vendedor a los 764 clientes y provincia a los domicilios |
| Antigüedad de deuda y cobranza proyectada | Flujo de caja y gestión de cobranza | Saldos iniciales con respaldo, referencias estructuradas y vencimientos confiables |
| Conciliación FEMAG ↔ Holistor | Cerrar diferencias de documentos, IVA, percepciones y saldos | Referencia estructurada de comprobante y reporte mensual de diferencias |
| KPIs logísticos: kg/viaje, costo/kg, uso de camión y pallet | Reducir flete y mejorar carga | Carga máxima de camiones, peso/tipo de pallet y transportista por chofer |
| Planificación de producción vs demanda | Compras, turnos y capacidad | Producción real y stock actualizado |
| Tablero diario/semanal para dirección | Gestión con datos confiables | Cerrar los puntos anteriores y definir una única fuente de cálculo |

---

## 6. Plan de acción recomendado

### Fase 0 — Ordenar la casa (0 a 30 días)

Objetivo: dejar los maestros confiables y definir las reglas de negocio que hoy están ambiguas.

| Acción | Responsable | Criterio de aceptación |
|---|---|---|
| Unificar los 8 clientes duplicados y completar los CUIT faltantes | Administración | 0 clientes duplicados; 100% con CUIT |
| Completar vendedor, teléfono, email y provincia/localidad de clientes | Comercial | 90% de clientes activos con vendedor y provincia |
| Crear maestro de proveedores y migrar los 147 | Compras | 100% de recepciones vinculadas a un proveedor con código |
| Definir la interfaz de conciliación con Holistor: campos de referencia, responsable y frecuencia | Administración | Proceso documentado y reporte de diferencias mensual |
| Completar carga máxima de camiones y transportista de choferes | Logística | 90% de camiones y choferes con dato |
| Definir línea base de stock al 6/10 o completar histórico | Administración / Depósito | Stock inicial documentado y aprobado |
| Acordar con Producción que los informes distingan medido vs estimado | Producción | 0 reportes que mezclen ambos sin aviso |

### Fase 1 — Cerrar el circuito (30 a 90 días)

Objetivo: que la fábrica quede registrada de punta a punta.

| Acción | Criterio de aceptación |
|---|---|
| Activar producción real: partes, bolsas producidas y consumo | Producción diaria registrada por turno/lote |
| Activar conteos de stock y ajustes | Al menos 1 conteo mensual con diferencias explicadas |
| Registrar lote y fechas en producción, ítems de orden y pallets, si calidad lo requiere | 100% de los despachos que requieran trazabilidad con lote |
| Mantener el remito como documento legal independiente y documentar esa decisión | El remito no se vincula a la operación ni carga lote |
| Registrar peso y tipo de pallet | 100% de pallets con peso y tipo |
| Implementar conciliación estructurada FEMAG ↔ Holistor | Reporte mensual de diferencias por comprobante, IVA y percepción |
| Tablero gerencial v1: ventas, cobranza, logística y materia prima | Tablero disponible con definiciones únicas |

### Fase 2 — Gobernar y analizar (90 a 180 días)

Objetivo: que los datos se mantengan confiables y se usen para decidir.

| Acción | Criterio de aceptación |
|---|---|
| Definir un responsable de datos maestros por área (comercial, compras, logística, producción) | Cada maestro tiene un dueño y una revisión mensual |
| Costeo y margen por producto/cliente/canal | Margen calculado y conciliado con contabilidad |
| Scorecard de proveedores con rinde medido | Ranking mensual usado en compras |
| Congelar el sistema anterior y dejar una única fuente | 0 importaciones DBF nuevas |
| Analítica de demanda, recompra y rentabilidad | Informes usados en la reunión mensual |

### Metas de calidad a 90 días

| Indicador | Hoy | Meta |
|---|---|---|
| Producción diaria registrada | 0% | 100% de los turnos |
| Conteo físico de stock | 0 | 1 conteo mensual |
| Clientes con vendedor | 15,8% | 90% |
| Direcciones con provincia | 12,7% | 95% |
| Camiones con carga máxima | 0,9% | 90% |
| Documentación legal remito + F150 | 100% | 100% (mantener) |
| Trazabilidad de lote (si calidad la requiere) | 0,2% en ítems de orden | 100% de los despachos que la requieran |
| Pallets con peso | 0% | 100% |
| Recepciones con origen de rinde identificado | 100% (ya está) | 100%, y 0 informes que mezclen sin aviso |
| Comprobantes/impuestos con referencia a Holistor | 77 movimientos, en texto libre | 100% con tipo, número, fecha e importe |

---

## 7. Anexo A — Cómo se midió

Se trabajó sobre una copia de la base, sin conectarse al sistema en producción. Se parsearon las 65 tablas del volcado y se calcularon métricas de:

- **Completitud:** campos vacíos o nulos sobre el total.
- **Validez:** formato de CUIT, fechas, estados y valores permitidos.
- **Consistencia:** órdenes vs ítems vs presupuestos vs cuenta corriente vs stock.
- **Unicidad:** CUIT y nombres duplicados; códigos repetidos.
- **Oportunidad:** fechas futuras, cortes de módulos y datos desactualizados.
- **Trazabilidad:** vínculos entre orden, lote, pallet, pago y comprobante; y la emisión legal de remito/F150.

**Nota:** los importes son valores netos registrados en las órdenes; no incluyen IVA ni representan facturación fiscal. La facturación fiscal se emite en Holistor y quedó fuera del alcance. El análisis no modifica datos ni reemplaza una auditoría contable.

---

## 8. Anexo B — Detalle de tablas principales

| Tabla | Filas | Uso |
|---|---:|---|
| `client` | 907 | Maestro de clientes |
| `clientaddress` | 924 | Domicilios fiscales y de entrega |
| `product` | 12 | Productos y precios |
| `loadorder` | 120 | Órdenes de carga |
| `loadorderproduct` | 564 | Ítems de orden |
| `loadorderdestination` | 379 | Destinos por orden |
| `loadorderpallet` | 2.101 | Pallets |
| `loadorderpalletallocation` | 2.161 | Asignación de producto a pallet |
| `budget` | 317 | Presupuestos |
| `budgetitem` | 472 | Ítems de presupuesto |
| `loadorderbudgetstatus` | 385 | Estado de presupuesto por orden/cliente |
| `loadorderclosure` | 96 | Cierres de orden |
| `loadorderstatushistory` | 336 | Historial de estados |
| `remittance` | 26 | Remitos |
| `remittanceitem` | 34 | Ítems de remito |
| `f150batch` | 26 | Lotes F150 |
| `f150batchremittance` | 26 | Relación F150/remito |
| `clientpayment` | 392 | Recibos |
| `clientpaymentdetail` | 458 | Detalle de medios de pago |
| `clientaccountmovement` | 1.209 | Cuenta corriente operativa |
| `raw_material_receipt` | 610 | Recepciones de mandioca |
| `stock_movement` | 156 | Movimientos de stock |
| `driver` | 147 | Choferes |
| `carrier` | 77 | Transportistas |
| `truck` | 108 | Camiones |
| `salesperson` | 9 | Vendedores |
| `auditlog` | 5.092 | Auditoría |
| `managerialsummarydelivery` | 97 | Envíos del resumen gerencial |

---

## 9. Conclusión

El sistema ya es una buena base para la gestión comercial y de despacho: las órdenes, los presupuestos, los remitos, el F150, los pagos y la cuenta corriente operativa están razonablemente completos y auditados. La facturación fiscal está correctamente separada en Holistor. El problema no es que falten datos de venta ni que el IVA sea 0%: el problema es que **la fábrica todavía no está instrumentada** y que el **puente con Holistor es manual**.

La prioridad no es agregar más pantallas, sino **cerrar tres circuitos**: producción y stock real, trazabilidad de lote (si calidad la requiere) y conciliación estructurada FEMAG ↔ Holistor. Con eso, en 90 días se puede pasar de un sistema que registra despachos a un sistema que explica el negocio de punta a punta.
