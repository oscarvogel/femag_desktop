# Bitácora: migración de esquema e importación DGR (2026-10-09)

Registro de una intervención sobre la base local `femag_desktop` de la rama
`fix/f150-ui-origen-y-seleccion`. Documenta qué se ejecutó, qué se encontró y qué
queda pendiente.

Issues relacionados: #404 (hilo padre), #685, #686.

---

## 1. Síntoma de partida

`py -m app.main --ui` no abría. Diálogo de la aplicación:

> El esquema de la base de datos no es compatible: Faltan tablas requeridas:
> dgrcountry, dgrprovince, f150batch, f150batchremittance. Un administrador debe
> ejecutar scripts/init_db.py antes de abrir los puestos.

Origen del mensaje: `app/ui/desktop_app.py:444`.

## 2. Causa raíz

No es un defecto de código. La rama de trabajo agrega tablas que **no están en
`main`**:

| Modelo | Commit | ¿En `origin/main`? |
|---|---|---|
| `app/models/dgr.py` | `008aa8b` | no |
| `app/models/f150.py` | `e6734aa` | no |

Verificado con `git merge-base --is-ancestor <commit> origin/main` (exit 1 en ambos
casos) y con `git diff --stat origin/main HEAD -- app/models/`.

La rama además agrega columnas nullable en `clientaddress`, `product`, `carrier`,
`truck` y `driver`.

Como la base local se había preparado con el esquema de `main`, le faltaban 5
tablas. Desde #660 la aplicación abre **read-only** contra el esquema: valida y se
niega a entrar en vez de migrar sola. Por eso el diálogo.

### Descartado durante el diagnóstico

- **No era el SQLite de demo.** `femag_demo.sqlite3` tiene las 54 tablas completas.
- **No faltaba configuración segura.** `has_runtime_configuration()` devuelve `True`;
  por eso la app va a MySQL aunque el `.env` del repo diga `sqlite`. Eso es
  intencional: `resolve_effective_connection_settings()` fuerza MySQL para que un
  `.env` demo no redirija el perfil por accidente.

La conexión efectiva: `127.0.0.1:3306/femag_desktop`, usuario `femag`, configurada
por DPAPI en `%LOCALAPPDATA%\FEMAG Desktop`.

## 3. Respaldo previo

Toda intervención sobre la base empieza con un dump:

```powershell
py scripts/backup_mysql_databases.py --database femag_desktop --dump-engine auto
```

```
OK femag_desktop: C:\Users\Usuario\AppData\Local\FEMAG Desktop\backups\mysql\20261009-132824\femag_desktop.sql
```

2.731.853 bytes. Es el punto de retorno de todo lo que sigue.

## 4. Preparación del esquema

```powershell
$env:FEMAG_SECURE_CONFIG='1'
$env:FEMAG_AUTO_MIGRATE_SCHEMA='0'
py scripts/init_db.py
# -> Base FEMAG preparada correctamente
```

Tablas: 51 → 56. `validate_runtime_schema` **OK** (tablas, columnas e índices).

> `FEMAG_SECURE_CONFIG=1` no es opcional acá. Ver el defecto del punto 7.

## 5. Importación de la referencia DGR

Fuentes: `C:\Programacion\dante\sistema\contable\data` (copia local del legacy;
en el issue #404 figura como `O:\dante\sistema\contable\data\`).

```powershell
py scripts/import_dgr_reference.py `
  --paises "...\paises.dbf" `
  --provincias "...\provincias.dbf" `
  --localidades "...\localidades.dbf" `
  --locdgr "...\locdgr.dbf"
```

Conteos contra lo que exige #404:

| Entidad | Esperado | Obtenido | |
|---|---|---|---|
| `paises` | 255 | 255 importados | coincide |
| `provincias` | 24 | 24 importados | coincide |
| `localidades` | 3976 | 3975 creadas + 1 actualizada = 3976 | coincide |

`errors: []` en las tres. **Este paso quedó completo y verificado.**

## 6. La reimportación de maestros no se pudo ejecutar

Con DGR cargada, el paso siguiente era reimportar los maestros para que
`_find_locality()` resolviera las localidades. Falla:

```
peewee.IntegrityError: (1062, "Duplicate entry '00000000000' for key 'client.client_cuit'")
```

Detalle completo y opciones en **#686**. Resumen:

- `Client.cuit` es `CharField(unique=True)` **sin `null=True`**
  (`app/models/masters.py:77`): el modelo no tiene forma de representar "cliente
  sin CUIT".
- `_clean_cuit()` solo quita no dígitos, así que `'  -        -0'` → `'0'` y
  `'00-00000000-0'` → `'00000000000'`. No distingue relleno de real.
- `_upsert()` usa `{"cuit": cuit}` como clave natural, de modo que **clientes
  legacy distintos se pisan entre sí** por compartir CUIT de relleno.

El CUIT `30-69329993-0` además aparece 2 veces con valor real, así que el problema
no se agota en los rellenos.

### Estado medido, no supuesto

El crash ocurre en la **primera** entidad, así que nada de las otras corrió. Los
enlaces a DGR siguen todos en cero:

| Enlace | Con valor | Total |
|---|---|---|
| `clientaddress.locality` | 0 | 872 |
| `driver.locality` | 0 | 143 |
| `carrier.locality` | 0 | 76 |
| `product.rh1` | 0 | 38 |
| `product.unidad_dgr` | 0 | 38 |
| `truck.chassis_type` | 0 | 104 |

La corrida abortada dejó además dos clientes con CUIT de relleno persistidos
(`CACERES RAMON` → `0`, `CAREL HUE` → `00000000000`) y un `importbatch` en
`status='running'` sin `finished_at`.

## 7. Defecto encontrado: el comando de preparación no hace nada

**El mensaje de error de la propia app manda a ejecutar un comando que, en un
checkout de desarrollo, no arregla nada y no avisa que no lo hizo.**

`scripts/init_db.py` llama a `initialize_runtime_database()` → `load_settings()`.
Eso solo lee la configuración segura (DPAPI) si `FEMAG_SECURE_CONFIG=1` está
seteado, y **el script nunca lo setea**. Después carga el `.env` del repo:

```
FEMAG_DB_ENGINE=sqlite
FEMAG_SQLITE_PATH=femag_demo.sqlite3
FEMAG_DEMO=1
```

Resultado: prepara `femag_demo.sqlite3`, imprime `Base FEMAG preparada
correctamente` y **nunca toca `femag_desktop`**.

Medido en este repo:

| Invocación | Base resuelta |
|---|---|
| `py scripts/init_db.py` | `engine=sqlite`, `demo=True` |
| `$env:FEMAG_SECURE_CONFIG='1'; py scripts/init_db.py` | `engine=mysql`, `127.0.0.1:3306/femag_desktop` |

En producción el EXE está congelado y no hay `.env`, así que el comando funciona.
El defecto aparece en desarrollo, que es donde se diagnostica.

Mismo camino en `scripts/import_dgr_reference.py:37` y en cualquier script que
use `initialize_runtime_database()` sin fijar la conexión.

Registrado en **#685**.

## 8. Validaciones ejecutadas

| Comprobación | Comando | Resultado |
|---|---|---|
| Esquema completo | `validate_runtime_schema()` | OK |
| Smoke sin UI | `py -m app.main --smoke` | `FEMAG smoke OK` |
| Arranque real | `py -m app.main --ui` (offscreen, 25 s) | sigue vivo, pasó la validación |
| Conteos DGR | `import_dgr_reference.py` | coinciden con #404 |
| Enlaces a DGR | consulta directa a MySQL | todos en cero (bloqueo de #686) |

**No validado:** la pantalla F150 en sí, y la UI sobre plataforma real. La
corrida offscreen no renderiza fuentes (limitación conocida, #652).

## 9. Roles de los DBF

Confirmado leyendo `app/importers/legacy_dbf.py`:

- **Los camiones no tienen DBF propio.** Salen de `chofer.dbf` (`CHASIS`,
  `ACOPLADO`, `TIPOPATE`, `TIPOPATEAC`) vía `_upsert_habitual_truck`. Por eso el
  comando **no** lleva `--trucks`.
- Mapeo que funciona:

```powershell
py scripts/import_legacy_dbf_masters.py `
  --clients "...\clientes.dbf" `
  --carriers "...\transporte.dbf" `
  --drivers "...\chofer.dbf" `
  --products "...\productos.dbf"
```

## 10. Pendientes

1. **#686 — identidad del cliente sin CUIT.** Requiere Define antes de tocar
   `Client.cuit`: es área protegida (modelo y estructura de base).
2. **Reejecutar la importación de maestros** una vez resuelto #686, y volver a
   medir los enlaces de la tabla del punto 6 hasta que dejen de estar en cero.
3. **Cerrar el `importbatch` colgado** en `status='running'` y los dos clientes con
   CUIT de relleno, según se decida la recuperación.
4. **#685** — el destino de los scripts de administración.
5. Recién con 1 y 2 resueltos, `f150_batch_service.py` puede dejar los `""`
   hardcodeados de las líneas 163-211, que es el objetivo de #404.