[CmdletBinding()]
param(
    [switch]$SkipInstallDependencies,
    [string]$PythonPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "Invoke-Native.ps1")

$Python = if ($PythonPath) {
    $PythonPath
} else {
    Join-Path $RepoRoot ".venv\Scripts\python.exe"
}

if ((-not (Test-Path -LiteralPath $Python)) -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $Python = (Get-Command python).Source
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "No existe $Python. Cree el entorno de desarrollo o indique -PythonPath."
}

$OutputExe = Join-Path $RepoRoot "dist\FEMAG_Managerial_Summary.exe"

Push-Location $RepoRoot
try {
    if (-not $SkipInstallDependencies) {
        Invoke-Native -Command $Python `
            -Arguments @(
                "-m", "pip", "install",
                "--trusted-host", "pypi.org",
                "--trusted-host", "files.pythonhosted.org",
                "-r", "requirements-build.txt"
            ) `
            -FailureMessage "No se pudieron instalar las dependencias de compilacion."
    }

    Remove-Item -Recurse -Force "build\FEMAG_Managerial_Summary" -ErrorAction SilentlyContinue
    Remove-Item -Force $OutputExe -ErrorAction SilentlyContinue

    Write-Host "Generando FEMAG_Managerial_Summary.exe..." -ForegroundColor Cyan

    Invoke-Native -Command $Python `
        -Arguments @(
            "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "installer\FEMAG_Managerial_Summary.spec"
        ) `
        -FailureMessage "PyInstaller fallo al generar FEMAG_Managerial_Summary.exe."

    if (-not (Test-Path -LiteralPath $OutputExe)) {
        throw "PyInstaller termino pero no se encontro $OutputExe"
    }

    Write-Host "Verificando arranque del ejecutable..." -ForegroundColor Cyan
    Invoke-Native -Command $OutputExe `
        -Arguments @("--help") `
        -FailureMessage "El ejecutable se genero pero no pudo iniciar."

    $file = Get-Item -LiteralPath $OutputExe
    Write-Host ""
    Write-Host "EXE GERENCIAL GENERADO OK" -ForegroundColor Green
    Write-Host "Ruta: $($file.FullName)" -ForegroundColor Green
    Write-Host ("Tamano: {0:N2} MB" -f ($file.Length / 1MB)) -ForegroundColor Green
    Write-Host ""
    Write-Host "Pruebas recomendadas en el Windows Server:" -ForegroundColor Yellow
    Write-Host "  .\FEMAG_Managerial_Summary.exe --health-check"
    Write-Host "  .\FEMAG_Managerial_Summary.exe --send-now"
    Write-Host "  .\FEMAG_Managerial_Summary.exe --daily"
} finally {
    Pop-Location
}
