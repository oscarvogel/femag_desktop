# Fase B — envío de la lista de precios por WhatsApp (#705, issue #763)

Bitácora de la implementación del módulo de envío, en las tres etapas en que se hizo.

**Estado:** código completo y validado (1966 tests), publicado como candidate
`2026.10.23.14.26.30` (canal `candidate`, **sin promover a producción**).
**Falta la prueba real contra el gateway**:
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

## Hallazgo: la zona horaria del tope diario no podía depender de `zoneinfo`

El primer release con la Fase B **abortó en los tests (19 fallos) y no publicó nada**. La
causa no era la lógica de la campaña: el tope diario se cuenta desde la medianoche local y
el código usaba

```python
ZONA = ZoneInfo("America/Argentina/Buenos_Aires")
```

`zoneinfo` exige el paquete **`tzdata`**, que no está en `requirements.txt`. En el venv
limpio del release (y en la PC del cliente) **la app no arrancaba**: `ZoneInfoNotFoundError`
al instalar la extensión.

El CI en Linux no lo ve (`tzdata` está en el sistema) y el Python del sistema de la máquina
de desarrollo también lo tiene, pero el `.venv` que arma el instalador de Windows no. Por eso
la corrección (PR #768, commit `ecb220e`) **no tocó `requirements.txt`** y usó el
desplazamiento fijo de Argentina, que es UTC-3 sin horario de verano desde 2009:

```python
ZONA = timezone(timedelta(hours=-3))
```

Evidencia antes/después con el venv: `ZoneInfoNotFoundError` → `extension OK`.

Además se verificó el **contenido** del instalador publicado (Inno Setup comprime con
lzma2, así que no se puede abrir con 7-Zip): se leyó el PYZ embebido del build congelado de
PyInstaller (1259 módulos) y se confirmó que `app.services.price_list_send_service` usa
`timedelta` y **no** `zoneinfo`. O sea, el instalador que se publicó lleva el fix.

## La lista 2, en detalle (para la prueba real)

Contra la base aislada del cliente (`femag_cliente_761`, dump del 20/10 con el import
unificado aplicado), con el código real de la app:

| id | cliente | teléfono en la base | estado | marcado | número a enviar |
|---|---|---|---|---|---|
| 88 | MENDEZ MARIA FERNANDA | 011-4484-7498 | posible | no | 5491144847498 |
| 850 | GIMENEZ ROMINA JAQUELINE | +5491164426278 | celular | **sí** | 5491164426278 |
| 852 | BUENOS ALIMENTOS | 011 2155 4404 | posible | no | 5491121554404 |
| 853 | MUSLI WOLKEN S.A | 358 - 602 5698 | posible | no | 5493586025698 |
| 854 | BAREIRO JAVIER | 011 3116 7114 | posible | no | 5491131167114 |
| 855 | GUIZZETTI MARIA DE LOS ANGELES | 011 5958 9894 | posible | no | 5491159589894 |
| 870 | CODIGO ANIMALS.R.L. | +5491157489959 | celular | **sí** | 5491157489959 |
| 873 | DA SILVA MARCELO RUBEN | (sin teléfono) | vacío | no | (no se manda) |

Además hay un GIMENEZ ROMINA JAQUELINE **inactivo** (id 865): la pantalla lo omite y avisa
en el contador `inactivos_omitidos`.

**Con la lista 2 solo salen marcados 2 destinatarios** (GIMENEZ y CODIGO ANIMALS). Para
llegar a 3-5 hay que tildar a mano alguno de los "posibles", y eso es una decisión del
operador: un local de 10 dígitos puede ser una línea fija, y mandarle a un fijo no es un
error de datos, es lo que más rápido hace que el proveedor bloquee la línea.

**Requisito previo**: el usuario que opera tiene que tener una **instancia de WhatsApp
asignada** (`Sistema > WhatsApp`, tabla de usuarios). Sin instancia, la pantalla avisa
*"El usuario no tiene una instancia de WhatsApp asociada"* y no deja empezar. En la base del
cliente hay dos: `femag_cliente_761` (admin y cristina) y `femag_gabriela` (gabriela).

**El PDF no viaja en el repositorio**: se elige en la PC del cliente con "Seleccionar PDF" y
se guarda con "Guardar configuración" (queda la ruta en `AppParameter`). El archivo tiene
que existir en el disco de esa máquina.

## Qué falta

1. **La prueba real**: 3-5 destinatarios, intervalo de 10 s, **instancia de prueba**. Es el único
   punto sin verificar: el código nunca habló con el gateway. Con la lista 2 solo salen
   marcados 2 destinatarios (GIMENEZ y CODIGO ANIMALS); ver la tabla de más arriba.
2. **Fase C**: reanudar una campaña después de cerrar la app, export del log de omitidos, ventana
   horaria y el reporte de "clientes de esta lista sin WhatsApp" (el informe que convierte el hueco
   de datos en una tarea cerrable).
3. **Fase D**: que el sistema arme el PDF de la lista.
4. **#759**: el normalizador viejo de los envíos 1 a 1 (es otro flujo: no se mezcló).

## Una deuda conocida

`tests/test_master_abm_desktop_ui.py::test_truck_created_from_abm_can_be_used_in_load_order_grid`
falla si se corre aislado. Se verificó que **falla igual en `main` sin estos cambios** (worktree
limpio en `8dda92a`): es un defecto preexistente y ajeno a esta issue.
