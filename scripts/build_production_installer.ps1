[CmdletBinding()]
param(
    [switch]$SkipInstallDependencies,
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
$BuildVersion = Get-Date -Format "yyyy.MM.dd.HH.mm.ss"
$BuildVersionFile = Join-Path $RepoRoot "app\build_version.py"
$BuildInfoFile = Join-Path $RepoRoot "app\build_info.py"
$InstallerOutputDir = Join-Path $RepoRoot "installer\output"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "No existe $Python. Cree el entorno de desarrollo o indique -PythonPath."
}

$resolveParams = @{}
if ($IsccPath) { $resolveParams["IsccPath"] = $IsccPath }
if ($NoAutoInstall) { $resolveParams["NoAutoInstall"] = $true }
$Iscc = Resolve-InnoSetup @resolveParams

Push-Location $RepoRoot
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($BuildVersionFile, "BUILD_VERSION = `"$BuildVersion`"`n", $utf8NoBom)
    [System.IO.File]::WriteAllText(
        $BuildInfoFile,
        "APP_ID = `"femag`"`nBUILD_VERSION = `"$BuildVersion`"`n",
        $utf8NoBom
    )

    if (-not $SkipInstallDependencies) {
        Invoke-Native -Command $Python `
            -Arguments @("-m", "pip", "install", "--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org", "-r", "requirements-build.txt") `
            -FailureMessage "No se pudieron instalar las dependencias de compilacion."
    }

    Remove-Item -Recurse -Force "build\FEMAG Desktop" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "dist\FEMAG Desktop" -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $InstallerOutputDir)) {
        New-Item -ItemType Directory -Force $InstallerOutputDir | Out-Null
    } else {
        Get-ChildItem -LiteralPath $InstallerOutputDir -Filter "FEMAG_Desktop_Produccion_Setup*.exe" -File |
            Remove-Item -Force
    }

    Invoke-Native -Command $Python `
        -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", "installer\FEMAG_Desktop.spec") `
        -FailureMessage "PyInstaller fallo."

    Invoke-Native -Command $Iscc `
        -Arguments @("/DMyAppVersion=$BuildVersion", "installer\FEMAG_Desktop.iss") `
        -FailureMessage "Inno Setup fallo."

    Write-Host "Version: $BuildVersion" -ForegroundColor Green
    Write-Host "Instalador generado: installer\output\FEMAG_Desktop_Produccion_Setup.exe" -ForegroundColor Green
} finally {
    Pop-Location
}
