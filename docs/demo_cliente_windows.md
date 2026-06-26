# Demo cliente Windows - FEMAG Desktop

Esta guia permite mostrar el avance funcional de Ordenes de carga en una PC Windows. Es una demo de avance, no el sistema productivo final.

## Requisitos

- Windows con PowerShell.
- Internet.
- Si el repositorio es privado, la PC necesita acceso/autenticacion a GitHub.
- Permisos para instalar Git y Python con `winget`, o tenerlos ya instalados.

## Como descargar el script

Opcion recomendada para la demo:

1. Descargar `scripts/instalar_femag_demo.ps1` desde GitHub.
2. Guardarlo, por ejemplo, en `Descargas`.
3. Abrir PowerShell.

Si el repositorio es privado, primero iniciar sesion o configurar acceso a GitHub en esa PC.

## Como ejecutarlo

Desde PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\instalar_femag_demo.ps1
```

Parametros utiles:

```powershell
.\instalar_femag_demo.ps1 -InstallRoot "$env:USERPROFILE\FEMAG"
.\instalar_femag_demo.ps1 -SkipUi
```

Por defecto usa la rama:

```text
codex/issue-73-load-order-integral-demo
```

## Que hace

1. Verifica Git.
2. Si falta Git, intenta instalarlo con `winget`.
3. Verifica Python.
4. Si falta Python, intenta instalar Python 3.12 con `winget`.
5. Clona `https://github.com/oscarvogel/femag_desktop.git`.
6. Entra en la rama de demo.
7. Crea `.venv`.
8. Instala `requirements.txt`.
9. Ejecuta `scripts/init_db.py` si existe.
10. Ejecuta `scripts/issue_73_integral_demo.py`.
11. Ejecuta `python -m app.main --smoke`.
12. Abre `python -m app.main --demo-ui`.

Si `scripts/init_db.py` no puede conectarse a una base MySQL operativa, el script informa la limitacion y continua la demo integral con SQLite local en `backups`.

## Que mostrar en la demo

- Pantalla principal FEMAG Desktop.
- Maestros minimos para Orden de carga.
- Orden de carga multi-cliente/multi-destino.
- Emision.
- Impresion Orden A4.
- Hoja resumen/sobre.
- Reimpresion como copia operativa.
- Anulacion.
- Evidencia documental generada en `docs\prints\issue_73_integral_demo`.

## Limitaciones conocidas

- Es una demo funcional, no una instalacion productiva final.
- No incluye remito fiscal, F150, AFIP/ARCA, facturacion, presupuesto definitivo ni rendicion completa.
- La cuenta corriente es documental con importe `ARS 0` hasta definir precios/listas comerciales.
- Si el repo es privado, GitHub puede pedir autenticacion.
- Si Git o Python se instalan durante la demo, puede ser necesario cerrar y abrir PowerShell para refrescar el `PATH`.
- En algunas PCs, la captura automatizada de PyQt/Windows puede fallar; en ese caso la validacion visual debe hacerse manualmente.
