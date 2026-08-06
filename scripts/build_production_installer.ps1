[CmdletBinding()]
param(
    [switch]$SkipInstallDependencies,
    [string]$PythonPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = if ($PythonPath) { $PythonPath } else { Join-Path $RepoRoot ".venv\Scripts\python.exe" }
$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not (Test-Path $Python)) {
    throw "No existe $Python. Cree el entorno de desarrollo o indique -PythonPath."
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

    Remove-Item -Recurse -Force "build\FEMAG Desktop" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "dist\FEMAG Desktop" -ErrorAction SilentlyContinue

    & $Python -m PyInstaller --noconfirm --clean installer\FEMAG_Desktop.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo." }

    & $Iscc installer\FEMAG_Desktop.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallo." }

    Write-Host "Instalador generado: installer\output\FEMAG_Desktop_Produccion_Setup_v2.exe" -ForegroundColor Green
} finally {
    Pop-Location
}
