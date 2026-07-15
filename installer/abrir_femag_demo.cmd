@echo off
setlocal
set "DEMO_ROOT=%~dp0app"
set "DEMO_PYTHON=%DEMO_ROOT%\.venv\Scripts\pythonw.exe"

if not exist "%DEMO_PYTHON%" (
    echo FEMAG Desktop DEMO no esta preparado correctamente.
    echo Vuelva a ejecutar el instalador FEMAG_Desktop_DEMO_Setup.exe.
    pause
    exit /b 1
)

pushd "%DEMO_ROOT%"
start "FEMAG Desktop DEMO" "%DEMO_PYTHON%" -m app.main --demo-ui
popd
endlocal
