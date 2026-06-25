# Guia de usuario - Entrega 2

## Ordenes de carga

### Prueba real contra base de datos

Para validar la pantalla con una base MySQL de prueba, configurar `.env` o `FEMAG_ENV_FILE` con los datos de esa base y ejecutar:

```bash
py -3 scripts/init_db.py
py -3 scripts/seed_issue_65_load_order_demo.py
py -3 -m app.main --ui
```

El seed crea datos sinteticos con prefijo `ISSUE65`, un usuario `issue65_demo` con clave `demo`, una orden multi-cliente y una salida HTML A4 en `docs/prints/issue_65_demo/`. No usar este seed contra una base productiva con datos reales.

1. Entrar en Operaciones > Ordenes de carga.
2. Cargar la cabecera logistica: fecha, transportista, chofer, camion, estado y observaciones.
3. Agregar uno o mas clientes/destinos dentro de la carga.
4. Cargar observaciones si hacen falta.
5. Dentro de cada cliente/destino, agregar uno o mas productos con cantidad, unidad y observaciones.
6. Agregar el detalle de pallets con tipo, medida, peso, cantidad y observaciones.
7. Guardar la orden.

Cada orden corresponde a una carga logistica de camion o viaje. Una misma carga puede incluir varios clientes, varios lugares de entrega y varios productos por cliente/destino. La cabecera no obliga a elegir un unico cliente, domicilio o producto para toda la orden.

## Bloqueo de chofer

Al crear una orden activa, el chofer queda bloqueado y no puede asignarse a otra orden pendiente o emitida.

El chofer se libera cuando la orden pasa a:

- Cerrada.
- Anulada.

Si se intenta usar un chofer bloqueado, el sistema rechaza la operacion con un mensaje claro.

## Estados

Los estados disponibles son:

- Pendiente.
- Emitida.
- Cerrada.
- Anulada.

Cerrar una orden deja liberado el chofer. Anular una orden requiere permiso de anulacion.

## Impresion y reimpresion

Desde la orden se puede generar:

- Orden de carga.
- Hoja resumen / sobre de carga.
- Impresion conjunta de orden + hoja resumen.

La salida actual se genera como HTML imprimible en A4 desde `LoadOrderPrintService`. El servicio esta desacoplado de la pantalla para poder reemplazar el motor de reportes por PDF u otro formato mas adelante sin cambiar la logica de negocio.

La impresion muestra una cabecera logistica y el detalle agrupado por cliente/destino para evitar confundir una carga multi-cliente con una operacion monocliente.

La reimpresion no pide clave de administrador. La impresion y reimpresion quedan auditadas.

## Auditoria

Quedan registradas las operaciones relevantes:

- Creacion de orden.
- Modificacion.
- Cambio de estado.
- Cierre.
- Anulacion.
- Impresion o reimpresion.
- Bloqueo y liberacion de chofer.

## Dashboard

El dashboard muestra:

- Ordenes del dia.
- Ordenes pendientes.
- Choferes bloqueados.
- Acceso rapido a Nueva orden de carga.

## Arquitectura UI

La pantalla de ordenes se declara desde `app/ui/load_orders.py` usando el contrato de `app/ui/abm.py`, que apunta a `pyqt5libs`.

`femag_desktop` consume `pyqt5libs` como dependencia externa. No se modifica `pyqt5libs` dentro de este repositorio.
