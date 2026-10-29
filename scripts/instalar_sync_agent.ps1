# Instala el agente FEMAG Sync en Windows Server 2019.
#
# Toma los datos de MySQL desde el webapp.env que ya usa el servidor de la
# webapp y los combina con el sync.env (URL/token) que prepara el responsable.
# No necesita Python en la maquina: el agente es un EXE congelado.

[CmdletBinding()]
param(
    [string]$InstallRoot = "C:\FEMAG\sync",
    [string]$ConfigPath = "C:\ProgramData\FEMAG\sync.env",
    [string]$WebappEnvPath = "C:\ProgramData\FEMAG\webapp.env",
    [string]$SyncEnvSource = "",
    [string]$BaseUrl = "",
    [string]$Token = "",
    [string]$TaskName = "FEMAG Sync Agent",
    [int]$IntervalMinutes = 5,
    [switch]$SkipTask,
    [switch]$RunNow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Ejecute PowerShell como administrador."
    }
}

function Read-EnvFile {
    param([string]$Path)
    $values = [ordered]@{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $values
    }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $index = $trimmed.IndexOf("=")
        if ($index -lt 1) { continue }
        $key = $trimmed.Substring(0, $index).Trim()
        $value = $trimmed.Substring($index + 1).Trim()
        if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

function Write-EnvFile {
    param([string]$Path, $Values)
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $lines = @($Values.Keys | ForEach-Object { "$_=$($Values[$_])" })
    [System.IO.File]::WriteAllLines(
        $Path,
        $lines,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

function Protect-ConfigFile {
    param([string]$Path)
    & icacls $Path /inheritance:r /grant:r "*S-1-5-18:(R)" "*S-1-5-32-544:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudieron proteger los permisos de $Path."
    }
}

Assert-Administrator

$exe = Join-Path $InstallRoot "FEMAG Sync Agent.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "No se encontro el agente en $exe."
}
if (-not (Test-Path -LiteralPath $WebappEnvPath)) {
    throw "No se encontro $WebappEnvPath. El agente necesita la configuracion MySQL del servidor webapp."
}

$webapp = Read-EnvFile -Path $WebappEnvPath
foreach ($required in @("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")) {
    if (-not $webapp.Contains($required) -or [string]::IsNullOrWhiteSpace($webapp[$required])) {
        throw "Falta $required en $WebappEnvPath."
    }
}

$sourcePath = $SyncEnvSource
if ([string]::IsNullOrWhiteSpace($sourcePath) -and (Test-Path -LiteralPath $ConfigPath)) {
    $sourcePath = $ConfigPath
}
$syncValues = [ordered]@{}
if (-not [string]::IsNullOrWhiteSpace($sourcePath)) {
    $syncValues = Read-EnvFile -Path $sourcePath
}
if (-not [string]::IsNullOrWhiteSpace($BaseUrl)) { $syncValues["FEMAG_SYNC_BASE_URL"] = $BaseUrl }
if (-not [string]::IsNullOrWhiteSpace($Token)) { $syncValues["FEMAG_SYNC_API_TOKEN"] = $Token }

$baseUrl = $syncValues["FEMAG_SYNC_BASE_URL"]
$token = $syncValues["FEMAG_SYNC_API_TOKEN"]
if ([string]::IsNullOrWhiteSpace($baseUrl) -or [string]::IsNullOrWhiteSpace($token)) {
    throw "Falta FEMAG_SYNC_BASE_URL o FEMAG_SYNC_API_TOKEN en $sourcePath."
}
if ($baseUrl -notmatch "^https://") {
    throw "FEMAG_SYNC_BASE_URL debe usar HTTPS."
}

$values = [ordered]@{}
foreach ($key in $syncValues.Keys) {
    $values[$key] = $syncValues[$key]
}
$values["FEMAG_SYNC_BASE_URL"] = $baseUrl.TrimEnd("/")
$values["FEMAG_SYNC_API_TOKEN"] = $token
if (-not $values.Contains("FEMAG_SYNC_LOG_FILE")) {
    $values["FEMAG_SYNC_LOG_FILE"] = "C:\ProgramData\FEMAG\logs\sync_agent.log"
}
$values["FEMAG_DB_ENGINE"] = "mysql"
$values["FEMAG_SECURE_CONFIG"] = "0"
$values["FEMAG_DEMO"] = "0"
$values["APP_ENV"] = "production"
$values["FEMAG_ENV_FILE"] = $ConfigPath
$values["DB_HOST"] = $webapp["DB_HOST"]
$values["DB_PORT"] = $webapp["DB_PORT"]
$values["DB_NAME"] = $webapp["DB_NAME"]
$values["DB_USER"] = $webapp["DB_USER"]
$values["DB_PASSWORD"] = $webapp["DB_PASSWORD"]

Write-EnvFile -Path $ConfigPath -Values $values
Protect-ConfigFile -Path $ConfigPath

$logDir = Split-Path -Parent $values["FEMAG_SYNC_LOG_FILE"]
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

Write-Host "Preparando esquema de sincronizacion..." -ForegroundColor Cyan
$initOutput = & $exe --init-schema 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo preparar el esquema de sync. El usuario MySQL debe tener permiso para crear tablas. Detalle: $initOutput"
}

if (-not $SkipTask) {
    $action = New-ScheduledTaskAction `
        -Execute $exe `
        -Argument "--snapshot" `
        -WorkingDirectory $InstallRoot
    $trigger = New-ScheduledTaskTrigger `
        -Once `
        -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $principal = New-ScheduledTaskPrincipal `
        -UserId "SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Force | Out-Null
    Write-Host "Tarea programada '$TaskName' registrada cada $IntervalMinutes minutos." -ForegroundColor Green
}

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Tarea iniciada. Revise $($values['FEMAG_SYNC_LOG_FILE'])." -ForegroundColor Yellow
}

Write-Host "Agente instalado. Configuracion: $ConfigPath" -ForegroundColor Green
