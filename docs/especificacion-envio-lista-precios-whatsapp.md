# Envío de lista de precios por WhatsApp — Especificación

**Issue de referencia:** #705 (tracking) · **Issue relacionado:** #706 (presupuestos, otro pedido)
**Fecha:** 22/10/2026 · **Estado:** propuesta para aprobación, sin implementación

---

## 1. Contexto: qué pidió Gabriela

Mensajes del 21 y 22 de octubre (WhatsApp, Femag / Oscar Vogel):

> **Femag (21/10):** "Ya esta corregida las listas, los mayoristas de siempre tienen lista 1."
>
> **Femag (22/10 16:47):** "Hola Oscar, estoy por pasar una nueva lista, probamos con el sistema?"
>
> **Oscar (22/10 16:49):** "aun no importe y no arme el modulo de envio"
>
> **Oscar (22/10 16:50):** "contame como queres hacerlo, que puedas seleccionar un pdf y que tome
> automaticamente del sistema la lista que seleciones y envie por whatsapp?? asi seria?"
>
> **Femag (22/10 16:50):** "Era por si eso estaba para probar. Si algo asi."

Traducción a requisitos:

1. Elegir un **PDF** (la lista de precios ya armada) desde el equipo.
2. Elegir la **lista de precios** (1 a 4) en el sistema.
3. El sistema **toma solo** los clientes de esa lista y les manda el PDF por WhatsApp, usando la
   **instancia de Gabriela**.
4. **Restricciones de Oscar:** no enviar de golpe a todos (WhatsApp bloquea la línea) y **no
   bloquear la interfaz**, porque ella tiene que seguir trabajando mientras se envía.

### Decisiones tomadas el 22/10 (Oscar)

| Decisión | Qué implica en el diseño |
|---|---|
| **El PDF va por lista** | Cada lista tiene **su propio PDF**. El combo de lista trae el PDF ya associated; no se puede mandar el PDF de otra lista por accidente. La asociación se guarda en `AppParameter` (sin migración de modelo). |
| **100 mensajes por día** | Tope diario por instancia, contado desde la auditoría. Cuando se llega, la campaña se detiene con un mensaje claro y sigue al día siguiente. |
| **El Excel se importa: la lista y el teléfono** | Nuevo módulo: importación del `.xlsx` que aplica **`lista_precios`** y **completa `phone` si está vacío**. Ningún otro campo del archivo se escribe, y ningún dato existente se pisa. Ver §5. |
| **El mensaje puede cambiar** | Plantilla de mensaje **por lista**, editable, con variables `{cliente}`, `{lista}`, `{empresa}`. Se puede pisar para una campaña puntual. |

Artefacto de entrada: `docs/clientes_20261021.xlsx` (export de la lista de clientes con la columna
`Lista` ya corregida).

---

## 2. Auditoría del estado real (Regla 2 de `AGENTS.md`)

| Dato | Valor |
|---|---|
| Repo | `oscarvogel/femag_desktop` |
| Rama actual | `feat/issue-740-sobre-automatico` (**1 commit adelante de `main`, 3 atrás**) |
| `main` | `12ef1fe` — 21/10 15:28, "la promoción a producción queda diferida hasta la prueba del operador" |
| Árbol de trabajo | **sucio**: `app/config/envelope_settings.py` y `app/services/envelope_print_service.py` modificados, un PNG de `docs/prints/` modificado, y varios archivos sin trackear (`docs/clientes_20261021.xlsx`, `docs/VENTAS.xlsx`, `importar_desde_cero.py`, entre otros) |
| Issue | **#705** "Envío masivo de lista de precios en PDF por WhatsApp y correo con throttling (1 cada 2-3 min)" — abierto, sin comentarios, es el tracking issue de este pedido |
| Issue relacionado | **#706** "Envío automático de presupuestos por WhatsApp al emitir" — abierto, es otro pedido, no se toca acá |
| PRs abiertos | #755 (sobre automático), #757 (producción webapp móvil) — ninguno relacionado |
| Trabajo duplicado | **No crear issue nuevo**: este pedido ya está representado en #705 |
| Base de testeo | **Armada el 22/10**: dump `Downloads/femag_desktop.sql` (MySQL 5.7 del cliente, 20/10) importado en MariaDB de WSL (puerto 3308), usuario `femag`, y `python -m app.main --smoke` → OK contra la base real. Comandos en §9 |

### Qué está hecho hoy

- Envío 1 a 1 de un PDF por WhatsApp: `WhatsAppSendDialog` (`app/ui/whatsapp_send.py`) +
  `WhatsAppEnvioService` (`app/services/whatsapp_envio_service.py`) + `WhatsAppApiClient.upload_document`
  (`app/services/whatsapp_api_client.py:191`).
- El envío 1 a 1 **ya corre en background** con `QRunnable` + `QThreadPool` (`app/ui/desktop_app.py:1494`),
  o sea que **la UI no se congela**: ese patrón se reutiliza tal cual.
- Auditoría persistida: tabla `whatsapp_envios` (modelo `WhatsAppEnvio`, `app/models/whatsapp.py`),
  con estados `preparing/queued/accepted/delivered/read/failed`, `messageId`, `error` y usuario.
- Instancia por usuario: `User.whatsapp_instance_id` + resolución en
  `WhatsAppEnvioService._resolve_instance_for_user` (`app/services/whatsapp_envio_service.py:34`).
- Gateway configurable y central: `WhatsAppCentralConfigurationService` (`app/services/whatsapp_configuration_service.py`).
- El maestro `Client` ya tiene `lista_precios` (1 a 4, `app/models/masters.py:121`), `phone`, `email`,
  `active` y `salesperson`. La grilla de clientes ya exporta a Excel (`app/reports/client_list_export.py`).
- Configuración clave-valor sin migrar: `AppParameter` (`app/models/system.py:6`), que ya usa
  `WhatsAppCentralConfigurationService` para la configuración central del gateway.

### Qué falta (y es el pedido)

- Importación del Excel que solo toque `lista_precios`.
- Asociación lista ↔ PDF y plantillas de mensaje por lista.
- Selección del destinatario por lista de precios.
- Cola con **throttling** (1 cada 2-3 min), **pausa / cancelar / reanudar**, **tope de 100/día**.
- **No bloquear la UI** durante el lote.
- Registro de omitidos y reintento de fallidos.

### Lo que está roto y hay que arreglar antes de enviar (hallazgo nuevo)

El normalizador actual convierte **fijos en móviles falsos** y los manda como si fueran celulares.
`normalize_whatsapp_phone` (`app/services/account_statement_share_service.py:7`) no distingue un
celular (el "15" después del código de área) de una línea fija:

| Teléfono guardado | Lo que produce hoy | ¿Es celular? |
|---|---|---|
| `011 3042 6170` | `5491130426170` | **No**, es un fijo de CABA |
| `0340 4422412` | `5493404422412` | **No**, es un fijo de Córdoba |
| `3404 633133 - 3404 634132` | número corrupto | No, son dos teléfonos en un mismo campo |
| `TTE.SERVIBAIRES LARRAZABAL2562` | se rechaza | No, es texto |
| `+5491157489959` | `5491157489959` | Sí |
| `0221 15 4947551` | `5492214947551` | Sí |

Sobre la base real (203 clientes activos con teléfono), el normalizador de la app **devuelve un
número para 199, de los que solo 26 son celulares**: los otros **173** son líneas fijas o números
dudosos a los que el fallback `"549" + número_local` les cuela el "9" móvil. Mandar la lista a esos
173 sería mandarla a números que no son de los clientes (o a números que no existen): lo que más
rápido quema la línea de Gabriela.

---

## 3. Hallazgo central: la audiencia real es mucho más chica que "la lista"

Estos números están **verificados contra la base real del cliente** (dump `femag_desktop.sql` del
20/10, restaurado en MariaDB de WSL — ver §9), no solo contra el Excel:

| Dato | Base real (dump 20/10) | Excel `clientes_20261021.xlsx` |
|---|---|---|
| Clientes totales | **884** | 901 |
| Activos / inactivos | 882 / 2 | 899 / 2 |
| **Lista 1** | **876** | **893** |
| **Lista 2** | **8** | **8** |
| Lista 3 / Lista 4 | 0 / 0 | 0 / 0 |
| Clientes **sin teléfono** | **679** | 686 |
| **Celulares** (el "15" detrás del área o el formato `+549...`) | **26** → 25 en lista 1, 1 en lista 2 | **27** → 25 en lista 1, 2 en lista 2 |
| **Posibles móviles** (10 u 11 dígitos, sin el "15": puede ser fijo o móvil escrito así) | **142** | 153 |
| Teléfono que **no sirve** (letras, dos teléfonos en un campo o formato raro) | **35** | 35 |
| Clientes con **email** | **0** | **0** |

La diferencia de 17 filas entre el Excel y la base es que el Excel es del 21/10 (un día posterior al
dump) e incluye **8 clientes que no están en el dump** (`CONSUMIDOR FINAL`, `NOGALES ARGENTINOS`,
`RODRIGUEZ JAVIER`, `RUIZ ELVIO RAMON`, `DISTRIB.DE INSUMOS Y MAT.PRIMAS EG SRL`,
`DOS SANTOS NICOLAS FABIAN`, `GALLI JUAN`, `LULEMUU S.R.L.`), más filas duplicadas de clientes que
ya están duplicados en la base (§5.5).

Consecuencias directas para el diseño:

1. **"Enviar la lista 1" hoy son 25 mensajes seguros, no 893** (26 en total si se cuentan los de
   lista 2). El riesgo de bloqueo no viene del volumen de esta campaña: viene del volumen de las
   campañas *futuras* (cuando Gabriela reparta las listas con la importación nueva) y de mandar a
   números equivocados.
2. **El throttle no es el problema principal; la calidad del dato es.** Con 679 clientes sin
   teléfono, el cuello de botella real es que el maestro no tiene el celular del 77 % de los
   clientes. Por eso el spec incluye (Fase C) un reporte de "clientes de esta lista sin WhatsApp"
   para que Gabriela los busque y complete. La importación del Excel **suma 8 teléfonos** (todos
   fijos, §5.5.2): mejora el dato para llamar, pero **no agranda la audiencia de WhatsApp**.
3. **El canal email es inviable hoy:** el maestro no tiene ni un email. La parte de email de #705
   queda fuera de alcance con evidencia, no por convenience.
4. Los 142 "posibles móviles" (10 u 11 dígitos sin el "15") **no se mandan por defecto**: se muestran
   en la vista previa con el número exacto que se enviaría, y los tilda el operador. Son la
   diferencia entre una campaña de 26 mensajes y una de 168, y decidir eso es suyo, no del
   sistema.
5. Los números de arriba son **una foto del 20-21/10**, no un dato fijo: la pantalla debe **calcular
   la audiencia en el momento** contra la base real y mostrar los contadores antes de enviar.

---

## 4. Diseño: envío por WhatsApp

### 4.1 PDF y mensaje por lista

Cada lista (1 a 4) tiene **su PDF** y **su plantilla de mensaje**, configurables en la pantalla:

- **PDF:** botón "Seleccionar PDF" por lista → `QFileDialog`; valida existencia, tamaño > 0 y
  extensión `.pdf`. Queda associated a la lista en `AppParameter` (`lista_precios_pdf_{N}` → ruta),
  así que la próxima vez ya está cargado. También un botón "Buscar `lista{N}.pdf` en una carpeta"
  que los baja todos de una.
- **Mensaje:** editor de texto por lista, con variables `{cliente}`, `{lista}`, `{empresa}`.
  Default si no hay: *"Hola {cliente}, adjuntamos la lista de precios {lista} de FEMAG. Quedamos a
  disposición."* Se guarda en `AppParameter` (`lista_precios_mensaje_{N}`) y se puede pisar para una
  campaña puntual.
- Si la lista elegida **no tiene PDF associated**, el botón "Iniciar envío" queda deshabilitado con
  el motivo a la vista: no hay forma de mandar el PDF de otra lista sin cambiarlo a mano.
- El PDF que se está por enviar se muestra **siempre** junto a la lista, antes de confirmar.

> No se agrega ninguna tabla: `AppParameter` ya existe y es clave-valor
> (`app/models/system.py:6`), así que las áreas protegidas (modelos/migraciones) no se tocan.

### 4.2 Pantalla "Envío de lista de precios"

Página nueva en la app (ruta propia, en el grupo **Informes** → "Envío de lista de precios").
Debe entrar en **1366×768 y 1638×969** (resolución del cliente): va envuelta en `QScrollArea`
como las páginas corregidas en #748/#749, con la tabla de destinatarios dentro de un `QSplitter`.

**Paso 1 — Preparar**

- **Lista de precios:** combo `1 / 2 / 3 / 4` (los valores que acepta `ClientService`). Al elegirla
  carga su PDF y su mensaje.
- **PDF** y **mensaje**: como en §4.1 (editables para esta campaña).
- **Intervalo:** spinner en segundos, default **180 s (3 min)**, mínimo 60 s, máximo 600 s.
  Botón "Usar 10 s (modo prueba)".
- **Lote inicial:** spin, default 20 (los primeros 20 y después ella decide si sigue).

**Paso 2 — Calcular destinatarios (botón "Calcular destinatarios")**

Recalcula la audiencia **contra la base real** y la muestra antes de tocar el gateway:

| Contador | Significado |
|---|---|
| Clientes de la lista | total con `lista_precios = N` |
| Sin teléfono / fijos / texto inválido | los que **no** se pueden mandar |
| **Celulares válidos** | los que realmente se van a enviar |
| Ya enviados hoy | los que cuentan contra el tope de 100/día |
| Destinatarios marcados a mano | los que ella deseleccionó en la tabla |

Tabla previa con una fila por cliente: nombre, teléfono **como está guardado**, teléfono
**normalizado** (el que se va a mandar), estado y checkbox para excluir. Default: los celulares
válidos marcados, los demás visibles pero no marcados (para que vea qué se está dejando afuera y
por qué).

> **Confirmación explícita:** el botón "Iniciar envío" muestra *"Se enviarán N mensajes desde tu
> instancia de WhatsApp"* y exige tildar *"Entiendo que sale desde mi línea"*.

**Paso 3 — Enviar y seguir trabajando**

Botón "Iniciar envío" → arranca el lote y **deja la pantalla libre**. Puede navegar a otras
pantallas y seguir operando; al volver, la página muestra el estado del lote en curso.

**Paso 4 — Seguimiento (tabla en vivo, misma pantalla)**

| Columna | Contenido |
|---|---|
| Cliente / Teléfono | nombre y normalizado |
| Estado | `en cola` → `enviando` → `enviado` / `falló` / `omitido` |
| Detalle | `messageId` o el motivo del error |
| Hora | timestamp real del envío |

Barra de progreso, contador `enviados / total`, **ETA** calculado con el intervalo, y botones:
**Pausar**, **Cancelar**, **Reintentar fallidos**, **Exportar log (CSV)**.
Al terminar: resumen (`enviados`, `fallidos`, `omitidos`) con el motivo de los fallos.

### 4.3 Motor de envío (lo que garantiza que no se bloquea nada)

Proceso: **un solo hilo de trabajo, secuencial, con espera entre envíos.** La UI nunca espera al
gateway: el hilo hace el `sleep` y la ventana de Qt sigue respondiendo.

- **Hilo:** `QRunnable` + `QThreadPool`, el mismo patrón que ya usa `WhatsAppSendWorker`
  (`app/ui/whatsapp_send.py:108`) y que ya se usa en `desktop_app.py:1494`. La UI solo se actualiza
  por señales (`pyqtSignal`), nunca tocando widgets desde el hilo.
- **Orden:** el PDF se sube **una vez** al gateway y se reutiliza el `messageId` para cada
  destinatario, si el gateway lo permite; si no, se sube por destinatario (es lo que ya hace hoy).
  A definir contra el gateway real, con fallback seguro.
- **Intervalo:** `espera = intervalo ± 10 %` (jitter). El jitter evita el patrón mecánico que los
  gateways detectan. El intervalo se cuenta **desde el envío anterior**, no desde el inicio.
- **Lote inicial y pausa:** al completar el lote inicial el hilo **se detiene solo** y la pantalla
  avisa: *"20 enviados. ¿Continuar con los 30 restantes?"*. Ella puede seguir trabajando y
  reanudar cuando quiera.
- **Tope diario de 100 por instancia:** se cuenta desde `whatsapp_envios` (filas de
  `tipo_documento=lista_precios`, `instance_id` de la usuaria, creadas hoy). Al llegar a 100, la
  campaña se detiene: *"Límite diario alcanzado (100). Mañana continúa."* **Sin tabla nueva.**
- **Circuit breaker:** si el gateway responde con error de rate-limit/ban (HTTP 429 o error
  equivalentes), el hilo **para la campaña completa**, deja el resto en `en cola` y avisa. Nunca
  insiste contra un rechazo.
- **Reintentos:** máximo 2, solo para errores transitorios (timeout, 5xx), con espera creciente.
  Los errores permanentes (número inválido, 4xx) no se reintentan: quedan `falló` con motivo.
- **Cancelar:** detiene el envío en el próximo punto seguro; lo ya enviado no se puede deshacer.
- **Base de datos:** peewee abre la conexión por hilo (thread-local), así que el worker escribe sus
  estados sin interferir con la UI. Reusa `FemagMySQLDatabase`, que ya reconecta sola si se cae la
  conexión.

### 4.4 Datos, trazabilidad e idempotencia (sin migración de base)

**No se crea ninguna tabla nueva** (las áreas protegidas del `AGENTS.md` no se tocan):
se reusa `whatsapp_envios`, que ya existe en la base del cliente (`ALL_MODELS` incluye
`WhatsAppEnvio`; `ensure_runtime_schema` la crea con `safe=True`).

- `tipo_documento = "lista_precios"`
- `documento_id = <clave de campaña>`, con el formato
  `lista{N}-{nombre_del_pdf_sin_extension}-{AAAAMMDD-HHMM}`
  → una campaña es "lista 1 + lista1.pdf + 22/10 17:30". Sirve para retomar, auditar y no repetir.
- `estado`: los estados que ya usa el modelo (`queued`, `accepted`, `delivered`, `read`, `failed`).
  Los **omitidos** (sin celular válido) **no se persisten**: son ruido; se exportan a CSV.
- **Idempotencia:** antes de enviar, se consultan los envíos de esa clave de campaña y se excluye
  a quien ya tenga estado terminal (`delivered`, `read`, `failed`). Reanudar la campaña = audiencia
  calculada − ya enviados.
- `external_ref` es `unique`: cada destinatario tiene su propio `femag:lista_precios:<clave>:<id>`.
- El `usuario` que figura en cada fila es el de la sesión (Gabriela), y `instance_id` es el de su
  instancia, así que la auditoría dice exactamente desde qué línea salió cada mensaje.

### 4.5 Reglas de destinatario (el filtro que evita mandarle a fijo o basura)

El filtro nuevo **no** reemplaza al normalizador de los envíos 1 a 1 (los extractos y presupuestos
ya funcionan y no se tocan en este PR), pero **sí corrige el error de fondo** que lo hace dudoso:
el fallback `"549" + número_local` le pone el "9" móvil a cualquier línea fija de 10 dígitos. En la
base real del cliente eso son **173 teléfonos que el sistema daría por móviles y no lo son**. Por
eso el clasificador nuevo va al lado, y la pantalla de lista de precios usa el nuevo.

La clasificación tiene **tres** estados, no dos, porque un número local de 10 dígitos **no se
puede distinguir** entre fijo y móvil escrito sin el "15":

| Estado | Qué es | Qué hace la pantalla |
|---|---|---|
| `celular` | Tiene el "15" después del código de área, o viene en formato internacional `+549...` (**26 clientes**: 25 en lista 1, 1 en lista 2) | **Se manda** sin preguntar. Normalizado `549` + área + suscriptor |
| `posible` | 10 u 11 dígitos: código de área + número, **sin el "15"**. Puede ser un fijo o un móvil escrito así (**142 clientes**) | **No se manda por defecto.** Aparece en la vista previa con el número exacto que se mandaría, y el operador lo tilda si quiere |
| `invalido` / `vacio` | Letras, número muy corto, dos teléfonos en un campo, formato raro, o sin dato (**35** y **679** clientes) | **No se manda**, con el motivo a la vista |

Reglas del clasificador (`clasificar_telefono(texto) -> (estado, normalizado, motivo)`):

1. Teléfono vacío → `vacio` ("sin teléfono").
2. Teléfono con letras → `invalido` ("tiene letras").
3. Teléfono con más de un número en el mismo campo (ej. `3404 633133 - 3404 634132`) → `invalido`
   y se propone el primero para que el operador lo tilde a mano.
4. `celular` si: tiene el "15" después del código de área, o viene en formato internacional
   `+549` + área + suscriptor, o arranca con `15` + número sin área. **El código de área nunca
   puede empezar con 0**: el 0 inicial es del prefijo local, no del área (`011 15 53088679` → área
   `11`, no `011`). El área tiene 2 dígitos (solo el `11`), 3 o 4, y el suscriptor 6, 7 u 8: no
   todos los lugares tienen el mismo largo (`+54 9 3416 51-0261` es de Rosario, con 6).
5. `posible` si son 10 u 11 dígitos locales sin el "15" (área + número), o si viene en formato
   internacional **sin el "9"** del móvil (`+54 3416 510261`). El normalizado que se mostraría es
   `549` + área + número, **que es justo lo que la app manda hoy**: por eso se muestra, para
   que el operador decida.
6. Inactivo → omitido.
7. Todo lo que no pasa el filtro queda en la tabla previa, con su motivo, para que el número de
   "enviados" nunca sea una sorpresa.

> El filtro se implementa como una función pura y testeable (tipo
> `clasificar_telefono(texto) -> (estado, normalizado, motivo)`), en un servicio nuevo, para poder
> testearla sin base ni gateway.

### 4.6 Instancia de WhatsApp

La instancia es **la del usuario logueado** (`User.whatsapp_instance_id`), resuelta por
`WhatsAppEnvioService._resolve_instance_for_user` — no hay que elegirla a mano en la pantalla.
Si el usuario no tiene instancia, la pantalla lo avisa **antes** de empezar y no deja arrancar
(el error actual aparece recién al enviar). La configuración central del gateway
(`WhatsAppCentralConfigurationService`) se usa tal cual: no se toca ni se duplica.

### 4.7 Idioma y textos de la pantalla

Todo en español rioplatense, con los mismos textos que ya usa la app ("No se pudo conectar con el
gateway de WhatsApp.", "El usuario no tiene una instancia de WhatsApp asociada."). Los mensajes
de error técnicos van al log y en pantalla va una explicación accionable.

---

## 5. Diseño: importación de la lista de precios desde Excel

### 5.1 Qué hace y qué NO hace

**Hace dos cosas, y solo dos:**

1. Escribir `Client.lista_precios` del cliente que matchea con la fila del archivo.
2. **Completar** `Client.phone` **cuando el cliente no tiene teléfono** en la base.

**Nada más.** Con la misma disciplina del modo `patch` de #746/#747: la importación **completa lo
que falta** y **no pisa lo que ya está**.

- **Nunca** escribe nombre, CUIT, email, contacto, vendedor, plazo de pago, activo, saldo ni
  ningún otro campo, **aunque el archivo traiga un valor distinto**. Se reporta la diferencia para
  que la vea, pero no se aplica (caso real: 2 diferencias de nombre y 1 de condición de IVA, §5.5.2).
- **Nunca** pisa un teléfono que ya está en la base, ni siquiera si el archivo trae otro (hoy no
  hay ningún caso así: §5.5.2).
- **Nunca** borra un teléfono: si el archivo viene sin teléfono, el de la base se conserva.
- **Nunca** crea clientes que no están en la base.
- **Nunca** borra ni desactiva clientes.
- Los clientes de la base que **no** aparecen en el archivo quedan **como están**.

> **Por qué el teléfono entra y no antes:** el Excel de Gabriela trae **7 teléfonos que la base no
> tiene** (§5.5.2). Son datos que ella puso y que no llegaron a la base; si la importación solo
> "tocara la lista", ese trabajo se pierde. Y el riesgo de meterlos es nulo con la regla de
> "solo si está vacío": no se pisa nada.

### 5.2 Formato del archivo

Es el **mismo formato que exporta la app** (`app/reports/client_list_export.py`), así que el
circuito es: exportar → Gabriela edita la columna `Lista` → importar. Columnas del archivo:

`Nombre / Razón social` · `CUIT` · `Cond. IVA` · `Celular / Teléfono` · `Email` · `Contacto` ·
`Vendedor` · **`Lista`** · `Estado`

- Se **exigen** solo dos columnas: `CUIT` y `Lista`. Las demás se leen pero se ignoran (salvo
  `Celular / Teléfono`, que se usa **solo para completar**).
- Si el archivo tiene menos columnas, se acepta igual (con `CUIT` y `Lista`).
- La columna `Lista` debe ser un entero **1, 2, 3 o 4** (mismo criterio que
  `ClientService.create_client`, `app/services/client_service.py:33`). Otro valor → la fila se
  reporta como inválida y no se aplica.
- La columna `Celular / Teléfono` **solo completa**: si el cliente ya tiene teléfono en la base, se
  respeta el de la base y la diferencia queda reportada, no aplicada.
- Fila vacía → se ignora.

### 5.3 Cómo se matchea cada fila

El CUIT es la clave, pero **el CUIT de la base puede venir con separadores** (el legacy los dejó
así: `20- 29646152-1`), así que la comparación es **por dígitos**, no por texto:

1. **CUIT normalizado** = solo dígitos. Si queda vacío o es todo ceros → el CUIT no sirve
   (mismo criterio que `_clean_cuit` del importador DBF, `app/importers/legacy_dbf.py:748`).
2. Si hay CUIT utilizable → se busca el cliente por **CUIT normalizado**.
3. Si **no** hay CUIT utilizable → se busca por **nombre normalizado** (sin acentos, en mayúsculas,
   con espacios colapsados), siempre que dé **un solo** cliente.
4. Si el CUIT normalizado corresponde a **varios** clientes de la base → **ambiguo**: no se aplica,
   se reporta.
5. Si en el **archivo** el mismo CUIT normalizado aparece con **listas distintas** → **conflicto**:
   no se aplica ninguna de esas filas, se reporta (ver §5.5).
6. Si en el archivo el mismo CUIT aparece con la **misma** lista → es el mismo cliente escrito de
   dos formas: se aplica una vez y se reporta el duplicado.

> Para 901 clientes, el lookup se hace **en memoria**: se trae la tabla una vez, se indexa por CUIT
> normalizado y por nombre normalizado, y se resuelve cada fila sin 901 queries. Si el maestro
> llegara a 100 000 clientes, esto hay que pasarlo a indexación en SQL (o a una columna de CUIT
> normalizado) — queda anotado, no es el caso de hoy.

### 5.4 Vista previa obligatoria (dry run) antes de tocar nada

Importar 901 filas sin revisarlas es impensable. Antes de escribir, la pantalla muestra:

| Bloque | Contenido |
|---|---|
| **Resumen** | filas del archivo, clientes de la lista antes, clientes que van a cambiar |
| **A cambiar** | CUIT, nombre, lista actual → lista nueva (con el motivo del match: CUIT o nombre) |
| **Sin cambio** | ya están en esa lista |
| **Con conflicto** | mismo CUIT con listas distintas en el archivo, o CUIT ambiguo en la base |
| **No encontrado** | la fila no matchea ningún cliente de la base (no se crea nada) |
| **Lista inválida** | valor fuera de 1..4 o celda vacía |
| **Faltantes** | clientes de la base que no están en el archivo (quedan como están) |

Con el botón **"Aplicar"** deshabilitado mientras haya conflictos sin resolver, y un botón para
exportar la vista previa a CSV.

### 5.5 Lo que la importación tiene que resolver con este archivo concreto

El `docs/clientes_20261021.xlsx` tiene tres problemas de datos que la importación **no puede
ignorar**:

**a) 8 CUITs aparecen repetidos.** En 7 de los casos es **el mismo cliente escrito de dos formas**
(el CUIT con guiones en una fila y plano en la otra); en 1 caso son **dos nombres de empresa
distintos con el mismo CUIT**:

| CUIT | Filas | Qué son |
|---|---|---|
| `20296461521` | 84 (BAREIRO JAVIER, **lista 2**) y 85 (BAREIRO JAVIER, **lista 1**) | Mismo cliente, **listas distintas** → conflicto |
| `30718532066` | 119 (BUENOS ALIMENTOS, **lista 2**) y 120 (BUENOS ALIMENTOS S.R.L, **lista 1**) | Mismo cliente (variante de nombre), **listas distintas** → conflicto |
| `30719437709` | 187 (CODIGO ANIMALS.R.L, **lista 2**) y 188 (CODIGO ANIMAL S.R.L, **lista 1**) | Mismo cliente, **listas distintas** → conflicto |
| `27385135918` | 403 (GIMENEZ ROMINA JAQUELINE, **lista 1**, Activo) y 404 (GIMENEZ ROMINA JAQUELINE, **lista 2**, Inactivo) | Mismo cliente, **listas distintas** + estado distinto → conflicto |
| `27298529446` | 430 (GUIZZETTI, **lista 2**) y 431 (GUIZZETTI, **lista 1**) | Mismo cliente, **listas distintas** → conflicto |
| `27924639240` | 607 y 608 (MIRANDA ZURITA EPIFANIO, **lista 1** y **lista 1**) | Mismo cliente, misma lista → se aplica una vez |
| `30714827975` | 633 (MUSLI WOLKEN S.A, **lista 2**) y 634 (MUSLI WOLKEN S.A, **lista 1**) | Mismo cliente, **listas distintas** → conflicto |
| `30693299930` | 671 (PANYMAX S.A, **lista 1**) y 702 (PRINWEY ALIMENTOS S.A, **lista 1**) | **Dos nombres, mismo CUIT y misma dirección** → es el mismo cliente con el nombre cambiado → a unificar |

**Regla:** si el mismo CUIT normalizado aparece en el archivo con **listas distintas**, **no se
aplica** y se reporta el conflicto. No se elige "la última" ni "la primera" en silencio: son 6
clientes donde adivinar mal cambia el precio de venta. Gabriela los resuelve en el Excel (deja
una sola fila por cliente) y reimporta.

**b) 10 filas sin CUIT real** (`'0'`, `''`, `'00000000000'`, `None`): se matchean por nombre normalizado.
Incluye `CONSUMIDOR FINAL` (fila 197) y `CACERES RAMON` (fila 128, CUIT `'0'`). Si el nombre no da
un único cliente → "no encontrado", sin crear nada.

**c) 5 CUITs con formato raro**: uno de 8 dígitos, uno de 9, uno de 10, dos con prefijo `12`
(no es prefijo AFIP). El match es por dígitos, así que funcionan igual, pero se reportan como
advertencia ("CUIT con formato inusual") para que ella lo mire.

### 5.5.1 Lo que la base real tiene de duplicado (esto hay que arreglarlo antes de importar)

El dump real muestra que **la duplicación no está solo en el Excel: está en la base**. Medido
**por CUIT normalizado** (solo dígitos) sobre los 884 clientes del dump, hay **3 grupos con el
mismo CUIT (6 filas)** y **2 grupos con el mismo nombre normalizado (4 filas)**. El índice único de
`client.cuit` no los frena porque el CUIT se comparaba **por texto**: una fila tiene el CUIT con
guiones y la otra sin guiones, y para la base son cadenas distintas:

| Cliente | Fila 1 | Fila 2 | Qué implica |
|---|---|---|---|
| **GIMENEZ ROMINA JAQUELINE** | id 850 · cuit `27385135918` · **lista 1** · activo · **sin teléfono** · del legacy | id 865 · cuit `27-38513591-8` · **lista 2** · **inactivo** · **+5491164426278** | **La misma persona en dos listas.** La fila con el móvil y la lista 2 está **dada de baja**; la que está activa y en lista 1 no tiene teléfono → si se manda la lista 1, ese cliente **no recibe nada**, y si se manda la lista 2, es un cliente inactivo. |
| **MIRANDA ZURITA EPIFANIO** | id 95 · cuit `27924639240` · lista 1 · `01154268595` · del legacy | id 868 · cuit `27 - 92463924 - 0` · lista 1 · `011 2374 1520` | Mismo cliente, dos teléfonos distintos. |
| **PRINWEY ALIMENTOS S.A. / PANYMAX S.A.** | id 124 · cuit `30693299930` · lista 1 · del legacy | id 864 · cuit `30-69329993-0` · lista 1 | **Mismo CUIT y misma dirección** (AVELLANEDA / 25 DE MAYO 530) → es el mismo cliente con el nombre cambiado. |

Los otros nombres que salen duplicados (BAREIRO, GUIZZETTI, MUSLI, BUENOS ALIMENTOS, CODIGO
ANIMALS) **no están duplicados dentro de la base**: son los "gemelos" que el Excel trae como fila
aparte (por eso la importación los reporta como *clientes que el archivo no menciona*).

**Consecuencia para la importación:** el importador **no puede decidir solo**. Cuando un CUIT
normalizado matchea más de un cliente en la base, la regla es:

- mismo **nombre normalizado** y **misma lista** en la base → es el mismo cliente: se actualizan
  todas sus filas y se reporta "duplicado unificado" (caso MIRANDA);
- mismo **nombre normalizado** pero **listas distintas** en la base → **no se aplica**: se reporta
  *"duplicado con listas distintas"* y hay que **unificar las dos filas primero** (caso GIMENEZ);
- **nombres distintos** con el mismo CUIT → **no se aplica**: se reporta *"posible mismo cliente
  con otro nombre"* (caso PRINWEY/PANYMAX).

Esto no es un detalle de la importación: es un **bug de datos que ya está afectando los precios**
(el mismo cliente en dos listas depende de qué fila tome una orden). Lo razonable es tratarlo como
un issue propio de datos (#753 y compañía), **antes** de la campaña de envío, porque si no la
campaña sale con el criterio de "última fila gana" y mete precios donde no van.

### 5.5.2 Comparación campo por campo contra la base real (resultado medido)

La comparación **medida con el importador contra la base real** (vista previa, sin escribir, con
`docs/clientes_20261021.xlsx` contra el dump del 20/10):

| Resultado | Filas | Qué significa |
|---|---|---|
| Filas leídas | 901 | una por cliente del Excel |
| **Sin cambio** | **871** | La base ya tiene la lista y el teléfono del Excel |
| **Lista a cambiar** | **0** | **No se toca un solo precio**: los 6 casos de lista distinta quedan bloqueados por el conflicto de duplicado |
| **Teléfono a completar** | **8** | Dato nuevo que hay que traer (la base los tiene vacíos) |
| Conflicto: mismo CUIT con listas distintas en el archivo | 6 clientes (12 filas) | BAREIRO, BUENOS ALIMENTOS, CODIGO ANIMAL, GIMENEZ, GUIZZETTI, MUSLI → **esperan a que Gabriela limpie el Excel** |
| Conflicto: CUIT duplicado en la base | 2 | MIRANDA (mismo nombre y misma lista → se unifican y se avisa) y PRINWEY/PANYMAX (nombres distintos → no se aplica) |
| No encontrado (por CUIT / sin CUIT) | 4 / 4 | Clientes que están en el Excel y no en el dump |
| Diferencias informadas (no se aplican) | 4 | 1 teléfono (MIRANDA) y 3 condiciones de IVA |
| Clientes que el archivo no menciona | 9 | Los "gemelos" de la base: no se tocan |

**Los 8 teléfonos que hay que completar** (la base los tiene vacíos):

| Cliente | Teléfono del Excel | Cómo se matcheó | Tipo |
|---|---|---|---|
| ASOCIACION ADVENTISTA SEPTIMO DIA | `03754411029` | CUIT | posible (La Pampa) |
| CARDOZO MAURICIO GUSTAVO | `379 466 9427` | CUIT | posible (Corrientes) |
| DAAL ALIMENTARIA SRL | `0341 431-3436` | CUIT | posible (Rosario) |
| DON ALBERTO SRL | `3758 650849` | CUIT | posible (Posadas) |
| ESTEVEZ CRISTIAN ADRIAN | `299 580 7634` | CUIT | posible (Neuquén) |
| MENDEZ OSVALDO MIGUEL | `011 34070557` | CUIT | posible (CABA) |
| SAN PATRICIO Y CIA S.A | `011-3553-0131` | CUIT | posible (CABA) |
| CAREL HUE | `01133521144` | **nombre** (CUIT `23456789` no sirve) | posible (CABA) |

Los 8 son **"posibles"**, no celulares: tienen el código de área + número **sin el "15"** de los
celulares, así que **no amplían la audiencia de WhatsApp**: sirven para llamar, no para mandar
lista. Y como Gabriela dijo por audio *"me fijé que todos tengan el teléfono... la verdad que no
llegué a actualizar eso"*, esto es exactamente el trabajo a medias que quedó en el Excel y no
llegó a la base.

**Lo bueno:** con el archivo de hoy la importación **no toca un solo precio** (los 6 casos de
lista distinta quedan bloqueados por el conflicto de duplicados). Es el caso de prueba ideal: se
prueba el circuito completo sin riesgo.
**Lo que falta:** resolver los 6 conflictos del Excel y los 3 grupos de duplicados de la base
antes de que Gabriela pase la lista nueva.

### 5.6 Cómo se aplica (seguro y reversible)

- **Respaldo automático antes de aplicar:** se exporta el estado actual (CUIT, nombre, lista,
  teléfono) a un archivo `respaldo_listas_AAAAMMDD-HHMM.xlsx` en la carpeta de salida. Con ese
  archivo, cualquier cambio se revierte en un click. Es barato y es la red de seguridad de un cambio
  que **afecta precios** (`pricing.py` usa `client.lista_precios`).
- **Una sola transacción:** o se aplican todos los cambios, o no se aplica ninguno. Con 901 filas
  se hace por lotes dentro de la misma transacción.
- **Auditoría:** cada cambio se registra con `AuditService` (como ya hace `ClientService`,
  `app/services/client_service.py:51`): módulo "Clientes", acción "actualizar_lista_precios" o
  "completar_telefono", con el valor anterior y el nuevo, y el usuario que lo hizo.
- **Idempotente:** reimportar el mismo archivo da **0 cambios**. Se puede repetir sin miedo.
- **Informe final:** pantalla con el resumen (aplicados, sin cambio, conflictos, no encontrados,
  inválidos) y exportación a CSV con el detalle.
- **Camino CLI:** `scripts/import_client_price_lists.py` con el mismo servicio, para correrlo
  desde la terminal del cliente (o desde el despliegue) sin depender de la UI.

### 5.7 Dónde vive la pantalla

Botón **"Importar lista de precios desde Excel"** en la grilla de Clientes, **junto al botón
"Exportar clientes a Excel"** que ya existe (`app/ui/master_abm.py:2138`). El round-trip queda
visible: exportar → editar la columna `Lista` → importar.

La importación **no** depende de la pantalla de envío: se puede importar la lista y mandar la
campaña de hoy, o importarla y dejar el envío para mañana.

---

## 6. Fuera de alcance (con motivo)

| Fuera | Por qué |
|---|---|
| Envío masivo por **email** | El maestro tiene **0 emails** en 901 clientes. Sin datos, el canal no existe. Queda como issue propio si algún día se cargan. |
| **Generar** el PDF de la lista desde el sistema | Hoy el PDF lo arma Gabriela. El sistema tiene `Product.precio_lista_1..4` (`app/models/masters.py:177`) y puede generarlo, pero es un desarrollo aparte con decisiones de layout (Fase D). |
| Issue **#706** (presupuestos automáticos) | Es otro pedido. Sí conviene **reusar este motor de cola** cuando se implemente. |
| Opt-out / lista de exclusión por cliente | Fase C. En Fase B la exclusión es manual (checkbox en la tabla previa). |
| Cambios en remitos, F150, DBF/MySQL, liquidaciones | Áreas protegidas del `AGENTS.md`. |
| Cambios en `Client` (columna nueva de consentimiento, CUIT normalizado) | Área protegida (modelos/migraciones). El CUIT normalizado se resuelve **en memoria** en el importador. |
| Importar **otros** campos del Excel (teléfono, email, nombre) | Fuera del pedido: "solo eso debe modificar". Si alguna vez se quiere, es otro issue con su propia revisión. |

---

## 7. Etapas

### Fase 0 — Este documento
Spec, auditoría, hallazgos y decisiones. **Cerrada con la aprobación de Oscar (22/10).**

### Fase A — Importar la lista (bloqueante)
Sin esto no hay nada que mandar: la lista que Gabriela preparó tiene que estar en la base.

1. `ClientePriceListImporter`: lee el `.xlsx`, matchea por CUIT normalizado (con fallback por
   nombre), y produce el **informe de vista previa** sin escribir nada.
2. Aplicación transaccional de **`lista_precios`** y **completado de `phone` cuando está vacío**,
   con auditoría y respaldo previo. Ningún otro campo se escribe.
3. Pantalla en la grilla de Clientes + script CLI.
4. Tests: match por CUIT con separadores, conflicto de CUIT duplicado, CUIT ambiguo, match por
   nombre, lista inválida, idempotencia, **teléfono que completa / que no pisa / que no borra**, y
   **garantía de que ningún otro campo cambia**.

### Fase B — Envío del PDF por lista (bloqueante para Gabriela)
1. `clasificar_telefono()` + `es_celular()` estricto, con tests. *(cierra el bug de los fijos)*
2. PDF y mensaje por lista, guardados en `AppParameter`.
3. `PriceListSendWorker`: cola secuencial con intervalo, jitter, lote inicial, tope de 100/día,
   pausa/cancelar, circuit breaker y reintentos.
4. Pantalla "Envío de lista de precios" con los 4 pasos de la §4.2.

**Criterio de salida:** Gabriela importa el Excel, elige la lista 1, ve el preview con los
contadores, y envía 3-5 mensajes de prueba a su propio número con intervalo de 10 s sin que la
interfaz se congele.

### Fase C — Para cuando la campaña sea real
- Reanudar una campaña después de cerrar la app.
- Reintento de fallidos desde la tabla.
- Export CSV del log y de los omitidos (con motivo).
- Ventana horaria.
- Reporte "clientes de la lista sin WhatsApp" para que Gabriela complete los teléfonos
  (convierte el hueco de datos en una tarea cerrable).

### Fase D — Que el sistema arme el PDF
Generar la lista de precios desde `Product.precio_lista_N` con el layout que defina Gabriela
(cantidad de productos, columnas, paginado) y eliminar el paso manual de armar el PDF.

---

## 8. Criterios de aceptación

### Fase A — Importación

- [ ] Se puede elegir un `.xlsx` y ver **la vista previa** antes de tocar la base.
- [ ] La vista previa separa: a cambiar, sin cambio, con conflicto, no encontrado, lista inválida
      y faltantes.
- [ ] Al aplicar, **solo** cambia `lista_precios` y, si estaba vacío, `phone`: nombre, CUIT, email,
      contacto, vendedor, plazo y activo quedan intactos (verificado campo por campo en el test).
- [ ] Un teléfono que **ya está** en la base no se pisa ni se borra, aunque el archivo traiga otro
      (y la diferencia queda reportada).
- [ ] Un cliente **sin teléfono** en la base y **con teléfono** en el archivo lo recibe
      (con los 7 casos reales del §5.5.2 como ejemplo).
- [ ] Si el archivo trae el teléfono vacío, el de la base se conserva (nunca se borra un teléfono).
- [ ] El match es por CUIT normalizado (funciona con `20- 29646152-1` contra `20296461521`).
- [ ] Las filas sin CUIT real matchean por nombre normalizado, y solo si dan un único cliente.
- [ ] Un CUIT repetido con listas distintas **no** se aplica: queda reportado como conflicto.
- [ ] Un CUIT que corresponde a varios clientes de la base **no** se aplica: queda reportado.
- [ ] No se crea ningún cliente que no exista en la base.
- [ ] Los clientes que no están en el archivo quedan como estaban.
- [ ] La lista se valida contra 1..4.
- [ ] Se guarda un **respaldo** del estado anterior antes de aplicar.
- [ ] Reimportar el mismo archivo produce **0 cambios**.
- [ ] Cada cambio queda auditado con valor anterior, valor nuevo y usuario.

### Fase B — Envío

- [ ] Al elegir una lista aparecen **su** PDF y **su** mensaje; sin PDF asignado no se puede enviar.
- [ ] La pantalla **calcula** la audiencia contra la base real y muestra: clientes de la lista,
      sin teléfono, fijos/inválidos, **celulares válidos**, ya enviados hoy y excluidos a mano.
- [ ] Solo se envían a celulares: un fijo o un texto con letras queda **omitido con motivo**.
- [ ] Se exige confirmación explícita con la cantidad exacta de mensajes a enviar.
- [ ] El envío respeta el intervalo configurado (verificable por timestamps en el log), con jitter.
- [ ] **La UI no se congela** durante el lote: se puede navegar a otra pantalla y seguir operando.
- [ ] Se puede **pausar** y **reanudar**; **cancelar** detiene en el siguiente punto seguro.
- [ ] Al completar el lote inicial, el envío se detiene y espera la confirmación de seguir.
- [ ] **No se pasan de 100 mensajes por día y por instancia**: al llegar al tope, la campaña para.
- [ ] Cada envío queda en `whatsapp_envios` con `tipo_documento=lista_precios`, `instance_id` de la
      usuaria, estado y `messageId`.
- [ ] Reanudar una campaña **no vuelve a enviar** a quien ya tiene estado terminal.
- [ ] Los fallidos quedan con motivo y se pueden reintentar.
- [ ] Un error de rate-limit/ban del gateway **detiene** la campaña y avisa.
- [ ] La pantalla se ve completa y sin solapamientos en **1366×768** y **1638×969**.

---

## 9. Validaciones

Según `VALIDATION.md`:

```bash
git diff --check
$env:QT_QPA_PLATFORM="offscreen"; python -m pytest
python -m compileall app webapp
python -m app.main --smoke
```

**Tests nuevos — importación (con base de prueba, sin gateway):**

- `test_import_solo_lista_y_telefono`: se importan filas con nombre/teléfono distintos y se
  verifica que **ningún otro campo** del cliente cambió.
- `test_telefono_completa_solo_si_esta_vacio`: base vacía + archivo con teléfono → se completa;
  base con teléfono + archivo con otro → **no se pisa** y se reporta; archivo sin teléfono → el de
  la base se conserva.
- `test_match_cuit_con_separadores`: `20- 29646152-1` en el archivo matchea `20296461521` en la base.
- `test_match_por_nombre_sin_cuit`: matchea por nombre normalizado (con acentos y espacios).
- `test_conflicto_cuit_duplicado`: mismo CUIT con listas distintas → no se aplica, se reporta.
- `test_cuit_ambiguo_en_la_base`: dos clientes con el mismo CUIT normalizado → no se aplica.
- `test_lista_invalida`: valor fuera de 1..4 → la fila se ignora con motivo.
- `test_no_crea_clientes`: una fila sin match no crea nada en la base.
- `test_clientes_faltantes_no_se_tocan`: los que no están en el archivo conservan su lista.
- `test_import_es_idempotente`: importar dos veces → la segunda da 0 cambios.
- `test_respaldo_generado`: antes de aplicar se escribe el respaldo.
- `test_auditoria`: cada cambio queda en el log de auditoría con anterior/nuevo/usuario.

**Tests nuevos — envío (con cliente falso, sin gateway real):**

- `test_clasificar_telefono`: móvil con 15, móvil con +549, móvil sin separadores, fijo 011, fijo
  03752, texto basura, dos teléfonos en un campo, vacío → estado y motivo de cada uno.
- `test_audiencia_por_lista`: solo clientes de la lista N, solo activos, excluye fijos y basura.
- `test_throttling`: con reloj falso, la diferencia entre dos envíos consecutivos es ≥ intervalo.
- `test_lote_inicial`: se detiene en el tamaño del lote y espera la confirmación.
- `test_tope_diario`: con 100 envíos del día ya registrados, la campaña no manda el 101.
- `test_pausa_y_cancelacion`: no se envían más mensajes después de pausar/cancelar.
- `test_idempotencia`: relanzar la misma clave de campaña no reenvía a los terminales.
- `test_circuit_breaker`: un 429 deja el resto en cola y no reintenta.
- `test_auditoria_whatsapp`: se crea la fila en `whatsapp_envios` con los datos esperados.
- Test de UI (offscreen): la pantalla calcula los contadores y el botón se habilita recién con
  confirmación.

**Validación contra la base real (obligatoria antes de tocar el puesto del cliente):**

La importación cambia precios, así que **no se aplica en la base del cliente sin correr antes contra
la base real restaurada del dump**, como se hizo en #746/#747:

1. Restaurar el dump del cliente en una base MySQL/MariaDB de prueba.
2. Correr la importación con el `docs/clientes_20261021.xlsx`.
3. Verificar: conteos de cambios, que ningún otro campo cambió, y que la lista de precios de un
   cliente de prueba queda con el valor esperado.
4. Probar la campaña con 3-5 destinatarios (intervalo 10 s, modo prueba) sobre la instancia de
   prueba.

> **Entorno de testeo (armado el 22/10, funcionando):** el dump `C:\Users\Usuario\Downloads\femag_desktop.sql`
> (MySQL 5.7 del cliente, export de HeidiSQL del 20/10) quedó importado en MariaDB de WSL:
>
> ```bash
> # 1. Levantar MariaDB (instancia propia, puerto 3308, no toca la base legacy 'an')
> nohup mysqld --defaults-file=/home/oscar/mysql_an/my.cnf --user=oscar &
> # 2. Importar el dump (el dump crea la base femag_desktop)
> mysql --socket=/home/oscar/mysql_an/run/mysql.sock -u root \
>   < /mnt/c/Users/Usuario/Downloads/femag_desktop.sql
> # 3. Usuario para la app
> CREATE USER 'femag'@'%' IDENTIFIED BY 'femag';
> GRANT ALL PRIVILEGES ON femag_desktop.* TO 'femag'@'%';
> ```
>
> Y desde Windows, la app se conecta con:
>
> ```powershell
> $env:FEMAG_SECURE_CONFIG='0'; $env:FEMAG_DEMO='0'; $env:FEMAG_DB_ENGINE='mysql'
> $env:DB_HOST='127.0.0.1'; $env:DB_PORT='3308'; $env:DB_NAME='femag_desktop'
> $env:DB_USER='femag';    $env:DB_PASSWORD='femag'
> python -m app.main --smoke      # -> FEMAG smoke OK (verificado)
> ```
>
> **Al terminar los tests, restaurar la base con el dump limpio** (o borrar la base `femag_desktop`
> y reimportar), para no dejar datos de prueba mezclados con los del cliente.
>
> Nota: la instancia `mysql_test` (puerto 3307) quedó con el datadir en **formato MySQL 8** y
> MariaDB 11.8 no la abre (`Unknown/unsupported storage engine: InnoDB`). La base `an` que sí
> levanta es el **legacy Django**, no la base de FEMAG Desktop: no confundir una con otra.

**No probar un envío masivo real sin autorización expresa** (riesgo de bloqueo de la línea).

---

## 10. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| La importación cambia el **precio de venta** de un cliente | Alto | Solo `lista_precios`, dry-run obligatorio, respaldo previo, transacción, auditoría |
| Matcheo equivocado (un cliente recibe la lista de otro) | Alto | CUIT normalizado + fallback por nombre solo si es único + conflictos no se aplican |
| Bloqueo de la instancia de Gabriela | Alto | Intervalo + jitter + tope 100/día + circuit breaker + lote inicial + confirmación |
| Mandar a un número equivocado (fijo convertido en móvil) | Alto | Filtro estricto de celular (§4.5) + preview con el número exacto que se va a mandar |
| Enviar el PDF de la lista equivocada | Bajo | El PDF está asociado a la lista y se muestra junto a ella antes de confirmar |
| Que el cliente haya cambiado de lista a mitad de campaña | Bajo | La audiencia se recalcula al inicio; la clave de campaña fija qué se envió |
| Colgar la base desde el hilo | Bajo | peewee abre conexión por hilo; `FemagMySQLDatabase` reconecta sola; el worker solo escribe estados |
| Que la app se cierre a mitad de envío | Medio | Los enviados quedan auditados; la campaña se reanuda desde la clave (Fase C trae el botón) |
| Volver a enviar a los mismos clientes en la próxima lista | Bajo | Idempotencia por clave de campaña + histórico visible |

---

## 11. Bitácora

| Fecha | Qué pasó |
|---|---|
| 21/10 | Gabriela avisa que las listas quedaron corregidas (los mayoristas, lista 1). |
| 22/10 | Gabriela propone pasar una lista nueva y probar el envío; Oscar plantea "elegir un PDF + que el sistema tome la lista". Gabriela: "era por si eso estaba para probar". |
| 22/10 | Auditoría del repo: el pedido ya está representado en #705 (no se crea issue nuevo). Se detecta que el normalizador actual convierte fijos en móviles falsos y que solo 31 de 901 clientes tienen celular real. Se escribe el spec. |
| 22/10 | **Oscar decide:** el PDF va por lista; 100 mensajes por día; el mensaje puede cambiar; **el Excel se importa y solo modifica la lista**. Se agrega el §5 (importación) al spec y se reordena el plan: Fase A importación, Fase B envío. |
| 22/10 | **Base real restaurada:** se importa `Downloads/femag_desktop.sql` (dump MySQL 5.7 del cliente, 20/10) en MariaDB de WSL y se crea el usuario `femag` para que la app de Windows se conecte. `python -m app.main --smoke` → **FEMAG smoke OK** contra la base real. Entorno de testeo armado y reproducible (§9). |
| 22/10 | **Auditoría de datos sobre la base real:** 884 clientes (876 lista 1 / 8 lista 2), 31 con celular. Se detectan **3 grupos de clientes duplicados en la base** (GIMENEZ en dos listas, MIRANDA dos teléfonos, PRINWEY/PANYMAX mismo CUIT y dirección) y 8 filas del Excel que no existen en la base. |
| 22/10 | **Comparación campo por campo** del Excel contra la base real (881 clientes matcheados 1 a 1): la lista coincide en 876 y difiere en 6 (los duplicados, que quedan en conflicto); **el teléfono coincide en 869 y el Excel trae 8 teléfonos que la base no tiene**; nombre difiere en 2, condición de IVA en 3, email/contacto/estado en 0. → La importación pasa a aplicar **lista + completar teléfono**. |
| 22/10 | **Audio de Gabriela (17:45):** *"Modifiqué la lista, Oscar, y... los lo de los mayoristas... me fijé que todos tengan el teléfono. Y de algunos clientes, no de todos. La verdad que no llegué a actualizar eso, pero la lista que le corresponde a cada uno, sí."* Confirma que la lista está lista y que **el trabajo de teléfonos quedó a medias en el Excel**, sin llegar a la base. |
| 22/10 | **Base de testeo intacta:** se verificó que la base de WSL quedó igual que el dump (884 clientes, `updated_at` sin movimientos posteriores al 20/10, 56 tablas antes y después del smoke). El smoke de la app **no escribe datos**. |
| 22/10 | **Simulación de la importación contra la base real: 0 cambios** (877 sin cambio, 12 filas en conflicto, 4 CUIT ambiguos, 8 no encontrados). Con el archivo actual la importación es un no-op: el caso de prueba ideal para probar el circuito sin tocar precios. |
| 22/10 | Al intentar usar la copia `an_test` de WSL se detecta que su datadir quedó en formato MySQL 8 y MariaDB 11.8 no la abre (`Unknown/unsupported storage engine: InnoDB`): se restauró el dump de cero en la instancia `mysql_an` (puerto 3308). La base `an` que sí levanta es el **legacy Django**, no la de FEMAG Desktop. |
| 22/10 | **Fase A implementada** en la rama `feat/issue-705-importar-lista-precios` (worktree propia desde `main`): servicio `ClientPriceListImporter`, diálogo con vista previa, botón "Importar lista" en la grilla de Clientes, script `scripts/import_client_price_lists.py` y 19 tests. Validado contra una copia del dump real: **0 cambios de lista y 8 teléfonos completados**, con respaldo previo, 8 filas de auditoría y `updated_at` actualizado. Suite completa: **1872 passed, 3 skipped**. La base de testeo de WSL quedó intacta (205 con teléfono, 0 filas tocadas). |
| 22/10 | **Corrección de una cifra y hallazgo nuevo:** los móviles reales de la base son **14**, no 31 (el conteo anterior arrastraba el mismo error del normalizador). Y el normalizador de la app convierte **148 líneas fijas en "móviles"** (`549` + número local) → la clasificación del envío pasa a tres estados: `celular` (14, se mandan), `posible` (148, se muestran y los tilda el operador) y `fijo/inválido` (no se mandan). |
| 22/10 | **Clasificador dephones implementado** (`app/services/whatsapp_phone_classifier.py`, función pura `clasificar_telefono`): estados `celular` / `posible` / `invalido` / `vacio`, con los helpers `es_celular` y `numero_enviable`. **Edición fácil del teléfono**: `ClientService.set_phone` (acepta vacío, rechaza basura, audita) + diálogo `ClientPhoneEditDialog` con la clasificación en vivo + botón **"Teléfono"** en la grilla de Clientes. 19 tests nuevos. Suite completa con estos cambios: **1891 passed, 3 skipped**. |
| 22/10 | **Cifras finales medidas con el clasificador nuevo** contra la base real (882 clientes activos, 203 con teléfono): **26 celular** (25 lista 1, 1 lista 2), **142 posible**, **35 inválido**, **679 sin teléfono**. Antes se habían anotado 14/148: era un conteo a mano con otra regla. El clasificador nuevo además distingue el **formato internacional** (`+549...` = celular; `+54...` sin el 9 = posible) y el largo variable del suscriptor (Rosario: 6 dígitos, CABA: 8). Con el normalizador viejo de la app, **173** de los 203 teléfonos darían un número móvil que no es celular. |
| 22/10 | **Importación re-medida con el importador** (vista previa, sin escribir): 901 filas → **0 cambios de lista**, **8 teléfonos a completar** (7 matcheados por CUIT + CAREL HUE por nombre), 871 sin cambio, 8 conflictos (6 CUIT duplicados en el Excel, 1 unificado de MIRANDA, 1 ambiguo de PRINWEY/PANYMAX), 8 no encontrados, 4 diferencias informadas, 9 clientes que el archivo no menciona. |
| 22/10 | **Decisiones de Oscar:** (a) los 6 conflictos del Excel (mismo CUIT con listas 1 y 2) **no se aplican y se reportan** hasta que Gabriela limpie el archivo; (b) el bug del normalizador viejo (173 líneas fijas mandadas como móviles) **no entra en este PR**: queda en su propio issue **#759**, para no mezclar bugs con features. |
| 22/10 | **Bug encontrado y corregido en el diálogo del teléfono:** dos variables quedaban con el nombre mal escrito (`clificacion` en vez de `clasificacion`) y el `.pyc` viejo seguía enmascarando el arreglo (Python valida el bytecode por mtime + tamaño, y el `edit` preserva el mtime). Consecuencia práctica: **después de editar un archivo ya importado, hay que invalidar el `__pycache__`** o lo que se prueba no es lo que está en el código. |
