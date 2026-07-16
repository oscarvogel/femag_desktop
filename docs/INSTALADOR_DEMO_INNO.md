# Instalador autonomo FEMAG Desktop DEMO

Este instalador es exclusivo para demostraciones comerciales. Instala la
aplicacion, Python y todas sus dependencias dentro del paquete generado. La PC
cliente no necesita Git, Python, winget, acceso a GitHub ni Internet.

## Compilar en la PC de desarrollo

Requisitos exclusivos de la PC que genera el instalador:

- Windows 10 u 11.
- Python 3.12 y el entorno `.venv` del proyecto.
- Inno Setup 6.
- Internet solamente para instalar dependencias de compilacion si faltan.

Desde la raiz del repositorio:

```powershell
.\scripts\build_demo_installer.ps1
```

Si las dependencias ya estan instaladas:

```powershell
.\scripts\build_demo_installer.ps1 -SkipInstallDependencies
```

El resultado se genera en:

```text
installer\output\FEMAG_Desktop_DEMO_Standalone_Setup.exe
```

El ejecutable, el instalador y sus accesos directos usan el icono compartido
`app/ui/assets/branding/femag.ico`. El futuro instalador productivo debe reutilizar
este mismo contrato de branding, sin duplicar ni redibujar la marca.

## Requisitos de la PC cliente

- Windows 10 u 11 de 64 bits.
- No requiere Git.
- No requiere Python.
- No requiere winget.
- No requiere Internet ni acceso a GitHub.
- No requiere permisos de administrador para la instalacion normal por usuario.

## Diferencias visibles respecto de produccion

- Producto: `FEMAG Desktop DEMO`.
- Instalador: `FEMAG_Desktop_DEMO_Standalone_Setup.exe`.
- Carpeta: `%LOCALAPPDATA%\Programs\FEMAG Desktop DEMO`.
- Accesos directos: `FEMAG Desktop DEMO`.
- Base: `data\femag_demo.sqlite3`, creada localmente con datos sinteticos.
- Inicio: el ejecutable embebido abre siempre el modo `--demo-ui`.
- Desinstalacion independiente mediante Aplicaciones instaladas de Windows.

La demo usa usuario `demo` y clave `demo`. El instalador no contiene
credenciales ni datos productivos.

## Validacion de humo del paquete

El ejecutable empaquetado admite `--smoke` para validacion tecnica:

```powershell
& ".\dist\FEMAG Desktop DEMO\FEMAG Desktop DEMO.exe" --smoke
```

El resultado esperado es `FEMAG smoke OK`.

## Limitaciones actuales

- El ejecutable no tiene firma digital y Windows puede mostrar SmartScreen.
- La validacion final debe realizarse en una PC Windows limpia antes de entregarlo.
