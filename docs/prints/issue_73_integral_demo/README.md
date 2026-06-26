# Evidencia Issue #73 - Demo integral Ordenes de carga

- Orden: OC-000003
- Estado final: Anulada
- Destinos: 3
- Productos: 4
- Orden HTML: `orden_carga_3.html`
- Hoja/sobre HTML: `hoja_resumen_3.html`
- Reimpresion HTML: `orden_y_resumen_3.html`
- Cuenta corriente documental: 2 movimientos originales y 2 reversos.

## Flujo validado por script

1. Asegura maestros sinteticos.
2. Crea Orden de carga multi-cliente/multi-destino.
3. Emite la orden.
4. Genera Orden HTML A4.
5. Genera hoja/sobre HTML A4.
6. Reimprime como copia operativa.
7. Verifica cuenta corriente documental.
8. Anula la orden.
9. Verifica reversos documentales.

## Computer Use

- Comando ejecutado: `py -3 -m app.main --demo-ui`.
- Computer Use detecto la ventana real `FEMAG Desktop` via `list_windows`.
- La captura de estado de la ventana fallo con: `SetIsBorderRequired failed: Interfaz no compatible (0x80004002)`.
- Resultado: no queda validado visualmente el circuito extremo a extremo desde Computer Use.
- Decision: #73 puede documentar la demo funcional automatizada, pero #69 no debe cerrarse como validado visualmente hasta completar una validacion manual real asistida.

## Alcance

No fiscal. No remito, F150, AFIP/ARCA, factura, presupuesto, rendicion ni Delivery*.
