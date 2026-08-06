# UX - Cierre de orden de entrega

## Checklist UX previo

Pantalla: Dialogo de cierre de orden de entrega

Issue relacionado: #220

### Objetivo

- Mostrar los renglones emitidos y registrar cero o varios pagos antes de
  cerrar la entrega, sin salir del flujo de Ordenes de carga.

### Usuario principal

- Secretaria o administracion responsable de despacho y cobranza de entrega.

### Permisos

- Requiere acceso operativo a Ordenes de carga. #220 no incorpora un permiso
  nuevo; la accion permanece deshabilitada salvo que la orden este emitida.

### Datos minimos

- OC emitida, clientes, renglones, cantidades, precios y totales.
- Por pago: cliente, fecha, monto, medio y referencia opcional.
- Motivo obligatorio cuando no se registra ningun pago.

### Acciones principales

- Agregar pago.
- Cerrar entrega.

### Acciones secundarias

- Quitar pago preparado.
- Cancelar sin persistir.
- Registrar observaciones generales.

### Estados requeridos

- [x] Vacio: sin pagos preparados; se informa que el motivo es obligatorio.
- [x] Con datos: renglones y pagos visibles, con total, cobrado y saldo.
- [x] Cargando: no aplica; el dialogo opera sobre datos locales ya cargados.
- [x] Error: validacion de negocio o mensaje de conexion sin traza interna.
- [x] Sin permiso: la accion hereda el acceso a Ordenes y solo se habilita para
  una OC emitida.
- [x] Sin conexion / error de base: mensaje operativo y dialogo abierto para
  reintentar.

### Validaciones manuales

- Abrir una OC emitida y comprobar todos sus renglones.
- Agregar y quitar pagos de distintos medios.
- Confirmar pago total, parcial y cierre sin pago con motivo.
- Verificar que cancelar no persiste datos.
- Verificar que los errores conservan abierto el dialogo.

### Criterios visuales

- Renglones y pagos en grillas separadas y legibles.
- Una sola accion final primaria: `Cerrar entrega`.
- Total, pagos y saldo visibles antes de confirmar.
- Textos completos a 900 x 720 y controles alineados con el estilo FEMAG.

### Fuera de alcance

- Devoluciones (#221), notas de credito (#222), stock, remitos, F150 e
  importaciones legacy.

### Lista para implementacion

- [x] Si.
- [ ] No, falta definir.

## Evidencia

- `docs/screenshots/issue_220_closure_payments/closure_dialog.png` muestra dos
  renglones y un pago parcial por transferencia.
