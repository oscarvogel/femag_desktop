# Compila el agente FEMAG Sync y su instalador.
#
#   .\scripts\build_sync_agent_installer.ps1
#   .\scripts\build_sync_agent_installer.ps1 -SkipFrozenBuild
#
# Salida:
#   dist\FEMAG Sync Agent\FEMAG Sync Agent.exe
#   installer\output\FEMAG_Sync_Agent_Setup.exe

[CmdletBinding()]
param(
    [switch]$SkipInstallDependencies,
    [switch]$SkipFrozenBuild,
    [string]$BuildVersion,
    [string]$PythonPath,
    [string]$IsccPath,
    [switch]$NoAutoInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "Invoke-Native.ps1")
. (Join-Path $PSScriptRoot "Resolve-InnoSetup.ps1")

$Python = if ($PythonPath) { $PythonPath } else { Join-Path $RepoRoot ".venv\Scripts\python.exe" }
if ((-not (Test-Path -LiteralPath $Python)) -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $Python = (Get-Command python).Source
}
if (-not $BuildVersion) {
    $BuildVersion = Get-Date -Format "yyyy.MM.dd.HH.mm.ss"
}
$InstallerOutputDir = Join-Path $RepoRoot "installer\output"
$FrozenDir = Join-Path $RepoRoot "dist\FEMAG Sync Agent"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "No existe $Python. Cree el entorno de desarrollo o indique -PythonPath."
}

$resolveParams = @{}
if ($IsccPath) { $resolveParams["IsccPath"] = $IsccPath }
if ($NoAutoInstall) { $resolveParams["NoAutoInstall"] = $true }
$Iscc = Resolve-InnoSetup @resolveParams

Push-Location $RepoRoot
try {
    if (-not $SkipInstallDependencies) {
        Invoke-Native -Command $Python `
            -Arguments @("-m", "pip", "install", "--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org", "-r", "requirements-build.txt") `
            -FailureMessage "No se pudieron instalar las dependencias de compilacion."
    }

    if (-not $SkipFrozenBuild) {
        Write-Host "Compilando el agente congelado..." -ForegroundColor Cyan
        Invoke-Native -Command $Python `
            -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", "installer\FEMAG_Sync_Agent.spec") `
            -FailureMessage "PyInstaller fallo."
    }

    $agentExe = Join-Path $FrozenDir "FEMAG Sync Agent.exe"
    if (-not (Test-Path -LiteralPath $agentExe)) {
        throw "No se encuentra el agente en $agentExe. Compilalo primero."
    }

    if (-not (Test-Path -LiteralPath $InstallerOutputDir)) {
        New-Item -ItemType Directory -Force $InstallerOutputDir | Out-Null
    } else {
        Get-ChildItem -LiteralPath $InstallerOutputDir -Filter "FEMAG_Sync_Agent_Setup*.exe" -File |
            Remove-Item -Force
    }

    Write-Host "Compilando el instalador de Inno Setup..." -ForegroundColor Cyan
    Invoke-Native -Command $Iscc `
        -Arguments @("/DMyAppVersion=$BuildVersion", "installer\FEMAG_Sync_Agent.iss") `
        -FailureMessage "Inno Setup fallo."

    $setup = Join-Path $InstallerOutputDir "FEMAG_Sync_Agent_Setup.exe"
    if (-not (Test-Path -LiteralPath $setup)) {
        throw "Inno Setup no genero $setup."
    }

    Write-Host "Instalador generado: $setup" -ForegroundColor Green
} finally {
    Pop-Location
}
