[CmdletBinding()]
param(
    [switch]$SkipInstallDependencies,
    [switch]$VersionOnly,
    [string]$IsccPath,
    [switch]$NoAutoInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "Invoke-Native.ps1")
. (Join-Path $PSScriptRoot "Resolve-InnoSetup.ps1")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$BuildVersionFile = Join-Path $RepoRoot "app\build_demo_version.py"
$StateFile = Join-Path $RepoRoot "installer\.demo_build_state"
$InstallerOutputDir = Join-Path $RepoRoot "installer\output"

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
$resolveParams = @{}
if ($IsccPath) { $resolveParams["IsccPath"] = $IsccPath }
if ($NoAutoInstall) { $resolveParams["NoAutoInstall"] = $true }
$Iscc = Resolve-InnoSetup @resolveParams

Push-Location $RepoRoot
try {
    Set-Content -LiteralPath $BuildVersionFile -Value "BUILD_DEMO_VERSION = `"$BuildVersion`"" -Encoding UTF8

    if (-not $SkipInstallDependencies) {
        Invoke-Native -Command $Python `
            -Arguments @("-m", "pip", "install", "--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org", "-r", "requirements-build.txt") `
            -FailureMessage "No se pudieron instalar las dependencias de compilacion."
    }

    Remove-Item -Recurse -Force "build\FEMAG Desktop DEMO" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "dist\FEMAG Desktop DEMO" -ErrorAction SilentlyContinue
    if (Test-Path $InstallerOutputDir) {
        Get-ChildItem -LiteralPath $InstallerOutputDir -Filter "FEMAG_Desktop_DEMO_Standalone_Setup*.exe" -File |
            Remove-Item -Force
    }

    Invoke-Native -Command $Python `
        -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", "installer\FEMAG_Desktop_Demo.spec") `
        -FailureMessage "PyInstaller fallo."

    # Reintento ante bloqueos transitorios del antivirus (ver build de producción).
    $isccAttempts = 0
    $isccOk = $false
    while (-not $isccOk -and $isccAttempts -lt 2) {
        $isccAttempts++
        try {
            Invoke-Native -Command $Iscc `
                -Arguments @("/DMyAppVersion=$BuildVersion", "installer\FEMAG_Desktop_Demo.iss") `
                -FailureMessage "Inno Setup fallo."
            $isccOk = $true
        } catch {
            if ($isccAttempts -ge 2) { throw }
            Write-Warning "ISCC falló (intento $isccAttempts/2): $($_.Exception.Message)"
            Write-Host "Esperando 15s por posible bloqueo transitorio (antivirus) y reintentando..." -ForegroundColor Yellow
            Start-Sleep -Seconds 15
        }
    }

    Write-Host "Version: $BuildVersion" -ForegroundColor Green
    Write-Host "Instalador generado: installer\output\FEMAG_Desktop_DEMO_Standalone_Setup.exe" -ForegroundColor Green
} finally {
    Pop-Location
}
