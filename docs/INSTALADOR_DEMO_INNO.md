# Instalador FEMAG Desktop DEMO con Inno Setup

Este instalador es exclusivo para demostraciones comerciales. Se identifica como
`FEMAG Desktop DEMO`, usa SQLite local, abre la aplicacion con `--demo-ui` y se
instala por usuario en una carpeta separada de cualquier futura version productiva.

## Requisitos para compilar

- Windows 10 u 11.
- Inno Setup 6.
- Acceso al repositorio para que el bootstrap prepare la demo.

## Compilar

Desde la raiz del repositorio:

```powershell
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" installer\FEMAG_Desktop_Demo.iss
```

El resultado se genera en:

```text
installer\output\FEMAG_Desktop_DEMO_Setup.exe
```

Para validar una rama antes de mergearla:

```powershell
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" "/DSourceBranch=codex/issue-186-inno-demo-installer" installer\FEMAG_Desktop_Demo.iss
```

La compilacion normal usa `main`. El parametro de rama se reserva para validar
un PR y no debe usarse para una entrega final.

## Diferencias visibles respecto de produccion

- Producto: `FEMAG Desktop DEMO`.
- Instalador: `FEMAG_Desktop_DEMO_Setup.exe`.
- Carpeta: `%LOCALAPPDATA%\Programs\FEMAG Desktop DEMO`.
- Accesos directos: `FEMAG Desktop DEMO`.
- Base: SQLite local con datos sinteticos.
- Inicio: siempre `pythonw.exe -m app.main --demo-ui`.
- Desinstalacion independiente mediante Aplicaciones instaladas de Windows.

## Requisitos de la PC donde se instala

La preparacion inicial requiere Internet. El bootstrap verifica Git y Python
3.12, intenta instalarlos con `winget` si faltan, descarga el repositorio,
crea `.venv`, instala dependencias, genera la base demo y ejecuta el smoke.

El instalador no contiene credenciales ni datos productivos. La demo usa usuario
`demo` y clave `demo`.

## Limitaciones actuales

- El ejecutable no tiene firma digital.
- La primera instalacion requiere Internet.
- No es un paquete autonomo: Python y las dependencias se preparan en destino.
- La validacion final debe realizarse en una PC Windows limpia antes de entregarlo.
