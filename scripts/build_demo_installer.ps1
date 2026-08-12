[CmdletBinding()]
param(
    [switch]$SkipInstallDependencies,
    [switch]$VersionOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$BuildVersionFile = Join-Path $RepoRoot "app\build_demo_version.py"
$StateFile = Join-Path $RepoRoot "installer\.demo_build_state"
$InstallerOutputDir = Join-Path $RepoRoot "installer\output"
$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

function Get-DemoBuildVersion {
    param([string]$Path)

    $today = Get-Date -Format "yyyy.MM.dd"
    $state = $null
    if (Test-Path $Path) {
        try {
            $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
            if ($raw) {
                $parsed = $raw | ConvertFrom-Json
                if ($parsed.date -and $parsed.counter) {
                    $state = $parsed
                }
            }
        } catch {
            $state = $null
        }
    }

    $counter = 1
    if ($state -and "$($state.date)" -eq $today) {
        $counter = [int]$state.counter + 1
    }

    $newState = [pscustomobject]@{ date = $today; counter = $counter } | ConvertTo-Json -Compress
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Set-Content -LiteralPath $Path -Value $newState -Encoding UTF8

    return ("{0}.{1:D2}" -f $today, $counter)
}

$BuildVersion = Get-DemoBuildVersion -Path $StateFile

if ($VersionOnly) {
    Write-Host "BuildVersion: $BuildVersion" -ForegroundColor Green
    Write-Host "StateFile:    $StateFile" -ForegroundColor Green
    return
}

if (-not (Test-Path $Python)) {
    throw "No existe $Python. Cree el entorno de desarrollo antes de compilar."
}
if (-not $Iscc) {
    throw "No se encontro Inno Setup 6 (ISCC.exe) en esta PC de compilacion."
}

Push-Location $RepoRoot
try {
    Set-Content -LiteralPath $BuildVersionFile -Value "BUILD_DEMO_VERSION = `"$BuildVersion`"" -Encoding UTF8

    if (-not $SkipInstallDependencies) {
        & $Python -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias de compilacion." }
    }

    Remove-Item -Recurse -Force "build\FEMAG Desktop DEMO" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "dist\FEMAG Desktop DEMO" -ErrorAction SilentlyContinue
    if (Test-Path $InstallerOutputDir) {
        Get-ChildItem -LiteralPath $InstallerOutputDir -Filter "FEMAG_Desktop_DEMO_Standalone_Setup*.exe" -File |
            Remove-Item -Force
    }

    & $Python -m PyInstaller --noconfirm --clean installer\FEMAG_Desktop_Demo.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo." }

    & $Iscc "/DMyAppVersion=$BuildVersion" installer\FEMAG_Desktop_Demo.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallo." }

    Write-Host "Version: $BuildVersion" -ForegroundColor Green
    Write-Host "Instalador generado: installer\output\FEMAG_Desktop_DEMO_Standalone_Setup.exe" -ForegroundColor Green
} finally {
    Pop-Location
}
