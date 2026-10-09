# FEMAG - Módulo de Stock, Producción y Fraccionamiento

**Estado:** propuesta funcional para implementación futura  
**Fecha:** 2026-09-29  
**Proyecto:** `oscarvogel/femag_desktop`

## 1. Objetivo

Incorporar a FEMAG un módulo de stock que permita conocer existencias reales de materias primas y productos terminados, registrar procesos de producción/fraccionamiento y evitar faltantes mediante mínimos y alertas.

El diseño debe integrarse con el circuito actual de productos, órdenes, despacho, costos y rentabilidad, evitando duplicar cargas.

## 2. Principios de diseño

1. El stock se obtiene desde un **kardex de movimientos**. No se mantiene únicamente como un campo editable.
2. Se separan **materias primas** de **productos terminados**.
3. La producción **consume** materia prima y **genera** productos terminados.
4. El despacho existente debe descontar stock automáticamente cuando alcance el estado operativo definido como efectivo.
5. Todo ajuste manual debe ser auditable: usuario, fecha, motivo, cantidad y referencia.
6. La primera versión debe priorizar trazabilidad y simplicidad antes que funciones de ERP industrial avanzado.
7. Las operaciones críticas deben ser transaccionales: o se registran completas o no se registra ninguna parte.

## 3. Caso de negocio de referencia

Ingreso:
- Materia prima: Almidón de maíz a granel.
- Cantidad: 28.000 kg.
- Puede provenir físicamente de Big Bags de aproximadamente 1.300 kg.

Producción:
- 14.000 kg -> 560 bolsas de 25 kg.
- 14.000 kg -> 28.000 paquetes de 500 g.

Resultado:
- Stock de materia prima consumido: 28.000 kg.
- Stock generado: 560 bolsas de 25 kg + 28.000 paquetes de 500 g.
- No debe existir duplicación entre materia prima y producto terminado.

## 4. Entidades conceptuales

### 4.1 Materia prima
Campos mínimos sugeridos:
- `id`
- `codigo`
- `descripcion`
- `unidad_base`
- `stock_minimo`
- `activo`
- auditoría de alta/modificación

### 4.2 Producto terminado
Reutilizar el maestro de productos existente siempre que sea posible. Agregar lo necesario para identificar si controla stock, unidad, peso/conversión, stock mínimo y relación futura con materia prima/receta.

### 4.3 Movimiento de stock / Kardex
Tipos iniciales:
- `INGRESO_COMPRA`
- `CONSUMO_PRODUCCION`
- `PRODUCCION_TERMINADA`
- `DESPACHO`
- `AJUSTE_POSITIVO`
- `AJUSTE_NEGATIVO`
- `MERMA`

Campos conceptuales:
- `id`, `fecha_hora`, `tipo_movimiento`
- `item_tipo`, `item_id`
- `cantidad`, `unidad`
- `referencia_tipo`, `referencia_id`
- `usuario_id`, `observacion`

No permitir borrar movimientos confirmados. Las correcciones deben realizarse mediante contramovimientos o anulaciones auditadas.

### 4.4 Producción
Cabecera con fecha, estado (`BORRADOR`, `CONFIRMADA`, `ANULADA`), usuario y observaciones.

Una producción puede consumir una o más materias primas y generar uno o varios productos terminados.

### 4.5 Mermas
Registrar cantidad, unidad, motivo, observación y usuario. La merma debe formar parte del kardex.

## 5. Flujos funcionales

### 5.1 Ingreso de materia prima
1. Seleccionar materia prima.
2. Registrar cantidad, fecha, proveedor y referencia.
3. Opcionalmente lote/importación.
4. Confirmar.
5. Generar `INGRESO_COMPRA`.
6. Aumentar disponibilidad.

### 5.2 Registrar producción
Pantalla orientada a fábrica:
1. Nueva producción.
2. Seleccionar materia prima.
3. Informar cantidad consumida.
4. Agregar uno o más productos obtenidos.
5. Informar cantidades reales.
6. Informar merma si existe.
7. Validar.
8. Confirmar.

En una única transacción:
- generar `CONSUMO_PRODUCCION`;
- generar uno o varios `PRODUCCION_TERMINADA`;
- generar `MERMA` si corresponde.

### 5.3 Despacho
Cuando el despacho alcance el estado que represente salida efectiva:
- generar movimiento `DESPACHO`;
- descontar productos terminados;
- vincular movimiento con orden/despacho;
- impedir doble descuento ante reintentos.

La operación debe ser idempotente.

### 5.4 Ajuste de inventario
Solo perfiles autorizados. Requerir item, diferencia o stock contado, motivo y observación cuando corresponda. Generar movimiento; nunca editar silenciosamente el saldo.

## 6. Stock y alertas

Mostrar como mínimo:
- stock actual;
- unidad;
- stock mínimo;
- estado;
- última actividad.

Estados iniciales:
- Normal
- Bajo
- Crítico / debajo del mínimo
- Sin stock

Primera versión: alerta visual y panel de items bajo mínimo.

Evolución:
- WhatsApp;
- correo;
- resumen gerencial;
- alerta anticipada por días de cobertura.

## 7. Cobertura estimada

Etapa posterior:

`dias_cobertura = stock_disponible / consumo_promedio_diario`

Mostrar stock, consumo promedio, días de cobertura, fecha estimada de agotamiento y tendencia. La fecha es una proyección, no una certeza.

## 8. Recetas / composición

No obligatorio para la primera versión, pero el modelo debe permitir incorporarlas.

Ejemplo:
- Producto: Almidón de maíz 500 g
- Materia prima: Almidón de maíz a granel
- Consumo teórico: 0,500 kg por unidad

Posteriormente: envase, etiqueta, bolsa, caja y otros insumos.

## 9. Integración con costos y rentabilidad

Diseñar considerando el módulo existente de costos/utilidad.

Evolución posible:
- costo de materia prima por lote/ingreso;
- costo promedio;
- costo de producción;
- merma valorizada;
- costo de envases;
- costo real del producto terminado;
- margen real por venta.

No incorporar esta complejidad en la primera iteración salvo necesidad de consistencia.

## 10. Lotes

Recomendado como segunda etapa:
- lote de ingreso;
- proveedor/importación;
- fecha de ingreso;
- lote de producción;
- trazabilidad materia prima -> producción -> producto terminado.

## 11. Permisos sugeridos

**Administración:** ingresos, consultas, ajustes autorizados y mínimos.  
**Fábrica / Producción:** producción, consumos, resultados, mermas y consulta.  
**Secretaría / Operación:** consulta según necesidad.  
**Administrador:** acceso completo, auditoría y anulaciones/correcciones.

Alinear con los perfiles existentes de FEMAG.

## 12. Pantallas iniciales

### Stock
Grilla con tipo, código, descripción, unidad, stock actual, mínimo, estado y última actividad.

Filtros por materia prima/terminado, bajo mínimo, sin stock y búsqueda.

### Ingreso de materia prima
Producto, cantidad, fecha, proveedor y referencia.

### Registrar producción
Dos sectores:
- **Consume:** materia prima + cantidad.
- **Produce:** producto terminado + cantidad.

Más merma, observaciones y confirmación.

### Kardex
Filtros por período, item, tipo de movimiento, usuario y referencia.

## 13. Reglas críticas

- No duplicar stock por producción.
- No descontar dos veces un despacho.
- No borrar silenciosamente movimientos confirmados.
- Mantener auditoría.
- Definir política de stock negativo.
- Definir precisión decimal.
- Validar conversiones kg/unidad.
- Las anulaciones deben revertir correctamente movimientos.
- Las operaciones compuestas deben usar transacciones de base de datos.

## 14. Migraciones

Antes de implementar:
1. Auditar tablas actuales de productos, órdenes, despachos, usuarios y costos.
2. Diseñar nuevas tablas sin modificar innecesariamente legacy.
3. Crear migraciones versionadas.
4. No poblar stock ficticio automáticamente.
5. Preparar carga controlada de stock inicial.
6. Probar con copia representativa de producción.

## 15. Puesta en marcha

El stock inicial no puede deducirse con seguridad solo de ventas históricas.

Propuesta:
1. desplegar módulo;
2. definir catálogo controlado;
3. realizar inventario físico;
4. registrar saldos iniciales con fecha de corte;
5. desde allí, exigir que ingresos, producción y despachos alimenten el kardex;
6. verificar inicialmente contra conteo físico.

## 16. Fases recomendadas

### Fase 1 - Núcleo de stock
Materias primas, productos controlados, kardex, stock inicial, ingresos, ajustes y consulta.

### Fase 2 - Producción
Órdenes de producción, consumo, producto terminado, merma y auditoría.

### Fase 3 - Integración despacho
Descuento automático, idempotencia, anulaciones/reversiones y pruebas end-to-end.

### Fase 4 - Alertas
Mínimos, dashboard y WhatsApp/correo opcional.

### Fase 5 - Inteligencia de stock
Consumo promedio, cobertura, fecha estimada de agotamiento y sugerencias de reposición.

### Fase 6 - Industrialización opcional
Recetas, lotes, envases/insumos, costos industriales y rendimiento.

## 17. Criterios de aceptación iniciales

- Un ingreso incrementa correctamente una materia prima.
- Una producción confirmada descuenta exactamente sus consumos.
- La producción genera exactamente los productos informados.
- La merma queda identificada y auditable.
- Un despacho confirmado descuenta una sola vez.
- Una anulación/reversión deja trazabilidad.
- El kardex permite explicar el stock actual.
- Usuarios sin permiso no pueden ajustar stock.
- El sistema identifica items bajo mínimo.
- Un error no deja movimientos parciales.

## 18. Pruebas mínimas futuras

- conversiones y saldos;
- producción con múltiples salidas;
- producción con merma;
- stock insuficiente;
- doble confirmación/reintento;
- anulación;
- despacho idempotente;
- concurrencia básica;
- permisos;
- migraciones;
- MySQL real;
- end-to-end ingreso -> producción -> despacho -> kardex.

## 19. Decisiones pendientes antes de implementar

- ¿Se permitirá stock negativo?
- ¿Qué estado exacto del despacho produce la salida?
- ¿Cómo se tratará una anulación posterior?
- ¿Big Bags individuales o solo kg inicialmente?
- ¿Lotes desde el inicio?
- ¿Qué precisión decimal?
- ¿Qué productos actuales controlarán stock?
- ¿Quién puede realizar ajustes?
- ¿Quién recibe alertas?
- ¿Envases desde la primera versión o después?

## 20. Fuera de alcance inicial

- MRP completo.
- Planificación automática de fábrica.
- Compras automáticas.
- Contabilidad industrial completa.
- Trazabilidad sanitaria avanzada.
- Gestión integral de múltiples depósitos.

## 21. Nota para implementación futura

Antes de crear issues o escribir migraciones, revisar el estado real de `oscarvogel/femag_desktop`, especialmente:

- modelos/tablas de productos;
- órdenes de carga;
- estados de despacho;
- anulaciones;
- costos y rentabilidad;
- perfiles/permisos;
- auditoría;
- integración WhatsApp.

A partir de esa auditoría, convertir esta propuesta en issues pequeños y separados, evitando mezclar stock, producción, costos y alertas en un único cambio.
