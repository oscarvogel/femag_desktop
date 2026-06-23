# Guia de usuario - Entrega 2

## Ordenes de carga

1. Entrar en Operaciones > Ordenes de carga.
2. Elegir cliente y domicilio de entrega.
3. Seleccionar transportista, chofer y camion.
4. Cargar producto, cantidad y pallets si corresponde.
5. Cargar observaciones si hacen falta.
6. Elegir estado Borrador, Emitida o Anulada segun corresponda.
7. Guardar la orden.

Cada orden corresponde a un solo camion. Si una carga tiene varios productos, se cargan como detalles de la misma orden.

La primera pantalla funcional permite alta, edicion basica, consulta, listado, emision, anulacion e impresion A4. Los detalles multiples quedan preparados en el servicio y se ampliaran en la UI cuando se avance con Remitos.

## Bloqueo de chofer

Al crear una orden activa, el chofer queda bloqueado y no puede asignarse a otra orden pendiente o emitida.

El chofer se libera cuando la orden pasa a:

- Cerrada.
- Anulada.

Si se intenta usar un chofer bloqueado, el sistema rechaza la operacion con un mensaje claro.

## Estados

Los estados disponibles son:

- Borrador.
- Emitida.
- Cerrada.
- Anulada.

Emitir una orden exige datos completos: fecha, cliente, producto y cantidad mayor a cero. Cerrar una orden deja liberado el chofer. Anular una orden requiere permiso de anulacion.

## Impresion y reimpresion

Desde la orden se puede generar:

- Orden de carga.
- Hoja resumen / sobre de carga.
- Impresion conjunta de orden + hoja resumen.

La salida actual se genera como HTML imprimible en A4 desde `LoadOrderPrintService`. El servicio esta desacoplado de la pantalla para poder reemplazar el motor de reportes por PDF u otro formato mas adelante sin cambiar la logica de negocio.

La reimpresion no pide clave de administrador. La impresion y reimpresion quedan auditadas.

## Fuera de alcance actual

Quedan pendientes para entregas posteriores:

- Remito real.
- Generacion F150 real.
- Importacion DBF/MySQL incremental.
- Integracion contable o cuenta corriente desde ordenes.

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
