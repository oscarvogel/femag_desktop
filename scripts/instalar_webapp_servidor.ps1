# Instala y deja andando el servidor de la webapp en el Windows Server 2019.
#
# Esto lo llama el instalador (installer\FEMAG_Webapp_Server.iss) con los
# datos que el administrador escribe en el asistente. Tambien se puede
# correr a mano, que es lo que se usa para probar sin instalar:
#
#   .\scripts\instalar_webapp_servidor.ps1 -DbUser femag_webapp -DbPassword "..."
#
# Que deja:
#   - C:\ProgramData\FEMAG\webapp.env         configuracion protegida
#   - C:\ProgramData\FEMAG\webapp_secret.key   secreto de sesion
#   - C:\ProgramData\FEMAG\logs\instalar_servidor.log  que hizo la instalacion
#   - C:\FEMAG\webapp\run_webapp.cmd           lanzador del servicio
#   - tarea programada "FEMAG Webapp QR"       arranca con la maquina
#   - regla de firewall para el puerto del backend
#
# Es el camino de instalacion del ejecutable empaquetado: el servidor no
# necesita Python, pip ni Git en la maquina.
#
# Opciones:
#   -ParamsFile <archivo>   Los datos vienen de un archivo en vez de la linea
#                           de comandos: la clave de MySQL queda expuesta en la
#                           lista de procesos si va en los argumentos.
#   -SkipServiceSetup       Escribe la configuracion y el lanzador, pero no
#                           registra la tarea ni abre el firewall. Sirve para
#                           preparar la maquina y arrancar el servidor a mano.
#   -DbEngine sqlite        La fabrica usa MySQL. Este valor existe para
#                           probar la instalacion donde no hay MySQL.
#   -ForceConfig            Vuelve a escribir la configuracion aunque ya
#                           exista (por defecto se conserva).

[CmdletBinding()]
param(
    [string]$InstallRoot = "C:\FEMAG\webapp",
    [string]$ConfigPath = "C:\ProgramData\FEMAG\webapp.env",
    [string]$PublicHostName = "femag.lan",
    [string]$DbHost = "127.0.0.1",
    [int]$DbPort = 3306,
    [string]$DbName = "femag_desktop",
    [string]$DbUser = "",
    [string]$DbPassword = "",
    # La fabrica usa MySQL. El valor "sqlite" existe para probar la
    # instalacion completa (configuracion + lanzador + arranque) en una
    # maquina donde no hay MySQL: no es un modo de uso de la fabrica.
    [string]$DbEngine = "mysql",
    [int]$WebPort = 8000,
    [string]$TaskName = "FEMAG Webapp QR",
    [string]$FirewallProfiles = "Domain,Private",
    [string]$FirewallRuleName = "FEMAG Webapp Server",
    [string]$ParamsFile = "",
    [switch]$ForceConfig,
    # Escribe la configuracion y el lanzador, pero no registra la tarea ni
    # abre el firewall: sirve para preparar la maquina y arrancar el servidor
    # a mano, y para probar el script sin permisos de administrador.
    [switch]$SkipServiceSetup,
    # No abre el navegador al terminar (instalacion desatendida).
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# El instalador pasa los datos en un archivo y no en la linea de comandos: la
# clave de MySQL queda expuesta en la lista de procesos mientras corre.
#
# Cuando se pasan los dos, manda la linea de comandos: el instalador no
# define ninguno (va todo por archivo) y un operador que corre el script a
# mano espera que lo que escribio en la linea sea lo que quede.
$fromCommandLine = @{}
foreach ($name in @("PublicHostName", "DbHost", "DbPort", "DbName", "DbUser", "DbPassword", "WebPort")) {
    $fromCommandLine[$name] = $PSBoundParameters.ContainsKey($name)
}

if ($ParamsFile -and (Test-Path -LiteralPath $ParamsFile)) {
    foreach ($line in Get-Content -LiteralPath $ParamsFile -Encoding UTF8) {
        if (-not $line.Trim() -or $line.Trim().StartsWith("#")) { continue }
        $parts = $line.Split("=", 2)
        if ($parts.Count -ne 2) { continue }
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        switch ($key) {
            "PublicHostName" { if (-not $fromCommandLine["PublicHostName"]) { $PublicHostName = $value } }
            "DbHost" { if (-not $fromCommandLine["DbHost"]) { $DbHost = $value } }
            "DbPort" { if (-not $fromCommandLine["DbPort"]) { $DbPort = [int]$value } }
            "DbName" { if (-not $fromCommandLine["DbName"]) { $DbName = $value } }
            "DbUser" { if (-not $fromCommandLine["DbUser"]) { $DbUser = $value } }
            "DbPassword" { if (-not $fromCommandLine["DbPassword"]) { $DbPassword = $value } }
            "WebPort" { if (-not $fromCommandLine["WebPort"]) { $WebPort = [int]$value } }
        }
    }
}

#: Donde queda el registro de lo que hizo la instalacion. El administrador de
#: la fabrica no ve la consola del instalador: si algo falla, esto es lo que
#: hay que mirar.
$script:LogPath = $null

function Write-InstallLog {
    param([string]$Message, [string]$Level = "INFO")
    if (-not $script:LogPath) { return }
    try {
        $line = "{0} {1} {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
        Add-Content -LiteralPath $script:LogPath -Value $line -Encoding UTF8
    } catch {
        # El log es un extra: si no se puede escribir, la instalacion sigue.
    }
}

function Write-Step { param([string]$Message); Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan; Write-InstallLog $Message }
function Write-Fail { param([string]$Message); Write-Host $Message -ForegroundColor Red; Write-InstallLog $Message "ERROR" }

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Ejecute PowerShell como administrador: hay que registrar una tarea como SYSTEM y abrir el firewall."
    }
}

function Protect-ConfigFile {
    # Lo lee el servicio (que corre como SYSTEM) y lo administran los
    # administradores. Nadie mas.
    param([string]$Path)
    & icacls $Path /inheritance:r /grant:r "*S-1-5-18:(R)" "*S-1-5-32-544:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudieron proteger los permisos de $Path." }
}

function Wait-ForHealthCheck {
    param([int]$Port, [int]$TimeoutSeconds = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) { return $true }
        } catch {
            # Todavia no levanta: se sigue esperando.
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Get-LogTail {
    param([string]$Path, [int]$Lines = 25)
    if (-not (Test-Path -LiteralPath $Path)) { return "(no hay archivo de log en $Path)" }
    $content = Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue
    if (-not $content) { return "(el log $Path esta vacio)" }
    return ($content -join [Environment]::NewLine)
}

# Registrar la tarea como SYSTEM y abrir el firewall requieren administrador.
# En modo sin servicio no hace falta: solo se escriben archivos.
if (-not $SkipServiceSetup) {
    Assert-Administrator
}

$configDirectory = Split-Path -Parent $ConfigPath
$logsDirectory = Join-Path $configDirectory "logs"
New-Item -ItemType Directory -Force -Path $configDirectory, $logsDirectory | Out-Null

# El registro de la instalacion: el administrador de la fabrica no ve la
# consola del instalador, asi que si algo falla esto es lo que hay que mirar.
$script:LogPath = Join-Path $logsDirectory "instalar_servidor.log"
Write-InstallLog "Inicio de la instalacion del servidor webapp (host: $PublicHostName, puerto: $WebPort)"

if ($DbEngine -notin @("mysql", "sqlite")) {
    throw "DbEngine debe ser 'mysql' o 'sqlite' (valor recibido: '$DbEngine')."
}

$serverExe = Join-Path $InstallRoot "FEMAG Webapp Server.exe"
if (-not (Test-Path -LiteralPath $serverExe)) {
    throw "No se encuentra el ejecutable del servidor en $serverExe. El instalador no copio todo."
}

# --- Configuracion -----------------------------------------------------------
# En una reinstalacion NO se pisa la configuracion: si se perdiera, habria que
# volver a escribir la clave de MySQL y se perderian las sesiones abiertas.
if ((Test-Path -LiteralPath $ConfigPath) -and -not $ForceConfig) {
    Write-Step "La configuracion ya existe: se conserva ($ConfigPath)"
    Write-Host "Para cambiarla, edite ese archivo o corra el instalador con -ForceConfig." -ForegroundColor DarkGray
} else {
    Write-Step "Escribiendo la configuracion"
    if (-not $DbUser) { throw "Falta el usuario de MySQL (DB_USER)." }
    $publicUrl = "http://${PublicHostName}:$WebPort"
    $secretFile = Join-Path $configDirectory "webapp_secret.key"
    if (-not $publicUrl -or -not $secretFile) { throw "No se pudieron armar los datos de la configuracion." }
    if ($WebPort -lt 1 -or $WebPort -gt 65535) { throw "WebPort debe estar entre 1 y 65535." }
    $configContent = @"
# Generado por el instalador de FEMAG Webapp Server.
# Lo lee el servicio (que corre como SYSTEM) y lo administran los
# administradores. No hace falta editarlo para actualizar el servidor.
APP_ENV=production
FEMAG_DB_ENGINE=$DbEngine

# El servicio NO crea ni altera tablas. La migracion de esquema la aplica un
# administrador desde FEMAG Desktop, antes de levantar el servidor.
FEMAG_AUTO_MIGRATE_SCHEMA=0

DB_HOST=$DbHost
DB_PORT=$DbPort
DB_NAME=$DbName
DB_USER=$DbUser
DB_PASSWORD=$DbPassword

# La URL que se imprime en el QR de cada turno. Sin https:// la camara del
# celular no abre, asi que tiene que ser la que el celular puede abrir.
FEMAG_WEB_PUBLIC_URL=$publicUrl

# El secreto con el que se firman las cookies de sesion, fuera del perfil de
# SYSTEM para que sobreviva a los reinicios.
FEMAG_WEB_SECRET_FILE=$secretFile
"@
    # UTF-8 con BOM: PowerShell 5.1 (el del Server 2019) lee los .ps1 sin BOM
    # como Windows-1252 y rompe el arranque.
    [System.IO.File]::WriteAllText($ConfigPath, $configContent, (New-Object System.Text.UTF8Encoding($true)))
    if ($SkipServiceSetup) {
        # Sin el servicio nadie mas lee el archivo: el servidor se levanta a
        # mano con este usuario, asi que tiene que poder leerlo.
        Write-Host "Configuracion escrita: $ConfigPath" -ForegroundColor Green
    } else {
        Protect-ConfigFile -Path $ConfigPath
        Write-Host "Configuracion escrita y protegida: $ConfigPath" -ForegroundColor Green
    }
}

# --- Lanzador ----------------------------------------------------------------
Write-Step "Escribiendo el lanzador del servicio"
$launcherPath = Join-Path $InstallRoot "run_webapp.cmd"
$stdoutLog = Join-Path $logsDirectory "webapp_server.stdout.log"
$launcher = @"
@echo off
setlocal
set "FEMAG_CONFIG_DIR=$configDirectory"
set "FEMAG_ENV_FILE=$ConfigPath"
set "FEMAG_DB_ENGINE=$DbEngine"
set "FEMAG_WEB_HOST=0.0.0.0"
set "FEMAG_WEB_PORT=$WebPort"
set "FEMAG_WEB_PUBLIC_URL=http://${PublicHostName}:$WebPort"
set "FEMAG_WEB_SECRET_FILE=$(Join-Path $configDirectory 'webapp_secret.key')"
cd /d "$InstallRoot"
"$serverExe" >> "$stdoutLog" 2>&1
"@
# Sin BOM: cmd.exe ve el BOM como parte del primer comando y el arranque falla.
[System.IO.File]::WriteAllText($launcherPath, $launcher, (New-Object System.Text.UTF8Encoding($false)))

if ($SkipServiceSetup) {
    Write-Step "Modo sin servicio: no se registra la tarea ni se abre el firewall"
    Write-Host ""
    Write-Host "Configuracion: $ConfigPath"
    Write-Host "Lanzador:      $launcherPath"
    Write-Host "Log:           $(Join-Path $logsDirectory 'webapp_server.log')"
    Write-Host ""
    Write-Host "Para levantar el servidor a mano: ""$launcherPath""" -ForegroundColor Yellow
    exit 0
}

# --- Tarea programada --------------------------------------------------------
Write-Step "Registrando el arranque automatico ($TaskName)"
$action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument "/d /c `"`"$launcherPath`"`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "FEMAG Webapp Server. Escucha en 0.0.0.0:$WebPort; el celular entra por http://${PublicHostName}:$WebPort."
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

# --- Firewall ----------------------------------------------------------------
Write-Step "Abriendo el puerto $WebPort en el firewall"
$allowedProfiles = @($FirewallProfiles -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$invalidProfiles = @($allowedProfiles | Where-Object { $_ -notin @("Domain", "Private", "Public") })
if ($invalidProfiles.Count -gt 0) {
    throw "FirewallProfiles inválido: $($invalidProfiles -join ', ')."
}
$rule = Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
if (-not $rule) {
    New-NetFirewallRule -DisplayName $FirewallRuleName -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $WebPort -Profile $FirewallProfiles | Out-Null
} else {
    # En una reinstalacion el puerto puede cambiar: hay que actualizar el
    # puerto de la regla, no solo el perfil.
    $rule | Set-NetFirewallRule -Profile $FirewallProfiles -ErrorAction SilentlyContinue | Out-Null
    $rule | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -LocalPort $WebPort -ErrorAction SilentlyContinue | Out-Null
}
if (Get-Command Get-NetConnectionProfile -ErrorAction SilentlyContinue) {
    $activeProfiles = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue | ForEach-Object { $_.NetworkCategory } | Sort-Object -Unique)
    if ($activeProfiles.Count -gt 0 -and @($activeProfiles | Where-Object { $_ -in $allowedProfiles }).Count -eq 0) {
        Write-Warning "El perfil de red activo del servidor es '$($activeProfiles -join ', ')' y la regla de firewall cubre '$FirewallProfiles'. El celular no va a entrar hasta que coincidan: cambié el perfil con Set-NetConnectionProfile o vuelva a correr con -FirewallProfiles $($activeProfiles -join ',')."
    }
}

# --- Verificacion ------------------------------------------------------------
Write-Step "Verificando que el servidor levante"
$sano = Wait-ForHealthCheck -Port $WebPort
if (-not $sano) {
    Write-Fail "El servidor no respondio en http://127.0.0.1:$WebPort/health"
    Write-Host ""
    Write-Host "Ultimas lineas del log:" -ForegroundColor Yellow
    Write-Host (Get-LogTail -Path (Join-Path $logsDirectory "webapp_server.log"))
    Write-Host ""
    Write-Host "Revise tambien que MySQL este accesible con las credenciales del archivo de configuracion." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Servidor de la webapp listo." -ForegroundColor Green
Write-Host "Celular:    http://${PublicHostName}:$WebPort/produccion"
Write-Host "Health:     http://127.0.0.1:$WebPort/health"
Write-Host "Log:        $(Join-Path $logsDirectory 'webapp_server.log')"
Write-Host "Instalacion: $(Join-Path $logsDirectory 'instalar_servidor.log')"
Write-Host "Tarea:      $TaskName (arranca con la maquina, se reinicia si se cae)"
Write-InstallLog "Instalacion terminada: el servidor respondio en /health"

if (-not $NoBrowser) {
    # Se abre la pantalla de produccion en el navegador de la maquina: el
    # administrador tiene que ver que quedo funcionando.
    try {
        Start-Process "http://127.0.0.1:$WebPort/produccion" | Out-Null
    } catch {
        Write-InstallLog "No se pudo abrir el navegador: $($_.Exception.Message)" "WARN"
    }
}
