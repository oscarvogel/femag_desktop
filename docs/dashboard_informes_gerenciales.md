# Dashboard e Informes Gerenciales — FEMAG

## 1. Objetivo

Diseñar e implementar una capa de información gerencial dentro de FEMAG que permita a la dirección obtener una visión rápida, confiable y navegable del estado comercial, financiero y logístico de la empresa.

El objetivo no es reemplazar los módulos operativos existentes, sino consolidar sus datos en indicadores ejecutivos, gráficos e informes detallados que permitan responder preguntas de gestión sin recorrer manualmente órdenes, clientes, cuenta corriente y movimientos.

La solución se divide conceptualmente en dos componentes:

1. **Dashboard Gerencial:** visión ejecutiva, resumida y visual.
2. **Informes Gerenciales:** vistas detalladas, filtrables y exportables que permiten profundizar cada indicador.

---

## 2. Principios de diseño

### 2.1. Una única definición por indicador

Cada KPI debe tener una definición centralizada y reutilizable. El Dashboard y los informes detallados deben consumir la misma lógica para evitar diferencias de cálculo entre pantallas.

Ejemplo: si `Ventas del mes` considera determinadas órdenes y estados, el informe de ventas debe producir exactamente el mismo total al aplicar el mismo período.

### 2.2. Separación entre datos operativos y consultas gerenciales

La lógica de agregación y métricas deberá ubicarse en una capa específica de reportes/servicios y no dentro de la UI.

Estructura sugerida:

```text
app/
  reports/
    dashboard_service.py
    sales_report.py
    account_report.py
    clients_report.py
    products_report.py
    logistics_report.py
```

La implementación final puede variar, pero debe conservarse esta separación conceptual.

### 2.3. Navegación desde resumen hacia detalle

Cada KPI o bloque relevante debe permitir acceder al detalle que lo compone.

Ejemplos:

- `Saldo vencido` → clientes con deuda vencida.
- `Ventas del mes` → detalle de ventas/despachos del período.
- `Top clientes` → detalle del cliente seleccionado.
- `Órdenes pendientes` → listado de órdenes filtrado por estado.

### 2.4. Datos auditables

Toda cifra gerencial debe poder explicarse mediante registros concretos del sistema.

No deben mostrarse métricas cuya composición no pueda rastrearse.

### 2.5. Evitar métricas ambiguas

Antes de implementar cada indicador deberá quedar establecido qué registros participan y cuáles quedan excluidos.

Especial atención a:

- órdenes anuladas;
- órdenes pendientes;
- devoluciones;
- créditos manuales;
- reversas;
- importes documentales versus cobrados;
- cantidades solicitadas versus cantidades efectivamente despachadas.

---

## 3. Dashboard Gerencial

### 3.1. Filtros generales

El Dashboard debe permitir seleccionar rápidamente:

- Hoy.
- Este mes.
- Mes anterior.
- Este año.
- Período personalizado: `Desde / Hasta`.

El período seleccionado debe aplicarse de forma consistente a todos los indicadores dependientes de fecha.

Cuando una métrica represente un saldo a una fecha determinada, deberá aclararse que se trata de una posición y no de un acumulado del período.

---

## 4. KPIs principales

La primera fila del Dashboard debería mostrar al menos seis indicadores grandes.

### 4.1. Ventas / Despachos valorizados

**Objetivo:** mostrar el importe total comercial correspondiente al período.

Datos disponibles actualmente en detalle de órdenes:

- precio neto unitario;
- descuento;
- neto gravado;
- IVA;
- total.

#### Definición propuesta

Inicialmente se considerarán como ventas/despachos las órdenes que ya tengan impacto comercial/documental válido.

Debe definirse durante la implementación exactamente qué estados participan.

Propuesta inicial:

- incluir: `Emitida` y `Cerrada`;
- excluir: `Pendiente`, `Borrador`, `Anulada`.

Esta definición debe validarse operativamente con FEMAG antes de cerrar el KPI.

#### Visualización

- Valor principal: `$ total período`.
- Secundario: variación porcentual respecto del período comparable anterior.

---

### 4.2. Toneladas despachadas

**Objetivo:** medir volumen físico comercializado/despachado.

Debe calcularse preferentemente utilizando kilos efectivamente asignados:

- mercadería en pallets;
- mercadería suelta.

Conversión:

```text
TN = kg / 1000
```

Debe evitarse sumar dos veces una misma mercadería si también existe como línea documental en la orden.

En caso de que existan órdenes históricas sin distribución física completa, deberá definirse una estrategia de fallback controlada.

---

### 4.3. Cantidad de órdenes / cargas

Cantidad de órdenes consideradas válidas dentro del período según la misma regla comercial del Dashboard.

Puede mostrarse adicionalmente:

- Emitidas.
- Cerradas.
- Pendientes.
- Anuladas.

---

### 4.4. Ticket promedio por orden

Fórmula propuesta:

```text
Ticket promedio = Importe total válido / Cantidad de órdenes válidas
```

Las órdenes sin impacto comercial no deben participar.

---

### 4.5. Saldo total de clientes

**Objetivo:** mostrar la exposición total de FEMAG frente a clientes.

Debe calcularse desde los movimientos de cuenta corriente y no desde una suma aislada de órdenes.

Debe respetar:

- saldos iniciales;
- débitos;
- créditos;
- pagos;
- anulaciones/reversas;
- ajustes manuales.

Este KPI representa una posición actual, o una posición a fecha de corte si se implementa consulta histórica.

---

### 4.6. Saldo vencido

**Objetivo:** visualizar cuánto del saldo total ya superó su fecha de vencimiento.

Regla propuesta:

```text
Movimiento pendiente con due_date < fecha de corte
```

Debe definirse correctamente la imputación de pagos para evitar considerar vencido un documento ya cancelado parcial o totalmente.

Visualización sugerida:

- importe vencido;
- porcentaje sobre saldo total;
- cantidad de clientes con deuda vencida.

---

## 5. Indicadores financieros complementarios

### 5.1. A vencer en 7 días

Saldo pendiente cuyo vencimiento ocurra dentro de los próximos 7 días.

### 5.2. A vencer en 15 días

Saldo pendiente dentro de los próximos 15 días.

### 5.3. A vencer en 30 días

Saldo pendiente dentro de los próximos 30 días.

### 5.4. Clientes excedidos de crédito

Si existe límite de crédito configurado para el cliente:

```text
Saldo actual > límite de crédito
```

### 5.5. Clientes próximos al límite

Propuesta inicial:

```text
Saldo actual >= 80 % del límite de crédito
```

El porcentaje debería quedar configurable o al menos centralizado.

### 5.6. Antigüedad de deuda

Agrupar deuda pendiente en bandas:

- No vencida.
- 1–30 días.
- 31–60 días.
- 61–90 días.
- Más de 90 días.

Esta vista es especialmente importante para gerencia.

---

## 6. Gráficos del Dashboard

### 6.1. Evolución mensual

Gráfico de últimos 12 meses con:

- ventas/despachos valorizados;
- opcionalmente toneladas.

Debe permitir detectar tendencia y estacionalidad.

### 6.2. Top clientes

Ranking configurable, inicialmente Top 10.

Medidas posibles:

- facturación / despachos valorizados;
- toneladas;
- cantidad de cargas.

La métrica principal inicial debería ser importe.

### 6.3. Top productos

Ranking por:

- toneladas;
- importe.

### 6.4. Estado de órdenes

Distribución por estados:

- Pendiente.
- Emitida.
- Cerrada.
- Anulada.

### 6.5. Deuda por antigüedad

Visualización de cartera:

- no vencida;
- 1–30;
- 31–60;
- 61–90;
- +90 días.

---

## 7. Comparativos

Siempre que tenga sentido, el Dashboard debería mostrar comparación contra un período equivalente.

### Si se selecciona `Este mes`

Comparar contra mes anterior.

### Si se selecciona `Hoy`

Comparar contra día anterior o mismo día hábil anterior, según definición futura.

### Si se selecciona `Este año`

Comparar contra igual período del año anterior si existen datos suficientes.

### Período personalizado

En una primera versión puede omitirse comparación automática o compararse contra el período inmediatamente anterior de igual duración.

---

# 8. Informe de Ventas / Despachos

## Objetivo

Permitir analizar en detalle todo lo que compone los indicadores comerciales.

## Filtros

- Desde / Hasta.
- Cliente.
- Producto.
- Estado de orden.
- Transportista.
- Chofer.
- Destino.

## Columnas sugeridas

- Fecha.
- N.º orden.
- Estado.
- Cliente.
- Destino.
- Producto.
- Cantidad.
- Unidad.
- Kg.
- TN.
- Precio neto unitario.
- Descuento.
- Neto gravado.
- IVA.
- Total.
- Transportista.
- Camión.
- Chofer.

## Totales

- Cantidad de órdenes.
- Cantidad total.
- Kg.
- TN.
- Neto.
- IVA.
- Total.

## Acciones

- Ver orden.
- Exportar Excel.
- Exportar PDF.

---

# 9. Informe Gerencial de Cuenta Corriente

## Objetivo

Dar a gerencia una visión consolidada de toda la cartera, distinta del extracto individual de un cliente.

## Filtros

- Fecha de corte.
- Cliente.
- Estado: todos / con saldo / vencidos / no vencidos.
- Antigüedad.

## Columnas sugeridas

- Cliente.
- Saldo total.
- Saldo vencido.
- Saldo a vencer.
- Próximo vencimiento.
- Días de atraso máximo.
- Límite de crédito.
- Crédito disponible.
- % utilizado.
- Fecha último pago.
- Fecha último despacho.

## Totales gerenciales

- Cartera total.
- Total vencido.
- Total no vencido.
- Cantidad de clientes deudores.
- Cantidad de clientes vencidos.
- Cantidad excedidos de crédito.

## Navegación

Doble clic o `Ver cuenta corriente` debe abrir la cuenta corriente del cliente ya seleccionado.

---

# 10. Informe de Clientes

## Objetivo

Analizar comportamiento comercial y financiero por cliente.

## Métricas por cliente

- Ventas/despachos valorizados.
- TN compradas.
- Cantidad de cargas.
- Ticket promedio.
- Último despacho.
- Saldo actual.
- Saldo vencido.
- Fecha último pago.
- Días promedio de pago, si puede calcularse de forma confiable.

## Rankings sugeridos

- Top por facturación.
- Top por TN.
- Top por cantidad de cargas.
- Top por saldo.
- Top por deuda vencida.

---

# 11. Informe de Productos

## Objetivo

Analizar participación comercial y volumen por producto.

## Métricas

- Cantidad vendida/despachada.
- Kg.
- TN.
- Importe neto.
- IVA.
- Total.
- Participación porcentual sobre TN totales.
- Participación porcentual sobre ventas totales.
- Precio neto promedio por unidad.
- Precio promedio por kg/TN cuando sea conceptualmente válido.

## Análisis temporal

- Evolución mensual por producto.
- Comparación contra período anterior.

---

# 12. Informe Logístico

## Objetivo

Dar visibilidad sobre el movimiento físico asociado a las órdenes.

## Indicadores

- Cantidad de cargas.
- TN transportadas.
- Kg promedio por carga.
- Cantidad de pallets utilizados.
- Kg en pallets.
- Kg de mercadería suelta.
- % de mercadería suelta.
- Cantidad de destinos atendidos.
- Cantidad de transportistas utilizados.
- Cantidad de camiones utilizados.

## Rankings

### Transportistas

- cargas;
- TN;
- kg promedio por carga.

### Camiones

- cargas;
- TN.

### Destinos

- cargas;
- TN.

---

# 13. Devoluciones

El Dashboard y los informes deben contemplar explícitamente las devoluciones registradas al cierre de una orden.

## Indicadores sugeridos

- Cantidad de devoluciones.
- Cantidad devuelta.
- Importe creditado.
- % devuelto sobre cantidad despachada.
- Clientes con más devoluciones.
- Productos con más devoluciones.

## Regla de negocio pendiente

Debe definirse si los KPIs comerciales mostrarán:

1. ventas brutas y devoluciones separadas; o
2. ventas netas de devoluciones.

Recomendación inicial:

Mostrar ambos conceptos.

Ejemplo:

```text
Despachos brutos      $ 120.000.000
Devoluciones          $   2.500.000
Despachos netos       $ 117.500.000
```

Esto conserva transparencia gerencial.

---

# 14. Estados de órdenes y criterio de inclusión

La aplicación contempla actualmente estados equivalentes a:

- Pendiente.
- Borrador legacy.
- Emitida.
- Cerrada.
- Anulada.

Para cada informe deberá indicarse claramente qué estados participan.

## Propuesta inicial para indicadores comerciales

| Estado | Participa en ventas | Participa en logística | Participa en pendientes |
|---|---:|---:|---:|
| Pendiente | No | No o separado | Sí |
| Borrador | No | No | Sí |
| Emitida | Sí | Sí | No |
| Cerrada | Sí | Sí | No |
| Anulada | No | No | No |

Esta tabla deberá validarse antes de congelar la implementación.

---

# 15. Exportaciones

Todos los informes detallados deberían poder exportarse.

## Excel

Debe ser la exportación principal para análisis.

Requisitos:

- mismas columnas visibles o una versión ampliada bien definida;
- filtros aplicados reflejados en encabezado;
- totales;
- fechas y números con formatos adecuados;
- importes numéricos reales, no strings formateados;
- filtros automáticos cuando corresponda.

## PDF

Orientado a presentación gerencial o impresión.

Requisitos:

- título del informe;
- período;
- fecha/hora de generación;
- usuario;
- filtros aplicados;
- KPIs principales;
- tabla resumida.

No todos los informes necesitan PDF en la primera entrega.

---

# 16. Permisos

El Dashboard y los informes gerenciales deben contar con permisos propios.

Propuesta:

```text
reports.dashboard.view
reports.sales.view
reports.account.view
reports.clients.view
reports.products.view
reports.logistics.view
reports.export
```

El perfil `Administrador` debería tenerlos por defecto.

Debe definirse qué perfiles adicionales podrán acceder a información financiera sensible.

---

# 17. Rendimiento

Los informes pueden crecer significativamente con el histórico.

La implementación deberá:

- realizar agregaciones en base de datos siempre que sea razonable;
- evitar cargar todas las filas en memoria para calcular KPIs simples;
- reutilizar consultas;
- revisar índices sobre campos utilizados para fecha, cliente, estado y relaciones principales;
- paginar informes extensos;
- evitar bloquear la UI durante consultas pesadas.

No se propone crear tablas de resumen/materializadas en la primera etapa salvo que las mediciones de rendimiento lo justifiquen.

---

# 18. Diseño visual propuesto

## Encabezado

```text
Dashboard Gerencial
Período: [ Este mes v ] [Desde] [Hasta] [Actualizar]
```

## Primera fila — KPIs

```text
┌───────────────┐ ┌───────────────┐ ┌─────────────┐
│ Ventas        │ │ Toneladas     │ │ Órdenes     │
│ $ ...         │ │ ... TN        │ │ ...         │
│ vs ant. ...%  │ │ vs ant. ...%  │ │ vs ant. ... │
└───────────────┘ └───────────────┘ └─────────────┘

┌───────────────┐ ┌───────────────┐ ┌─────────────┐
│ Saldo clientes│ │ Saldo vencido │ │ Ticket prom.│
│ $ ...         │ │ $ ...         │ │ $ ...       │
└───────────────┘ └───────────────┘ └─────────────┘
```

## Segunda fila

```text
┌───────────────────────────────┐ ┌──────────────────────┐
│ Evolución últimos 12 meses    │ │ Top 10 clientes      │
│ gráfico                       │ │ ranking              │
└───────────────────────────────┘ └──────────────────────┘
```

## Tercera fila

```text
┌──────────────────────┐ ┌──────────────────────┐ ┌─────────────────────┐
│ Top productos        │ │ Estado de órdenes    │ │ Deuda por antigüedad│
└──────────────────────┘ └──────────────────────┘ └─────────────────────┘
```

## Último bloque

Tabla breve:

```text
Clientes con deuda vencida
Cliente | Saldo | Vencido | Días atraso | Próximo vencimiento
```

Botón:

```text
[ Ver informe completo ]
```

---

# 19. Navegación propuesta

Agregar al menú principal una sección:

```text
Informes
  Dashboard Gerencial
  Ventas / Despachos
  Cuenta Corriente Gerencial
  Clientes
  Productos
  Logística
```

El Dashboard debe actuar como punto de entrada principal para perfiles gerenciales.

---

# 20. Estrategia de implementación por etapas

## Etapa 1 — Base gerencial + Dashboard V1

- Servicio central de métricas.
- Filtros de período.
- Ventas/despachos valorizados.
- TN.
- Cantidad de órdenes.
- Ticket promedio.
- Saldo clientes.
- Saldo vencido.
- Evolución mensual.
- Top clientes.
- Top productos.
- Estado de órdenes.

### Objetivo

Entregar una primera pantalla gerencial útil y validar todos los cálculos con FEMAG.

---

## Etapa 2 — Informe de Ventas / Despachos

- filtros;
- detalle;
- totales;
- navegación a orden;
- Excel.

---

## Etapa 3 — Cuenta Corriente Gerencial

- cartera consolidada;
- vencimientos;
- aging;
- límites de crédito;
- navegación a cliente;
- Excel.

---

## Etapa 4 — Clientes y Productos

- rankings;
- tendencias;
- detalle;
- comparativos.

---

## Etapa 5 — Logística

- cargas;
- TN;
- pallets;
- mercadería suelta;
- transportistas;
- camiones;
- destinos.

---

## Etapa 6 — Exportaciones y terminación ejecutiva

- PDFs gerenciales;
- mejoras visuales;
- drill-down completo;
- permisos finales;
- optimizaciones de rendimiento.

---

# 21. Validación de cifras

Antes de considerar finalizado cualquier KPI debe realizarse una conciliación manual contra registros conocidos.

Ejemplo:

1. Seleccionar un período pequeño.
2. Identificar manualmente las órdenes válidas.
3. Sumar importes.
4. Sumar cantidades/kg.
5. Comparar con Dashboard.
6. Revisar devoluciones/anulaciones.
7. Documentar el resultado del caso de prueba.

Los tests automáticos deben cubrir especialmente:

- órdenes anuladas;
- períodos sin datos;
- devoluciones;
- múltiples productos por orden;
- múltiples clientes/destinos;
- pallets y mercadería suelta;
- pagos y reversas;
- saldos iniciales;
- vencimientos;
- créditos/débitos manuales.

---

# 22. Decisiones que deben validarse con FEMAG

Antes o durante la primera implementación deben cerrarse estas definiciones:

1. ¿Una orden `Emitida` ya cuenta como venta/despacho o solamente una `Cerrada`?
2. ¿El indicador principal se denominará `Ventas`, `Despachos`, `Facturación` o `Despachos valorizados`?
3. ¿Las toneladas deben salir siempre de asignaciones físicas o puede utilizarse cantidad × peso del producto como fallback?
4. ¿Las devoluciones se descuentan del KPI principal o se muestran separadas?
5. ¿Se requiere ver valores con IVA y sin IVA simultáneamente?
6. ¿Saldo vencido debe considerar una imputación FIFO de pagos o existe una vinculación documental específica?
7. ¿Qué perfiles, además del Administrador/Gerencia, pueden visualizar saldos y montos?
8. ¿Se desea incluir metas/presupuesto mensual en una etapa futura?
9. ¿Se desea comparar contra mismo mes/año anterior cuando exista histórico suficiente?

---

# 23. Posibles ampliaciones futuras

Fuera del alcance inicial, pero compatibles con este diseño:

- metas mensuales de ventas;
- cumplimiento de objetivos;
- presupuesto vs. real;
- margen comercial si se incorpora costo;
- rentabilidad por cliente/producto;
- alertas automáticas de deuda vencida;
- envío periódico del resumen gerencial por correo;
- snapshot diario/semanal de KPIs;
- indicadores por vendedor si se incorpora esa dimensión;
- forecast de cobranzas;
- forecast de despachos;
- comparativos interanuales avanzados.

---

# 24. Criterio de éxito del módulo

El módulo se considerará exitoso cuando un gerente pueda abrir FEMAG y, en pocos segundos, responder como mínimo:

- cuánto se despachó/vendió en el período;
- cuántas toneladas se movieron;
- cuáles son los principales clientes;
- cuáles son los principales productos;
- cuánto deben los clientes;
- cuánto está vencido;
- quiénes concentran el riesgo crediticio;
- qué volumen de cargas se está manejando;
- cómo se compara el período actual con el anterior;
- y pueda pasar del indicador al detalle sin buscar manualmente en distintas pantallas.

---

## Estado del documento

**Estado:** propuesta funcional para validación.

Este documento no crea todavía los issues de implementación. Una vez validado funcionalmente, deberá utilizarse como documento maestro para generar un issue padre y los issues hijos por etapa.
