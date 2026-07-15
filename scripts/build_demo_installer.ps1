[CmdletBinding()]
param(
    [switch]$SkipInstallDependencies
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not (Test-Path $Python)) {
    throw "No existe $Python. Cree el entorno de desarrollo antes de compilar."
}
if (-not $Iscc) {
    throw "No se encontro Inno Setup 6 (ISCC.exe) en esta PC de compilacion."
}

Push-Location $RepoRoot
try {
    if (-not $SkipInstallDependencies) {
        & $Python -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias de compilacion." }
    }

    Remove-Item -Recurse -Force "build\FEMAG Desktop DEMO" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "dist\FEMAG Desktop DEMO" -ErrorAction SilentlyContinue

    & $Python -m PyInstaller --noconfirm --clean installer\FEMAG_Desktop_Demo.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo." }

    & $Iscc installer\FEMAG_Desktop_Demo.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallo." }

    Write-Host "Instalador generado: installer\output\FEMAG_Desktop_DEMO_Standalone_Setup.exe" -ForegroundColor Green
} finally {
    Pop-Location
}
