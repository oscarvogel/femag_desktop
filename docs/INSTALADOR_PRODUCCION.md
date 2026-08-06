# Instalador de produccion para Windows

El instalador `FEMAG_Desktop_Produccion_Setup.exe` contiene la aplicacion y su runtime. El puesto no necesita Git, Python ni acceso a Internet.

## Primera apertura

La primera vez, FEMAG completa automaticamente `almanet-server`, puerto `3306` y base `femag_desktop`; el operador solamente ingresa usuario y contrasena MySQL. Antes de guardar prueba la conexion y valida que el esquema sea compatible. El puesto productivo no crea ni modifica tablas.

- Servidor, puerto, base y usuario se guardan en `%LOCALAPPDATA%\FEMAG Desktop\connection.json`.
- La contrasena se cifra con Windows DPAPI (alcance `CurrentUser`) y se guarda en `connection.credential`.
- La contrasena no se escribe en el JSON, el instalador, el registro, argumentos de linea de comandos ni logs.
- La credencial solamente puede descifrarla el mismo usuario de Windows en la misma computadora.

La configuracion queda fuera de la carpeta del programa. Por eso una actualizacion o desinstalacion no la elimina. Si cambia el usuario de Windows, se pierde el perfil o la credencial deja de ser valida, FEMAG vuelve a solicitar los datos.

El menu Inicio incluye `Configurar conexion FEMAG`, que abre nuevamente el asistente mediante `FEMAG Desktop.exe --configure`.

## Compilacion

En una PC Windows con Inno Setup 6:

```powershell
.\scripts\build_production_installer.ps1 -SkipInstallDependencies
```

El resultado se genera en `installer\output\FEMAG_Desktop_Produccion_Setup_v4.exe`.

La compilacion actual no tiene firma digital. Windows SmartScreen puede mostrar una advertencia y una politica corporativa de control de aplicaciones puede bloquearla por completo. Antes del despliegue general se debe firmar tanto el ejecutable como el instalador con un certificado de firma de codigo confiable. Para un piloto interno sin firma, el responsable de infraestructura debe autorizar explicitamente ambos binarios.
