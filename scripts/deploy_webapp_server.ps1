[CmdletBinding()]
param(
    [string]$SourcePath = (Split-Path -Parent $PSScriptRoot),
    [string]$InstallRoot = "C:\FEMAG\webapp",
    [string]$ConfigPath = "C:\ProgramData\FEMAG\webapp.env",
    [string]$TaskName = "FEMAG Webapp QR",
    [string]$PythonPath = "",
    [int]$WebPort = 8000,
    # El nombre NO debe terminar en ".local": la RFC 6762 reserva ese sufijo
    # para mDNS y los celulares (iOS y Android) resuelven los nombres .local
    # por multicast, no por el DNS de la LAN. La RFC recomienda .lan, .corp,
    # .internal o .intranet para redes privadas.
    [string]$PublicHostName = "femag.lan",
    [string]$CaddyExePath = "",
    [string]$CaddyServiceName = "FEMAG Caddy",
    [string]$FirewallProfiles = "Domain,Private",
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

function Resolve-BasePython {
    # Windows Server 2019 no viene con Python. Se busca el launcher "py" y, si no
    # esta, el "python" del PATH. Se prefiere 3.12, que es la version con la que
    # se valido la webapp, pero se acepta cualquier 3.10 o superior: un servidor
    # con 3.13 instalado no deberia quedar afuera del despliegue.
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath)) {
            throw "No se encontró el intérprete de Python en $PythonPath."
        }
        return ,@($PythonPath)
    }

    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += ,@("py", "-3.12")
        $candidates += ,@("py", "-3")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidates += ,@("python")
    }

    foreach ($candidate in $candidates) {
        $executable = $candidate[0]
        $prefix = @()
        if ($candidate.Count -gt 1) { $prefix = $candidate[1..($candidate.Count - 1)] }
        $version = & $executable @prefix -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0) { continue }
        $text = ($version | Select-Object -First 1)
        if ([string]::IsNullOrWhiteSpace($text)) { continue }
        $parts = $text.Trim().Split(".")
        if ($parts.Count -lt 2) { continue }
        if ([int]$parts[0] -lt 3) { continue }
        if ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10) { continue }
        Write-Step "Python base: $text ($executable $($prefix -join ' '))"
        return ,(@($executable) + $prefix)
    }

    throw "No se encontró Python 3.10 o superior. Instale Python 3.12 en el servidor o indique -PythonPath."
}

function Invoke-BasePython {
    param([string[]]$Arguments)
    $base = Resolve-BasePython
    $executable = $base[0]
    $prefix = @()
    if ($base.Count -gt 1) { $prefix = $base[1..($base.Count - 1)] }
    & $executable @prefix @Arguments
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

# La URL publica del servidor es la que se imprime en el QR de cada turno, asi
# que tiene que ser la que el celular puede abrir. Sale de -PublicHostName, pero
# el archivo de configuracion puede sobreescribirla.
$publicUrl = "https://$PublicHostName"
$publicUrlMatch = [regex]::Match($configContent, "(?m)^FEMAG_WEB_PUBLIC_URL=(.+)$")
if ($publicUrlMatch.Success) {
    $candidateUrl = $publicUrlMatch.Groups[1].Value.Trim()
    if ($candidateUrl) { $publicUrl = $candidateUrl }
}
if (-not $publicUrl.StartsWith("https://")) {
    throw "FEMAG_WEB_PUBLIC_URL debe empezar con https:// (valor actual: $publicUrl). La cámara del celular sólo funciona en un contexto seguro."
}

# El secreto con el que se firman las cookies de sesion vive fuera del perfil
# de SYSTEM, junto a la configuracion, y con los mismos permisos restringidos.
$secretFilePath = Join-Path $configDirectory "webapp_secret.key"
$secretMatch = [regex]::Match($configContent, "(?m)^FEMAG_WEB_SECRET_FILE=(.+)$")
if ($secretMatch.Success -and $secretMatch.Groups[1].Value.Trim()) {
    $secretFilePath = $secretMatch.Groups[1].Value.Trim()
}
if (-not [System.IO.Path]::IsPathRooted($secretFilePath)) {
    $secretFilePath = Join-Path $configDirectory $secretFilePath
}

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
set "FEMAG_WEB_PUBLIC_URL=$publicUrl"
set "FEMAG_WEB_SECRET_FILE=$secretFilePath"
cd /d "$InstallRoot"
"$venvPython" -m webapp
"@
# Sin BOM: cmd.exe ve el BOM como parte del primer comando y el arranque falla.
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
    # El perfil de red del servidor decide si la regla de firewall aplica. En
    # una red de fabrica el Windows Server 2019 puede quedar en perfil Public:
    # con la regla restringida a Domain/Private el celular no entra y parece un
    # problema de HTTPS cuando en realidad es el firewall.
    $allowedProfiles = @($FirewallProfiles -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $invalidProfiles = @($allowedProfiles | Where-Object { $_ -notin @("Domain", "Private", "Public") })
    if ($invalidProfiles.Count -gt 0) {
        throw "FirewallProfiles inválido: $($invalidProfiles -join ', '). Use Domain, Private, Public o una combinación separada por comas."
    }
    if (-not (Get-NetFirewallRule -DisplayName "FEMAG Webapp HTTPS" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "FEMAG Webapp HTTPS" -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort 443 -Profile $FirewallProfiles | Out-Null
    } else {
        Set-NetFirewallRule -DisplayName "FEMAG Webapp HTTPS" -Profile $FirewallProfiles -ErrorAction SilentlyContinue | Out-Null
    }
    if (Get-Command Get-NetConnectionProfile -ErrorAction SilentlyContinue) {
        $activeProfiles = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue | ForEach-Object { $_.NetworkCategory } | Sort-Object -Unique)
        if ($activeProfiles.Count -gt 0 -and @($activeProfiles | Where-Object { $_ -in $allowedProfiles }).Count -eq 0) {
            Write-Warning "El perfil de red activo del servidor es '$($activeProfiles -join ', ')' y la regla de firewall cubre '$FirewallProfiles'. El celular no va a entrar hasta que coincidan: usá -FirewallProfiles $($activeProfiles -join ',') o cambiá el perfil con Set-NetConnectionProfile."
        }
    }

    Write-Step "Verificando que Caddy publique el puerto 443"
    $listening = $false
    for ($attempt = 0; $attempt -lt 15; $attempt++) {
        if (Get-NetTCPConnection -LocalPort 443 -State Listen -ErrorAction SilentlyContinue) {
            $listening = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $listening) {
        throw "Caddy no está escuchando en el puerto 443. Revisá el servicio '$CaddyServiceName' y que $PublicHostName resuelva a este servidor."
    }
}

if (-not $SkipHealthCheck) {
    Write-Step "Verificando backend y conexión MySQL"
    Wait-ForHealthCheck -Port $WebPort
}

# El secreto de sesion lo crea la webapp en el primer arranque. Se protege con
# los mismos permisos que la configuracion: lo lee SYSTEM y lo administran los
# administradores.
if (Test-Path -LiteralPath $secretFilePath) {
    Protect-ConfigFile -Path $secretFilePath
}

Write-Host ""
Write-Host "Despliegue listo." -ForegroundColor Green
Write-Host "Backend: http://127.0.0.1:$WebPort/health"
Write-Host "URL publica (la que se imprime en el QR de turnos): $publicUrl"
if (-not $SkipCaddy) {
    Write-Host "LAN: https://$PublicHostName/health"
    Write-Host "Instale la CA interna de Caddy en los celulares autorizados antes de usar la cámara."
    $caddyStorage = Join-Path $env:SystemRoot "System32\config\systemprofile\AppData\Roaming\Caddy"
    Write-Host "Certificado raíz para distribuir: $caddyStorage\pki\authorities\local\root.crt"
}
