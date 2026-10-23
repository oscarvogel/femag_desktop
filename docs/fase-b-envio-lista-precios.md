# Fase B — envío de la lista de precios por WhatsApp (#705, issue #763)

Bitácora de la implementación del módulo de envío, en las tres etapas en que se hizo.

**Estado:** código completo y validado (1966 tests). **Falta la prueba real contra el gateway**:
hasta que no se manden 3-5 mensajes de prueba sobre la instancia de prueba, el módulo no se
considera verificado en producción.

## Qué se implementó

| Etapa | PR | Qué trae |
|---|---|---|
| 1 | #764 | Configuración por lista (PDF + mensaje en `AppParameter`) y **cálculo de la audiencia** con el clasificador de teléfonos |
| 2 | #765 | **Motor de la campaña**: cola secuencial, intervalo con jitter, lote inicial, tope 100/día, pausa/cancelar, reintentos, circuit breaker, idempotencia y auditoría |
| 3 | #766 | **Pantalla** "Envío de lista de precios" (Maestros) con los 4 pasos del spec §4.2 |

El diseño completo, con las decisiones y las cifras, está en
`docs/especificacion-envio-lista-precios-whatsapp.md` (§4 y §7).

## Cómo se usa

1. **Maestros → Clientes → "Importar lista"**: se importa el Excel con la lista de precios (Fase A,
   ya en producción). La vista previa separa lo que cambia, lo que no, los conflictos y lo que no
   se encuentra; nada se escribe hasta que el operador confirma.
2. **Maestros → Envío de lista de precios**:
   - elegir la lista (1 a 4) → carga **su** PDF y **su** plantilla de mensaje;
   - "Calcular destinatarios" → contadores y una fila por cliente, con el **número exacto que se
     va a mandar**;
   - tildar "Entiendo que sale desde mi línea" → "Iniciar envío" pide confirmación con la cantidad
     exacta;
   - la cola corre en background: se puede seguir trabajando mientras manda. Pausar, cancelar,
     reintentar fallidos y exportar el log en CSV.

## Las cifras que hay que tener en cuenta

Medidas contra la base real del cliente (dump del 20/10, con el import unificado aplicado):

| lista | clientes | celulares válidos | "posibles" | inválidos | sin teléfono | inactivos |
|---|---|---|---|---|---|---|
| 1 | 874 | **25** | 145 | 35 | 669 | 1 |
| 2 | 8 | **2** | 5 | 0 | 1 | 1 |
| 3 / 4 | 0 | — | — | — | — | — |

**"Enviar la lista 1" son 25 mensajes seguros, no 875.** El cuello de botella real es el dato de
contacto del maestro, no el motor de envío: 669 clientes de la lista 1 no tienen teléfono.

Los "posibles" (un local de 10 u 11 dígitos puede ser una línea fija o un móvil escrito sin el
"15") **no se mandan solos**: aparecen en la vista previa con el número exacto y los tilda el
operador. Con el normalizador viejo de la app, 173 de esos números saldrían mandados como móviles
falsos (issue **#759**).

## Hallazgo: el normalizador viejo corrompe un número ya normalizado

```
5491153088679  ->  54954913088679      <-- número corrupto
011-1553088679 ->  5491153088679       <-- correcto
```

Por eso la campaña **no pasa por `WhatsAppEnvioService.create_attempt`**: el destino entra ya
normalizado por el clasificador y se escribe tal cual en la auditoría. Si se usara el
normalizador viejo, se mandaría a números que no son de nadie.

## Reglas que el módulo no puede aflojar

- El **PDF va por lista**: sin PDF asociado, no se puede enviar.
- **Solo celulares**: un fijo o un texto con letras queda omitido con el motivo a la vista.
- **100 mensajes por día y por instancia**, contados desde la medianoche local.
- **Circuit breaker**: un 429 del gateway detiene la campaña completa; nunca se insiste.
- **Reintentos** solo para errores transitorios (máx. 2); un 4xx no se reintenta.
- **Idempotencia**: la clave `lista{N}-{pdf}-{AAAAMMDD-HHMM}` y el `external_ref` por destinatario
  hacen que reanudar no vuelva a mandar a quien ya recibió la lista.
- El envío **real** requiere autorización expresa (riesgo de bloqueo de línea).

## Qué falta

1. **La prueba real**: 3-5 destinatarios, intervalo de 10 s, **instancia de prueba**. Es el único
   punto sin verificar: el código nunca habló con el gateway.
2. **Fase C**: reanudar una campaña después de cerrar la app, export del log de omitidos, ventana
   horaria y el reporte de "clientes de esta lista sin WhatsApp" (el informe que convierte el hueco
   de datos en una tarea cerrable).
3. **Fase D**: que el sistema arme el PDF de la lista.
4. **#759**: el normalizador viejo de los envíos 1 a 1 (es otro flujo: no se mezcló).

## Una deuda conocida

`tests/test_master_abm_desktop_ui.py::test_truck_created_from_abm_can_be_used_in_load_order_grid`
falla si se corre aislado. Se verificó que **falla igual en `main` sin estos cambios** (worktree
limpio en `8dda92a`): es un defecto preexistente y ajeno a esta issue.
