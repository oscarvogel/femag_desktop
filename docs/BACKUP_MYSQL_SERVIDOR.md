# Backup diario de MySQL en el servidor

Runbook del script que se despliega en el servidor de MySQL (por ejemplo en
`C:\resguardo`) y genera un `.sql` por base todos los dias.

Script: `scripts/backup_mysql_all_databases.ps1`
Issue de tracking: #15

---

## Que resuelve

En la planta el respaldo fallaba siempre con el mismo error:

```
No se encontro el script de dump: C:\resguardo\backup_mysql_databases.py
```

La causa era triple, y las tres tenian que estar arregladas para que el
respaldo sirviera:

1. **El script exigia un archivo hermano.** `backup_mysql_all_databases.ps1`
   buscaba `backup_mysql_databases.py` en la misma carpeta y abortaba si no lo
   encontraba. En el servidor solo se habia copiado el `.ps1`.
2. **El `.py` no era autonomous.** Eveno copiandolo, hacia
   `from app.config.secure_credentials import ...`, que exige el arbol `app/`
   del repositorio. En el servidor no hay checkout: el import fallaba con
   `ModuleNotFoundError: No module named 'app'`.
3. **El log era inutil.** El patron `try { & $Python @args 2>&1 } catch { ... }`
   con `$ErrorActionPreference = "Stop"` convierte la primera linea de stderr en
   excepcion terminante y descarta el resto: el traceback de Python quedaba
   registrado en una sola linea, sin forma de saber que habia pasado.

Ademas, `Start-Process -ArgumentList` con un array parte los caminos que tienen
espacios, y un dump fallido dejaba un `.sql` a medias que alguien podia
restaurar por error.

La version actual de este runbook cubre las tres.

---

## Que motor usa

El script **detecta solo** el motor de dump y no necesita que se le diga:

| Motor | Cuando se usa | Que necesita |
|---|---|---|
| `mysqldump` | esta instalado `mysqldump` y el cliente `mysql` | MySQL Client. No hace falta Python. |
| `python` | no esta instalado MySQL Client | Python con PyMySQL y `backup_mysql_databases.py` en la misma carpeta. |

Con `-DumpEngine` se puede forzar uno de los dos (`auto`, `mysqldump`, `python`).
Por defecto es `auto`.

La contrasena viaja siempre por `MYSQL_PWD` (motor nativo) o por variable de
entorno (motor Python). **Nunca** va en la linea de comandos: ahi queda
registrada en el administrador de tareas y en los logs del sistema.

---

## Instalacion en el servidor

### 1. Copiar el script

Copiar **el archivo**, no el texto pegado en un editor: el `.ps1` va con BOM
UTF-8 para que PowerShell 5.1 (Windows Server 2019) lo lea bien.

```powershell
mkdir C:\resguardo -Force
copy "\\ruta\al\repo\scripts\backup_mysql_all_databases.ps1" "C:\resguardo\"
```

Si el servidor **no** tiene MySQL Client instalado, copiar tambien:

```powershell
copy "\\ruta\al\repo\scripts\backup_mysql_databases.py" "C:\resguardo\"
```

Sin MySQL Client, el `.py` es imprescindible: es el exportador.

### 2. Completar la configuracion

En `C:\resguardo\backup_mysql_all_databases.ps1`, bloque `CONFIGURACION`:

```powershell
$MysqlHost = "127.0.0.1"
$MysqlPort = 3306
$MysqlUser = 'CAMBIAR_USUARIO'
$MysqlPassword = 'CAMBIAR_CLAVE'

# Carpeta donde queda un .sql por base (se sobrescribe siempre).
$BackupDir = "C:\FEMAG\backups\mysql"

# Bases a saltear ademas de las del sistema. Ejemplo: @("demo", "test")
$ExcludeDatabases = @()
```

La tarea diaria corre como `SYSTEM`, que **no** tiene la credencial DPAPI del
usuario de la app. Por eso la clave va aca y no en la credencial segura.

> El archivo queda con la clave en claro. Restringir el acceso a `C:\resguardo`
> y a la carpeta de backups:
>
> ```powershell
> icacls "C:\resguardo" /inheritance:r /grant "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F"
> ```

### 3. Probar una vez a mano

```powershell
cd C:\resguardo
.\backup_mysql_all_databases.ps1
```

Salida esperada:

```
[2026-11-03 11:33:56] Inicio dump MySQL en C:\FEMAG\backups\mysql
Motor de dump: mysqldump
OK femag_desktop -> C:\FEMAG\backups\mysql\femag_desktop.sql (3.97 MB)
Archivo C:\FEMAG\backups\mysql\femag_desktop.sql (3.97 MB)
[2026-11-03 11:34:02] Fin (exit=0)
```

La cabecera dice la ruta **absoluta** donde quedaron los respaldos. Si no
los ves donde los estas mirando, esa linea es la respuesta: el destino sale
del bloque `CONFIGURACION`, no de la carpeta del script.

Si el motor elegido no es el que se esperaba:

```powershell
.\backup_mysql_all_databases.ps1 -DumpEngine mysqldump
.\backup_mysql_all_databases.ps1 -DumpEngine python -PythonPath "C:\Python312\python.exe"
```

Para cambiar la carpeta de destino sin tocar el archivo, se pasa por parametro:

```powershell
.\backup_mysql_all_databases.ps1 -BackupDir "C:\resguardo\backups"
```

### 4. Registrar la tarea diaria

```powershell
.\backup_mysql_all_databases.ps1 -RegisterTask
```

Se crea la tarea `FEMAG - Dump MySQL diario`, todos los dias a las 12:00, como
`SYSTEM`. Para sacarla:

```powershell
.\backup_mysql_all_databases.ps1 -UnregisterTask
```

---

## Que genera

| Archivo | Contenido |
|---|---|
| `<BackupDir>\<base>.sql` | Un dump por base. Se reemplaza en cada ejecucion. |
| `<BackupDir>\manifest.json` | `created_at` y el resultado por base (`database`, `file_path`, `status`, `message`). |
| `<BackupDir>\backup.log` | Cabecera, resultado por base y pie con el codigo de salida. |

El `manifest.json` es el **registro del ultimo backup**: dice cuando se hizo y
que base salio bien y cual fallo.

El dump se publica por reemplazo atomico: se escribe a un temporal y se mueve.
Un dump fallido **no** deja un `.sql` a medias.

### Como saber si el ultimo respaldo sirve

El log termina con una linea por archivo publicado, con su ruta absoluta y su
tamano en disco:

```
[2026-11-03 11:33:56] Inicio dump MySQL en C:\FEMAG\backups\mysql
Motor de dump: mysqldump
OK femag_desktop -> C:\FEMAG\backups\mysql\femag_desktop.sql (3.97 MB)
Archivo C:\FEMAG\backups\mysql\femag_desktop.sql (3.97 MB)
[2026-11-03 11:34:02] Fin (exit=0)
```

Tres reglas para leerlo:

- **`exit=0` y lineas `Archivo`**: el respaldo esta ahi y tiene contenido.
- **`ERROR ... el dump salio vacio`**: la herramienta termino bien pero sin
  escribir nada. No se publica el archivo y el respaldo anterior queda
  intacto. Un `.sql` de 0 bytes no es un respaldo.
- **Sin lineas `Archivo`**: no hay nada. Fijate en la cabecera del log: dice
  la ruta **absoluta** donde se estuvo buscando.

La carpeta de destino se resuelve a una ruta absoluta antes de usarla. Si es
relativa, se resuelve contra la carpeta del script, no contra el directorio
desde el que se lanza: asi el respaldo queda siempre en el mismo lugar, se
llame como se llame.

---

## Verificar que el respaldo sirve

Un `.sql` que no se puede restaurar no es un respaldo. La restauracion se
prueba contra una base desechable, nunca contra la base de la app:

```powershell
# 1. Crear la base de prueba
mysql -u <usuario> -p -e "CREATE DATABASE femag_754_check"

# 2. Importar el dump (el dump trae su propio CREATE DATABASE y USE)
mysql -u <usuario> -p femag_754_check < "C:\FEMAG\backups\mysql\femag_desktop.sql"

# 3. Comparar
mysql -u <usuario> -p -e "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='femag_754_check'"

# 4. Limpiar
mysql -u <usuario> -p -e "DROP DATABASE femag_754_check"
```

---

## Rollback

El script no toca la base: solo escribe archivos. Para volver atras:

```powershell
# 1. Sacar la tarea
.\backup_mysql_all_databases.ps1 -UnregisterTask

# 2. Borrar el script
del "C:\resguardo\backup_mysql_all_databases.ps1"
```

Los `.sql` y el `manifest.json` se pueden borrar o archivar: son los backups.

---

## Bitacora de la reparacion

Validaciones ejecutadas contra el MariaDB real (11.8.6) de la etapa de
desarrollo, usuario `femag` sobre `127.0.0.1:3306`:

| Validacion | Resultado |
|---|---|
| Reparto del error en 3 niveles | 3 causas reproducidas de forma aislada |
| Dump con motor nativo (`mysqldump`) | 2 bases, `exit=0`, `.sql` de 3,7 MB y 4,0 MB |
| Dump con motor Python (PyMySQL) | 2 bases, `exit=0`, `.sql` de 4,9 MB y 5,2 MB |
| Restauracion del dump nativo en base desechable | 63 tablas y 21.009 filas, identicas al origen |
| Restauracion del dump Python en base desechable | 63 tablas y 21.009 filas, identicas al origen |
| Base de la app despues de restaurar | Sin cambios |
| Pruebas focalizadas (`tests/test_backup_mysql_all_databases.py`) | 14 passed |
| Pruebas del exportador (`tests/test_backup_mysql_databases.py`) | 6 passed |
| Suite completa del repo | 2257 passed, 3 skipped |
| Parser de PowerShell 5.1 sobre el `.ps1` | Sin errores |

Errores encontrados durante la validacion, y como se resolvieron:

- **El primer verificador de restauracion dio falso negativo** (57 tablas
  "faltantes"): el verificador reescribia el SQL en memoria pero importaba el
  archivo original, y el `USE femag_desktop` del dump mandaba la importacion a
  la base de la app. El dump estaba bien; el verificador no. Se corrigio
  importando el archivo ya reescrito y comparando el estado de la base de la app
  antes y despues.
- **El primer dump nativo salio con `Access denied`**: el motor nativo no
  estaba recibiendo `MYSQL_PWD`. Corregido en `Invoke-NativeDump`.
- **La carga del exportador como modulo fallaba** con
  `AttributeError: 'NoneType' object has no attribute '__dict__'`: el decorador
  `@dataclass` busca el modulo en `sys.modules`. No es un defecto de
  despliegue (en el servidor corre como script, con `__main__` en
  `sys.modules`), pero el test quedo exercising la forma real de ejecucion.
- **El resumen de archivos salia como `Archivo femag_desktop.sql.FullName`**:
  en PowerShell `"$objeto.Propiedad"` no interpola la propiedad, hay que
  escribir `"$($objeto.Propiedad)"`. Solo se ve al ejecutarlo de verdad.

### Segunda ronda: "dice que hizo pero nunca hizo"

En la planta se reporto que el script anunciaba el respaldo pero los archivos no
aparecian. Las causas que seinvestigaron y quedaron corregidas:

- **La carpeta de destino podia ser relativa.** Con una ruta relativa, los
  respaldos caian segun el directorio desde el que se lanzaba el script: a
  mano, desde otra carpeta o desde la tarea programada caian en lugares
  distintos. Ahora la ruta se resuelve a absoluta contra la carpeta del script
  y el log la muestra.
- **El script|reportaba OK sin verificar el archivo.** `mysqldump` puede
  terminar con codigo 0 sin haber escrito nada, y el script lo tomaba como
  exito: dejaba un `.sql` de 0 bytes con pinta de respaldo valido. Ahora se
  verifica el tamano antes de publicar; si el dump sale vacio se reporta ERROR,
  no se publica el archivo y el respaldo anterior queda intacto.
- **El log no dizia donde buscar.** Ahora cierra con una linea por archivo, con
  su ruta absoluta y su tamano en disco.

---

## Pendientes

Estos criterios del issue #15 **no** estan cubiertos por este script:

- Carpeta adicional configurable para copiar el respaldo a otra PC.
- Estado del ultimo backup visible desde el sistema (hoy esta en
  `manifest.json` y en `backup.log`, no en la pantalla).
- Registro en auditoria de los respaldos manuales.
