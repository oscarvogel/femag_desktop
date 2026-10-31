# Compila el instalador del servidor webapp (FEMAG_Webapp_Server_Setup.exe).
#
# Son dos pasos: primero el ejecutable congelado del servidor (PyInstaller,
# installer\FEMAG_Webapp_Server.spec) y despues el instalador de Inno Setup
# que lo lleva junto con el script de instalacion.
#
#   .\scripts\build_webapp_server_installer.ps1
#   .\scripts\build_webapp_server_installer.ps1 -SkipFrozenBuild
#
# La salida queda en installer\output\FEMAG_Webapp_Server_Setup.exe: es el
# archivo que se copia a la maquina de la fabrica y se corre ahi.

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
    $BuildVersion = (Get-Date).ToUniversalTime().ToString("yyyy.MM.dd.HH.mm.ss")
}
$InstallerOutputDir = Join-Path $RepoRoot "installer\output"
$FrozenDir = Join-Path $RepoRoot "dist\FEMAG Webapp Server"

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
        Write-Host "Compilando el ejecutable congelado del servidor..." -ForegroundColor Cyan
        Invoke-Native -Command $Python `
            -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", "installer\FEMAG_Webapp_Server.spec") `
            -FailureMessage "PyInstaller fallo."
    }

    $serverExe = Join-Path $FrozenDir "FEMAG Webapp Server.exe"
    if (-not (Test-Path -LiteralPath $serverExe)) {
        throw "No se encuentra el ejecutable del servidor en $serverExe. Compilalo primero (sin -SkipFrozenBuild)."
    }

    if (-not (Test-Path -LiteralPath $InstallerOutputDir)) {
        New-Item -ItemType Directory -Force $InstallerOutputDir | Out-Null
    } else {
        Get-ChildItem -LiteralPath $InstallerOutputDir -Filter "FEMAG_Webapp_Server_Setup*.exe" -File |
            Remove-Item -Force
    }

    Write-Host "Compilando el instalador de Inno Setup..." -ForegroundColor Cyan
    Invoke-Native -Command $Iscc `
        -Arguments @("/DMyAppVersion=$BuildVersion", "installer\FEMAG_Webapp_Server.iss") `
        -FailureMessage "Inno Setup fallo."

    $setup = Join-Path $InstallerOutputDir "FEMAG_Webapp_Server_Setup.exe"
    if (-not (Test-Path -LiteralPath $setup)) {
        throw "Inno Setup no genero $setup."
    }

    Write-Host "Instalador generado: $setup" -ForegroundColor Green
} finally {
    Pop-Location
}
