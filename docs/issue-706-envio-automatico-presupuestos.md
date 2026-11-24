# Envio automatico de presupuestos al emitir una orden (#706)

## Etapa 1 — alcance incluido

- Servicio `BudgetAutoSendService` (`app/services/budget_auto_send_service.py`):
  toma los presupuestos **activos de la orden emitida** y resuelve, por cada
  uno, un unico destinatario.
- Regla del destinatario: el vendedor del presupuesto (`budget.salesperson`,
  snapshot de #546) si existe; si no, el vendedor actual del cliente; si
  tampoco, el cliente. Es el mismo destinatario en WhatsApp y en correo.
- WhatsApp: destino resuelto por `WhatsAppContactService.destino_cliente` /
  `destino_vendedor` (#923), PDF propio por presupuesto y fila en
  `whatsapp_envios` con `tipo_documento="presupuesto"` (la misma que usa el
  envio manual de Cuenta corriente).
- Correo: se envia solo si el destinatario tiene direccion cargada. Con 0
  emails en la base real, hoy queda **omitido con motivo** en todos los casos.
- Tolerancia a fallos: cada canal y cada documento se resuelve por separado.
  Un fallo de gateway, SMTP, PDF o contacto queda registrado y no frena los
  demas envios ni la emision (el envio corre fuera de la transaccion).
- Idempotencia: no se repite un WhatsApp que ya tiene estado
  `queued/accepted/delivered/read` para ese presupuesto (incluye el envio
  manual) ni un correo ya confirmado para ese presupuesto.
- Trazabilidad: una fila de auditoria `Presupuestos / envio_automatico_*` por
  presupuesto y canal, con destinatario, estado y motivo; el correo confirmado
  deja ademas la marca `envio_automatico_correo_enviado`.
- Interfaz: el envio corre en un `QRunnable` sobre `QThreadPool` desde
  `emit_order_with_stock_check`, compartido por las dos pantallas de ordenes.
  Al terminar se muestra un resumen con enviados, omitidos, fallidos y sus
  motivos.

## Activacion

El envio automatico esta **apagado por defecto** y se habilita **una sola vez
para todo el sistema**, no puesto por puesto:

```text
Parametros > Presupuestos > Enviar los presupuestos automaticamente
```

La decision se guarda en `AppParameter` (`presupuestos.autoenvio`) y la
comparten todos los puestos. Queda auditada en `Sistema / configurar`.

El `.env` del puesto queda solo como respaldo para demo/tests:
`FEMAG_PRESUPUESTOS_AUTOENVIO=1`. Si hay valor central, manda el central. Si
no hay valor central, se lee el `.env`; si tampoco esta, queda apagado.

El destino de WhatsApp sigue la regla de #923: con `FEMAG_WHATSAPP_DEDICADO`
apagado se usa `phone` y solo si clasifica como celular; encendido, manda
`whatsapp_phone`. El envio automatico no enciende ese flag por su cuenta.

## Decisiones tomadas en esta etapa

- Se envian los presupuestos activos de la orden, incluida la parte diferida de
  una orden partida. Se puede restringir a `TIMING_IMMEDIATE` si operaciones
  prefiere que la parte a facturar despues no salga al emitir.
- Los presupuestos manuales no participan: solo se recorren los que tienen
  `load_order` y estan activos.
- Una orden anulada no se reemite (`issue()` lo rechaza), asi que no hay doble
  envio por anular y volver a emitir.
- El texto del mensaje distingue destinatario vendedor (menciona al cliente)
  de destinatario cliente (igual al envio manual).
- No hay reintento automatico de WhatsApp. Si un envio queda `failed`, se
  reintenta explicitamente y no se duplican los ya confirmados.

## Fuera de alcance / pendientes reales

- Correo: no hay direcciones cargadas en la base real (0 clientes, 0
  vendedores). Falta decidir si se cargan o si el canal queda en espera.
- Politica de reintentos automaticos y su pantalla de seguimiento.
- Envio a cliente **y** vendedor a la vez (hoy es uno solo, por decision del
  issue).
- Que hacer si una orden emitida se modifica y regenera presupuestos: hoy el
  envio es al emitir; una regeneracion posterior no dispara otro envio.

## Validacion

```bash
python -m pytest tests/test_issue_706_budget_auto_send.py -q
python -m compileall app
python -m app.main --smoke
```
