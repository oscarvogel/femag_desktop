# Deploy de FEMAG Desktop

## Objetivo

El instalador Windows conecta los puestos a MySQL sin incluir credenciales. En el primer inicio completa automaticamente:

- servidor: `almanet-server`;
- puerto: `3306`;
- base: `femag_desktop`.

El operador ingresa usuario y contrasena. El nombre del servidor se conserva y se resuelve a IPv4 en cada conexion, por lo que un cambio de IP administrado por DNS o la red no obliga a reconfigurar los puestos.

## Primera conexion y estructura

La contrasena MySQL se cifra con Windows DPAPI `CurrentUser` y se guarda fuera de la carpeta instalada, en `%LOCALAPPDATA%\FEMAG Desktop`. No se escribe en el instalador, JSON, argumentos ni logs.

Si la base esta vacia o incompleta, el asistente informa las tablas faltantes y ofrece `Crear o actualizar ahora las tablas de FEMAG`. La accion:

1. requiere confirmacion explicita;
2. usa la credencial administrativa ingresada;
3. ejecuta la preparacion de esquema una sola vez;
4. valida el esquema terminado antes de guardar la conexion.

Los arranques normales siguen siendo read-only respecto del esquema: no crean ni alteran tablas automaticamente.

## Version de cada build

Cada compilacion obtiene una version irrepetible con el formato:

```text
AAAA.MM.DD.HH.MM.SS
```

Ejemplo: `2026.08.06.14.32.09`.

El script actualiza `app/build_version.py` antes de ejecutar PyInstaller. La misma version se usa en la ventana de FEMAG y en `AppVersion` de Inno Setup.

El instalador mantiene siempre un unico nombre estable. Antes de compilar, el script elimina los instaladores productivos anteriores del directorio de salida y genera uno nuevo:

```text
FEMAG_Desktop_Produccion_Setup.exe
```

La identificacion de la compilacion se obtiene desde la version interna del sistema, no desde el nombre del instalador.

## Compilacion

Desde la raiz del repositorio, en Windows con Inno Setup 6:

```powershell
.\scripts\build_production_installer.ps1 -SkipInstallDependencies
```

Para indicar otro Python:

```powershell
.\scripts\build_production_installer.ps1 -SkipInstallDependencies -PythonPath C:\ruta\.venv\Scripts\python.exe
```

El resultado queda en `installer\output\`. PyInstaller genera el runtime standalone, por lo que el puesto no necesita Python, Git ni Internet.

## Validacion previa a entrega

```powershell
python -m pytest -q
python -m compileall -q app scripts
python -m app.main --smoke
git diff --check
```

Ademas se debe validar en una base descartable:

- resolucion de `almanet-server` por IPv4;
- conexion MySQL;
- creacion y validacion de tablas;
- guardado y recuperacion DPAPI;
- login funcional de FEMAG.

## Riesgos conocidos

- El instalador actual no tiene firma digital. Smart App Control puede bloquear tanto el instalador como el ejecutable temporal que Inno Setup extrae en `%TEMP%` con error 4551.
- El nombre y la version del build no causan ni resuelven ese bloqueo: cada binario nuevo sigue siendo codigo sin firma.
- Antes del despliegue deben firmarse el ejecutable interno, los binarios que genera Inno Setup y el instalador final con un certificado RSA de firma de codigo emitido por una entidad confiable para Windows.
- La PC de compilacion no tiene actualmente un certificado de firma de codigo con clave privada disponible.
- Las credenciales administrativas se usan solamente para preparar el esquema. Para operacion diaria se recomienda un usuario limitado a `SELECT`, `INSERT`, `UPDATE` y `DELETE`.
