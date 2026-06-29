@echo off
REM ============================================================
REM FEMAG Desktop - Lanzador demo UI para cliente
REM ============================================================
REM Doble click desde Explorador de Windows. Este .bat delega
REM al script PowerShell que hace el flujo completo:
REM   1) Verifica/actualiza repo
REM   2) Crea/activa .venv
REM   3) pip install -r requirements.txt
REM   4) Inicializa SQLite demo
REM   5) Carga datos demo integrales
REM   6) Corre smoke check
REM   7) Abre la UI con --demo-ui
REM ============================================================

setlocal

REM Resolver el directorio del repo (donde esta este .bat)
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Pasar todos los argumentos del .bat al .ps1
set "PS_SCRIPT=%SCRIPT_DIR%\scripts\instalar_femag_demo.ps1"

if not exist "%PS_SCRIPT%" (
    echo [ERROR] No se encontro "%PS_SCRIPT%".
    echo Este .bat debe estar en la raiz del repo clonado.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  FEMAG Desktop - Demo UI
echo  Repo: %SCRIPT_DIR%
echo ============================================================
echo.

REM Politica de ejecucion: Bypass solo para este proceso (no toca el host)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" %*

set "EXITCODE=%ERRORLEVEL%"

echo.
if %EXITCODE% NEQ 0 (
    echo.
    echo [ERROR] El instalador fallo con codigo %EXITCODE%.
    echo Revisa los mensajes arriba. Si fue un problema de red o permisos,
    echo volve a ejecutar este .bat.
) else (
    echo.
    echo Demo finalizada correctamente.
)

echo.
pause
endlocal
