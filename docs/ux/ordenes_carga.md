# UX - Ordenes de carga

Este documento aplica el Loop UX previo a la pantalla de Ordenes de carga antes de codificar cambios funcionales. No implementa pantallas, no cambia logica real y no define integraciones productivas.

## Checklist UX previo

Pantalla: Ordenes de carga

Issue relacionado: #52 - UX - Definir flujo de pantalla Ordenes de carga

### Objetivo

Definir el flujo operativo para crear, consultar, editar, anular e imprimir ordenes de carga de FEMAG.

La pantalla debe permitir trabajar rapido en despacho sin ocultar datos criticos: cliente, producto, cantidades, chofer, transportista, entrega, estado e impresion.

### Usuario principal

Secretaria / administracion de despacho.

Usuarios secundarios posibles:

- Administracion que consulta estados.
- Responsable operativo que revisa anulaciones o pendientes.
- Usuario con permiso de impresion.

### Permisos

Permisos minimos a definir antes de implementar:

- Ver ordenes.
- Crear ordenes.
- Editar ordenes pendientes.
- Anular ordenes.
- Imprimir.
- Acceder a datos relacionados: clientes, productos, choferes, transportistas y vehiculos.

Regla UX: si el usuario no tiene permiso para una accion, la accion debe estar oculta o deshabilitada con feedback claro. No mostrar botones activos que luego fallen por permisos.

### Datos minimos

Datos necesarios para operar la pantalla:

- Numero de orden.
- Fecha.
- Cliente.
- Producto.
- Cantidad / pallets.
- Chofer.
- Transportista.
- Vehiculo / patente si aplica.
- Domicilio de entrega.
- Observaciones.
- Estado de la orden.
- Usuario creador / auditoria si aplica.

Datos de apoyo:

- Estados posibles: pendiente, emitida/impresa, anulada, cerrada si aplica.
- Historial minimo de cambios si existe auditoria.
- Mensajes de validacion por campo.

### Acciones principales

Acciones visibles y prioritarias:

- Nueva orden.
- Guardar.
- Imprimir.
- Buscar.
- Filtrar por estado, fecha y cliente.
- Ver detalle.

Estas acciones deben ser faciles de encontrar y consistentes con el estilo profesional aprobado.

### Acciones secundarias

Acciones menos prominentes:

- Editar.
- Anular.
- Duplicar si aplica.
- Exportar si aplica.
- Ver historial si aplica.

Regla UX: anular, duplicar, exportar e historial no deben competir visualmente con Nueva orden, Guardar e Imprimir.

### Estados requeridos

- Vacio: no hay ordenes para los filtros actuales. Debe ofrecer limpiar filtros o crear una nueva orden si el usuario tiene permiso.
- Con datos: tabla/listado legible con estado visible y acceso rapido al detalle.
- Cargando: indicar que se estan consultando datos, sin bloquear visualmente toda la app si no hace falta.
- Error: mostrar mensaje claro sin traza interna.
- Sin permiso: explicar que el usuario no puede ver o ejecutar la accion.
- Sin conexion / error de base si aplica: informar problema operativo y sugerir reintentar o avisar a soporte.

## Flujo sugerido

### Consulta

1. El usuario abre Ordenes de carga.
2. La pantalla muestra filtros simples: fecha, estado, cliente y busqueda por numero.
3. El listado muestra ordenes con columnas operativas: numero, fecha, cliente, producto, cantidad/pallets, chofer, transportista, estado y accion de detalle.
4. El usuario puede abrir el detalle sin perder el contexto del listado.

### Alta

1. El usuario selecciona Nueva orden.
2. El formulario se presenta por secciones:
   - Datos generales.
   - Cliente y entrega.
   - Producto y cantidad.
   - Transporte.
   - Observaciones.
3. Guardar valida campos obligatorios antes de persistir.
4. Si la orden queda completa, Imprimir queda disponible segun permisos.

### Edicion

1. El usuario abre una orden pendiente.
2. Editar solo esta disponible si el estado lo permite.
3. Guardar vuelve a validar campos obligatorios y cantidades.
4. Si la orden ya fue impresa o anulada, la pantalla debe explicar que no se puede editar o que la edicion tiene restricciones.

### Anulacion

1. El usuario selecciona Anular desde una accion secundaria.
2. La app pide confirmacion con el numero de orden y cliente.
3. La anulacion registra usuario y motivo si el modelo lo soporta.
4. La orden queda con estado visible de anulada.

### Impresion

1. Imprimir se habilita solo si la orden esta completa.
2. La pantalla debe preparar salida A4 o preview si el modulo lo soporta.
3. Si faltan datos, mostrar que campos bloquean la impresion.

## Layout textual propuesto

```text
[Titulo] Ordenes de carga
[Acciones principales] Nueva orden | Guardar | Imprimir

[Filtros]
Fecha desde/hasta | Estado | Cliente | Buscar por numero

[Listado]
Numero | Fecha | Cliente | Producto | Cantidad/Pallets | Chofer | Transportista | Estado | Detalle

[Panel detalle / formulario]
Datos generales
- Numero
- Fecha
- Estado

Cliente y entrega
- Cliente
- Domicilio de entrega

Producto y cantidad
- Producto
- Cantidad
- Pallets

Transporte
- Chofer
- Transportista
- Vehiculo / patente

Observaciones
- Texto libre

[Acciones secundarias]
Editar | Anular | Duplicar si aplica | Exportar si aplica | Historial si aplica
```

## Validaciones manuales

Antes de implementar, el issue tecnico debe definir como validar:

- No permitir guardar sin cliente.
- No permitir guardar sin producto.
- No permitir cantidades invalidas.
- No permitir imprimir orden incompleta.
- Validar chofer/transportista cuando corresponda.
- Validar domicilio de entrega.
- Confirmar anulacion.
- Respetar permisos para ver, crear, editar, anular e imprimir.
- Mostrar errores claros sin trazas internas.

## Criterios visuales

- Mantener el estilo profesional aprobado.
- Acciones principales visibles y consistentes.
- Acciones secundarias menos prominentes.
- Tabla legible y escaneable.
- Filtros simples y cercanos al listado.
- Formulario ordenado por secciones.
- Estado visible de la orden.
- Preparacion conceptual para impresion A4.
- Estados vacios utiles, no pantallas muertas.
- Evitar saturar la pantalla con acciones simultaneas.

## Riesgos

- Mezclar alta, consulta, impresion y anulacion en una sola pantalla puede saturar el flujo.
- Permisos mal definidos pueden mostrar acciones que el usuario no puede ejecutar.
- Imprimir sin validar datos minimos puede generar documentos incompletos.
- Editar ordenes ya impresas o anuladas puede afectar trazabilidad.
- Integraciones futuras con DBF/MySQL o remitos pueden empujar alcance fuera de fase si no se separan.

## Fuera de alcance

- No implementar logica real todavia.
- No conectar importaciones DBF/MySQL.
- No generar F150.
- No modificar remitos.
- No modificar cuentas corrientes.
- No tocar impresion real salvo diseno conceptual si se documenta.
- No agregar tests ni screenshots en este documento.

## Decision

La pantalla no queda lista para implementacion todavia.

Antes de codificar, convertir este analisis en uno o mas issues tecnicos chicos. El primer issue de implementacion deberia limitarse a un flujo minimo, por ejemplo consulta + alta basica o ajuste de formulario, con permisos y validaciones claramente definidos.
