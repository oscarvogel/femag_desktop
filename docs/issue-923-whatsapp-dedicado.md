# #923 — Número de WhatsApp dedicado para clientes y vendedores

**Issue:** [#923](https://github.com/oscarvogel/femag_desktop/issues/923) — *Contactos: número de WhatsApp dedicado para clientes y vendedores, separado del teléfono*
**Estado:** diseño aprobado (13/11/2026) · implementación por etapas
**Rama:** `feat/issue-923-whatsapp-dedicado`
**Alimenta a:** [#706](https://github.com/oscarvogel/femag_desktop/issues/706) — envío automático de presupuestos al emitir la orden de carga

---

## 1. Contexto

`client.phone` y `salesperson.phone` son **un único campo** que mezcla cosas distintas: líneas fijas,
celulares escritos sin el "15", dos teléfonos pegados con `//`, textos con letras pegadas. No hay ningún
campo que diga "este es el número de WhatsApp", así que el sistema tiene que adivinar en cada envío.

El pedido de Oscar (13/11/2026):

> *Si el cliente tiene un vendedor debe enviarle al vendedor, caso contrario debe enviar al cliente.
> Verificar los números de teléfono a ver si están bien.*
>
> *Creo que deberíamos tener un número de WhatsApp válido y dejar los números de teléfonos libres para
> cuando tengan otros teléfonos, tanto para clientes como para vendedores.*

La segunda parte es este issue: un **número de WhatsApp verificado en un campo propio**, con `phone`
libre para otros teléfonos.

### 1.1 Estado real medido (base real, 13/11/2026)

Medido sobre el dump MySQL 5.7 del cliente, importado en MariaDB de WSL (puerto 3308, base
`femag_desktop`), con el clasificador que ya está en producción
(`app/services/whatsapp_phone_classifier.py`):

| | `celular` | `posible` | `invalido` | vacío |
|---|---|---|---|---|
| Clientes activos (904) | 26 | 183 | 34 | 661 |
| Vendedores (9) | 8 | 1 | 0 | 0 |

- Los 183 "posible" son líneas fijas o celulares escritos sin el "15": **indistinguibles** con la
  información disponible hoy.
- Los 34 inválidos son sobre todo **dos teléfonos en un mismo campo**
  (`01148975105//01157357632`, `0230 446 3850 - 011 62237092`), letras pegadas
  (`01144532188 SABRINA`) o formatos no reconocidos.
- El único vendedor sin celular es `BARILI MANUEL` (línea fija `2236800402`).
- De los 143 clientes con vendedor, el **vendedor** tiene celular en 141 casos y el **cliente** en
  solo 5: por eso la regla de destinatario del #706 es "vendedor si hay".

---

## 2. Decisiones tomadas

| Decisión | Valor | Quién |
|---|---|---|
| Campo | `whatsapp_phone` en `Client` y en `Salesperson`, nullable | Oscar |
| `phone` | No se borra ni cambia de sentido: queda libre para otros teléfonos | Oscar |
| Backfill | Copia **solo** los celulares ya confirmados (26 clientes, 8 vendedores) | Oscar |
| Fallback de envío | `whatsapp_phone`; si está vacío, `phone` **solo si** clasifica como celular | Oscar |
| Edición | Botón **"WhatsApp"** aparte en la grilla de Clientes, con su propio diálogo | Oscar |
| Carga de los que faltan | **Pantalla en la app** con informe y edición en el lugar | Oscar |
| Preferir `whatsapp_phone` | **Apagada por defecto**; la activa el admin a propósito | Regla del proyecto |

### 2.1 Por qué el fallback (y no cortar)

El campo arranca con 26 clientes y 8 vendedores con WhatsApp. Si el destino de envío pasara a ser
`whatsapp_phone` sin más, **se romperían los envíos que hoy funcionan**: el extracto de cuenta
corriente, el seguimiento de recompra y la lista de precios. Son 4 envíos reales registrados en
`whatsapp_envios`, y el operador los usa todos los días.

Por eso la regla es: `whatsapp_phone` manda; si no está, se cae a `phone` **pero solo si `phone`
clasifica como celular** (los 26 + 8 que el clasificador ya da como enviables). Un "posible" no se
manda solo, igual que hoy: se muestra y lo tilda el operador.

### 2.2 Por qué apagado por defecto

Una migración que cambia de dónde sale el destino de los envíos no puede activarse sola: si el
backfill quedó a medias o el operador todavía no cargó los números, se corta la operatoria diaria.
La preferencia por `whatsapp_phone` arranca en **OFF** y la activa el admin, por puesto, cuando los
números estén cargados.

---

## 3. Diseño

### 3.1 Modelo de datos

```python
class Salesperson(BaseModel):
    name = CharField(unique=True)
    phone = CharField(null=True)
    whatsapp_phone = CharField(null=True)      # nuevo
    email = CharField(null=True)
    ...

class Client(BaseModel):
    ...
    phone = CharField(null=True)
    whatsapp_phone = CharField(null=True)      # nuevo
    ...
```

**Cómo entra la columna:** por `ensure_runtime_schema` (`app/config/schema.py`), que hace
`ALTER TABLE ... ADD COLUMN ... NULL` sobre tablas existentes. La aplica un **administrador** desde
"Crear o actualizar ahora las tablas de FEMAG" o `scripts/init_db.py`. La aplicación **no** toca el
esquema al arrancar: `FemagMySQLDatabase.connect()` solo migra si `FEMAG_AUTO_MIGRATE_SCHEMA=1`.

Sin default: la columna queda en `NULL` para todos. El backfill es un script explícito, no una
migración automática.

### 3.2 La regla de resolución (módulo puro)

Nuevo archivo `app/services/whatsapp_contact_resolver.py`, con la misma forma que
`whatsapp_phone_classifier.py` (función pura, sin base ni interfaz, testeable aislado):

```python
@dataclass(frozen=True)
class WhatsAppContact:
    numero: str                    # normalizado, o "" si no hay destino
    origen: str                    # "whatsapp_phone" | "phone" | ""
    clasificacion: PhoneClassification

    @property
    def enviable(self) -> bool: ...
```

`resolver_contacto(*, whatsapp_phone, phone) -> WhatsAppContact`:

1. Si `whatsapp_phone` tiene contenido → se clasifica. Solo es enviable si da `celular`.
2. Si está vacío → se usa `phone`, y **solo** si da `celular`.
3. Nunca inventa, nunca convierte, nunca "adivina" el 15 de un fijo.

El módulo no decide *a quién* se manda (eso es el #706); decide *qué número* es válido.

### 3.3 Servicio de contacto

`app/services/whatsapp_contact_service.py` — `WhatsAppContactService(current_user)`:

- `set_client_whatsapp_phone(client, numero) -> Client`
- `set_salesperson_whatsapp_phone(salesperson, numero) -> Salesperson`

Ambos:

- **validan** con el clasificador: solo se acepta `celular`. Un "posible" o un inválido se rechaza
  con el motivo (mismo criterio que ya usa `ClientService.set_phone`, pero estricto).
- **guardan el número normalizado** en formato internacional (`549...`), que es el que entiende el
  gateway.
- **auditan** el cambio (`action="actualizar WhatsApp"`, `record_ref="Client:<id>"` /
  `"Salesperson:<id>"`), con el valor anterior y el nuevo.
- **no tocan `phone`** en ningún momento.
- Si el valor no cambió, no escriben ni auditan (igual que `set_phone`).

### 3.4 Interfaz

**Grilla de Clientes** (`app/ui/master_abm.py`): botón **"WhatsApp"** al lado del de "Teléfono", con
el mismo patrón (`edit_client_phone` → `edit_client_whatsapp`), y columna "WhatsApp" en la grilla.

**Diálogo nuevo** `app/ui/client_whatsapp_edit_dialog.py`: un campo, la clasificación en vivo y el
mensaje de por qué no se puede guardar. Reutiliza la lógica de estilos del diálogo de teléfono; lo
común se extrae a un helper (`app/ui/whatsapp_phone_edit_widgets.py`) para **no duplicar** el mapa de
colores ni el botón "Usar el primer número".

Diferencia clave con el diálogo de teléfono: el de teléfono **acepta** un "posible" (una línea fija
sirve para llamar); el de WhatsApp **no**, porque el campo tiene un solo propósito.

**Vendedores** (`app/ui/master_abm.py`, `SalespersonEntryDialog`): campo "WhatsApp" en el alta y la
edición, con la misma validación, y columna en la grilla de Vendedores.

**Pantalla de carga** (nueva, `app/ui/whatsapp_contact_load_dialog.py`): lista de clientes activos
**con orden emitida** y **sin `whatsapp_phone`**, con columnas Cliente, Vendedor, Teléfono actual,
Estado de la clasificación y el WhatsApp cargado. Permite editar y guardar en el lugar.

Respetar el tamaño de la pantalla del cliente (**1638x969** y **1366x768**): la tabla va con scroll
dentro del diálogo, no con la ventana estirada.

### 3.5 Backfill

`scripts/backfill_whatsapp_phones.py`:

- `--dry-run` **por defecto**: informa qué copiaría sin escribir.
- `--apply`: escribe, y solo copia los que el clasificador da como `celular`.
- **Idempotente**: correrlo dos veces no cambia nada (solo copia cuando el destino está vacío).
- **Respaldo previo** de la base antes de escribir (mysqldump desde WSL; el `.cnf` de credenciales va
  dentro de WSL con permisos 600, porque mysqldump ignora los archivos world-readable de `/mnt/c`).
- Salida con: cuántos se copiaron, cuántos quedaron vacíos y por qué motivo.

Con los datos de hoy: **26 clientes + 8 vendedores**. Los 183 "posible" y los 34 inválidos quedan
vacíos **a propósito**: mandarle a un número adivinado es peor que no mandar.

---

## 4. Etapas

| Etapa | Contenido | Estado |
|---|---|---|
| 1 | Modelo + servicio + resolver + edición individual (cliente y vendedor) + backfill | En este PR |
| 2 | Pantalla de carga de pendientes | En este PR |
| 3 | Activar la preferencia por `whatsapp_phone` (flag) | **Fuera de este PR**: la habilita el admin cuando los números estén cargados; es parte del #706 |

Las etapas 1 y 2 son el mismo PR porque son la misma unidad de trabajo (el contacto de WhatsApp del
cliente y del vendedor). La etapa 3 queda atrás del flag y no se activa por código: la decide el
admin.

---

## 5. Validaciones

**Unitarias**

- Resolver: con `whatsapp_phone` válido / vacío / inválido; con `phone` celular / posible / inválido /
  vacío; la precedencia y el `origen` que se reporta.
- Servicio: acepta celular, rechaza "posible" e inválido con motivo; guarda normalizado; no toca
  `phone`; no escribe si no cambió; audita.
- Backfill: copia solo celulares; es idempotente; no toca registros fuera de criterio.

**Suite**

```bash
git diff --check
python -m pytest
python -m compileall app
python -m app.main --smoke
```

**Contra la base real (MariaDB de WSL, puerto 3308)**

- Aplicar la columna por el camino oficial (`init_db.py` o el asistente).
- Correr el backfill en `--dry-run` y revisar el informe **antes** de `--apply`.
- Con respaldo previo: aplicar, y verificar con consultas de solo lectura.
- Restaurar la base con el dump limpio al terminar.

**Visual**

- Grilla de Clientes y de Vendedores, diálogo de edición y pantalla de carga, a **1638x969** y
  **1366x768**.

---

## 6. Fuera de alcance

- El envío automático de presupuestos al emitir la orden: es el **#706**.
- El envío masivo de lista de precios: es el **#705**.
- Cargar emails: el canal de correo del #706 hoy no tiene ningún destinatario posible (0 emails de
  clientes y de vendedores). Es un issue aparte.
- Cambios en cálculos, documentos o impresión de presupuestos.

---

## 7. Riesgos

| Riesgo | Mitigación |
|---|---|
| Es un **cambio de modelo** (área protegida en `AGENTS.md`) | Alcance explícito, respaldo previo y validación contra la base real antes de producción |
| El backfill **escribe en datos de producción** | Script explícito, `dry-run` por defecto, idempotente, con salida auditable |
| El backfill **no resuelve** los 183 "posible" ni los 34 inválidos | Quedan vacíos a propósito; hay una pantalla para cargarlos |
| Cambia el **origen del destino** de los envíos | El flag arranca **OFF**; con el fallback a `phone` no se rompe ningún envío |
| El vendedor `BARILI MANUEL` tiene línea fija | Queda sin WhatsApp después del backfill; hay que cargarlo a mano |
| El importador legacy puede pisar `phone` | No toca `whatsapp_phone`; el campo nuevo no se pisa |

---

## 8. Pendientes

- [x] Verificar contra la base real que el backfill copia lo que corresponde y nada más (14/11/2026: 28 clientes + 8 vendedores; el teléfono general quedó intacto; la corrida es idempotente).
- [ ] Cuando el admin active el flag, avisar en el #706 (que es quien consume el resolver).
- [ ] En la planta: aplicar la columna por el camino oficial (`scripts/init_db.py`) y correr el backfill
      con vista previa antes de `--aplicar`.
- [ ] Issue aparte: el clasificador no acepta un internacional escrito **sin** el `+` (por ejemplo
      `5491153088679`). Hoy el backfill y la edición guardan la forma canónica sin `+` y la pantalla de
      envío muestra la forma internacional; el que escribe a mano ese formato sin `+` recibe un rechazo.
- [ ] Issue de UX aparte: la grilla de Clientes ya excedía el ancho de la pantalla del cliente
      (1638x969) antes de este cambio, y el botón nuevo suma 142 px a una fila que ya tenía 11 botones.

**Decisiones menores tomadas al escribir esta especificación** (no requieren consulta):

- La columna se muestra como **"WhatsApp"** en todas las pantallas, para que el operador la
  distinga del teléfono de un vistazo.
- La pantalla de carga ordena por **fecha de la última orden emitida, de más nueva a más vieja**:
  primero los clientes que tienen movimiento reciente, que son los que más duelen si no les llega
  el presupuesto. El filtro por defecto es "clientes con orden emitida"; hay una opción para ver
  todos los clientes sin WhatsApp, incluidos los que nunca compraron.

---

## 9. Bitácora

| Fecha | Qué pasó |
|---|---|
| 13/11/2026 | Auditoría de la base real: 26 celular / 183 posible / 34 inválido / 661 vacío en 904 clientes; 8 de 9 vendedores con celular. El canal de correo no tiene ningún destinatario posible. |
| 13/11/2026 | Decisiones tomadas con Oscar: campo dedicado, `phone` libre, backfill solo de celulares confirmados, fallback a `phone` si es celular, botón "WhatsApp" aparte, pantalla de carga en la app, preferencia apagada por defecto. |
| 13/11/2026 | Diseño aprobado. Rama `feat/issue-923-whatsapp-dedicado` creada desde `main`. |
| 14/11/2026 | Implementado en `feat/issue-923-whatsapp-dedicado`: campo, resolver, servicio, flag, diálogos, grilla, pantalla de carga, backfill con script y los envíos tomados del resolver. 11 tareas, cada una con revisión propia. |
| 14/11/2026 | **La forma canónica:** lo que se guarda es el normalizado **sin `+`** (`5491153088679`), y ni el resolver ni el diálogo de envío aceptaban esa forma. El resolver ahora clasifica la forma canónica como si estuviera escrita con `+`, y el prefill de la pantalla muestra la forma internacional (`+549...`), que es la única que acepta el envío de hoy. Sin tocar el clasificador. |
| 14/11/2026 | **El prefill decide qué número se muestra, no si se puede enviar:** con el flag apagado es exactamente el teléfono de siempre, y la validación sigue en el diálogo, como hoy. Los 5 flujos de envío (extracto, presupuesto, resumen de cartera del vendedor, seguimiento de recompra, ficha de cliente) toman el destino del resolver. |
| 14/11/2026 | **Validación contra la base real** (MariaDB de WSL, `127.0.0.1:3308`, base `femag_desktop`): `scripts/init_db.py` (el camino oficial del administrador) creó las dos columnas `whatsapp_phone`. El backfill aplicó **28 clientes + 8 vendedores** (903 clientes, 8 vendedores); 875 contactos quedan sin destino a propósito para que los confirme el operador. El teléfono general no cambió (mismo conteo y mismo CRC32), quedaron 36 filas de auditoría `actualizar WhatsApp` y la segunda corrida copió 0. Al final la base se restauró con el dump limpio. |
| 14/11/2026 | La copia local de la base se restauró desde el dump del 7/11, que es anterior al import del 13/11: eso revirtió en la **copia local** el resultado de ese import (4 clientes, 1 vendedor, 21 órdenes, 60 destinos y 1096 filas de auditoría). El origen del import (`/home/oscar/cb_restore/cyberbrain.bak`) quedó intacto y el importador se re-ejecuta por `legacy_id`. La base de producción del cliente no se tocó. |

