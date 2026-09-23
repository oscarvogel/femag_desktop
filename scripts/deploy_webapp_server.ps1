[CmdletBinding()]
param(
    [string]$SourcePath = (Split-Path -Parent $PSScriptRoot),
    [string]$InstallRoot = "C:\FEMAG\webapp",
    [string]$ConfigPath = "C:\ProgramData\FEMAG\webapp.env",
    [string]$TaskName = "FEMAG Webapp QR",
    [string]$PythonPath = "",
    [int]$WebPort = 8000,
    [string]$PublicHostName = "femag.local",
    [string]$CaddyExePath = "",
    [string]$CaddyServiceName = "FEMAG Caddy",
    [switch]$SkipCaddy,
    [switch]$SkipHealthCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step { param([string]$Message); Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan }
function Assert-Success { param([string]$Step); if ($LASTEXITCODE -gt 7) { throw "$Step falló con código $LASTEXITCODE." } }

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Ejecute PowerShell como administrador. El despliegue registra tareas, protege la configuración y puede abrir HTTPS en el firewall."
    }
}

function Invoke-BasePython {
    param([string[]]$Arguments)
    if ($PythonPath) {
        & $PythonPath @Arguments
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 @Arguments
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python @Arguments
    } else {
        throw "No se encontró Python. Instale Python 3.12 o indique -PythonPath."
    }
    if ($LASTEXITCODE -ne 0) { throw "Python base falló con código $LASTEXITCODE." }
}

function Test-EnvValue {
    param([string]$Content, [string]$Key)
    $match = [regex]::Match($Content, "(?m)^" + [regex]::Escape($Key) + "=(.+)$")
    if (-not $match.Success -or [string]::IsNullOrWhiteSpace($match.Groups[1].Value) -or $match.Groups[1].Value -like "REEMPLAZAR_*") {
        throw "Complete $Key en $ConfigPath y vuelva a ejecutar el despliegue."
    }
}

function Protect-ConfigFile {
    param([string]$Path)
    # Evita depender de nombres de grupos localizados: SYSTEM sólo lee y Administrators administra.
    & icacls $Path /inheritance:r /grant:r "*S-1-5-18:(R)" "*S-1-5-32-544:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudieron proteger los permisos de $Path." }
}

function Wait-ForHealthCheck {
    param([int]$Port)
    $deadline = (Get-Date).AddSeconds(30)
    do {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200 -and $response.Content -match '"status"\s*:\s*"ok"') {
                return
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)
    throw "La webapp no respondió saludable en http://127.0.0.1:$Port/health. Revise la tarea '$TaskName' y sus logs."
}

Assert-Administrator

$SourcePath = (Resolve-Path -LiteralPath $SourcePath).Path
$requiredFiles = @("requirements-web.txt", "webapp\__main__.py", "app\config\settings.py")
foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $SourcePath $relativePath))) {
        throw "La fuente no parece un checkout de FEMAG con webapp: falta $relativePath."
    }
}
if ($WebPort -lt 1 -or $WebPort -gt 65535) { throw "WebPort debe estar entre 1 y 65535." }
if ([string]::IsNullOrWhiteSpace($PublicHostName)) { throw "Indique un nombre público interno con -PublicHostName." }
if (-not $SkipCaddy -and -not $CaddyExePath) {
    throw "Indique -CaddyExePath para publicar HTTPS o use -SkipCaddy sólo para preparar el backend local."
}

$configDirectory = Split-Path -Parent $ConfigPath
$envTemplate = Join-Path $PSScriptRoot "webapp-server.env.example"
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    New-Item -ItemType Directory -Force -Path $configDirectory | Out-Null
    Copy-Item -LiteralPath $envTemplate -Destination $ConfigPath
    Protect-ConfigFile -Path $ConfigPath
    throw "Se creó la plantilla segura $ConfigPath. Complete DB_USER y DB_PASSWORD, mantenga FEMAG_AUTO_MIGRATE_SCHEMA=0 y ejecute nuevamente."
}

$configContent = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8
foreach ($key in @("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")) { Test-EnvValue -Content $configContent -Key $key }
if ($configContent -notmatch "(?m)^FEMAG_AUTO_MIGRATE_SCHEMA=0$") {
    throw "El archivo $ConfigPath debe incluir FEMAG_AUTO_MIGRATE_SCHEMA=0 para que el despliegue no altere el esquema MySQL."
}
Protect-ConfigFile -Path $ConfigPath

Write-Step "Sincronizando código de la webapp"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$robocopyArgs = @(
    $SourcePath, $InstallRoot, "/MIR", "/COPY:DAT", "/DCOPY:DAT", "/R:2", "/W:2", "/NFL", "/NDL", "/NJH", "/NJS",
    "/XD", ".git", ".venv", "venv", "build", "dist", ".tmp", "__pycache__", ".pytest_cache", "docs\prints", "installer\output",
    "/XF", ".env", "*.credential", "*.sqlite3", "*.sqlite3-journal"
)
& robocopy @robocopyArgs | Out-Host
Assert-Success "robocopy"

$venvPath = Join-Path $InstallRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Step "Creando entorno virtual Python"
    Invoke-BasePython -Arguments @("-m", "venv", $venvPath)
}

Write-Step "Actualizando dependencias de la webapp"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "No se pudo actualizar pip." }
& $venvPython -m pip install -r (Join-Path $InstallRoot "requirements-web.txt")
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias de la webapp." }

$launcherPath = Join-Path $InstallRoot "run_webapp.cmd"
$launcher = @"
@echo off
setlocal
set "FEMAG_ENV_FILE=$ConfigPath"
set "FEMAG_WEB_HOST=127.0.0.1"
set "FEMAG_WEB_PORT=$WebPort"
cd /d "$InstallRoot"
"$venvPython" -m webapp
"@
[System.IO.File]::WriteAllText($launcherPath, $launcher, (New-Object System.Text.UTF8Encoding($false)))

Write-Step "Registrando ejecución automática"
$action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument "/d /c `"`"$launcherPath`"`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "FEMAG Webapp QR interna. Sólo escucha en localhost; Caddy publica HTTPS a la LAN."
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

if (-not $SkipCaddy) {
    $CaddyExePath = (Resolve-Path -LiteralPath $CaddyExePath).Path
    $caddyConfigPath = Join-Path $configDirectory "Caddyfile"
    $caddyConfig = @"
{
    admin 127.0.0.1:2019
}

$PublicHostName {
    tls internal
    encode zstd gzip
    reverse_proxy 127.0.0.1:$WebPort
}
"@
    [System.IO.File]::WriteAllText($caddyConfigPath, $caddyConfig, (New-Object System.Text.UTF8Encoding($false)))

    Write-Step "Validando y recargando Caddy"
    & $CaddyExePath validate --config $caddyConfigPath --adapter caddyfile
    if ($LASTEXITCODE -ne 0) { throw "Caddy rechazó la configuración." }
    $caddyService = Get-Service -Name $CaddyServiceName -ErrorAction SilentlyContinue
    if ($null -eq $caddyService) {
        & sc.exe create $CaddyServiceName start= auto binPath= "`"$CaddyExePath`" run --environ --config `"$caddyConfigPath`" --adapter caddyfile"
        if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el servicio Caddy." }
        & sc.exe start $CaddyServiceName
        if ($LASTEXITCODE -ne 0) { throw "No se pudo iniciar el servicio Caddy." }
    } elseif ($caddyService.Status -ne "Running") {
        Start-Service -Name $CaddyServiceName
    } else {
        & $CaddyExePath reload --config $caddyConfigPath --adapter caddyfile
        if ($LASTEXITCODE -ne 0) { throw "No se pudo recargar Caddy; se conserva su configuración anterior." }
    }
    if (-not (Get-NetFirewallRule -DisplayName "FEMAG Webapp HTTPS" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "FEMAG Webapp HTTPS" -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort 443 -Profile Domain,Private | Out-Null
    }
}

if (-not $SkipHealthCheck) {
    Write-Step "Verificando backend y conexión MySQL"
    Wait-ForHealthCheck -Port $WebPort
}

Write-Host ""
Write-Host "Despliegue listo." -ForegroundColor Green
Write-Host "Backend: http://127.0.0.1:$WebPort/health"
if (-not $SkipCaddy) {
    Write-Host "LAN: https://$PublicHostName/health"
    Write-Host "Instale la CA interna de Caddy en los celulares autorizados antes de usar la cámara."
}
