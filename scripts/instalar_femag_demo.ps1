[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [string]$InstallRoot = "$env:USERPROFILE\FEMAG",
    [string]$RepoUrl = "https://github.com/oscarvogel/femag_desktop.git",
    [string]$Branch = "main",
    [switch]$Reset,
    [switch]$SkipWinget,
    [switch]$SkipInstall,
    [switch]$SkipUi,
    [switch]$SkipDemoSeed,
    [switch]$SkipSmoke
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step { param([string]$Message); Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Info { param([string]$Message); Write-Host "    $Message" -ForegroundColor Gray }
function Write-Warn { param([string]$Message); Write-Host ""; Write-Host "AVISO: $Message" -ForegroundColor Yellow }
function Test-Command { param([string]$Name); return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Assert-Success { param([string]$Step); if ($LASTEXITCODE -ne 0) { throw "$Step fallo con codigo de salida $LASTEXITCODE." } }

function Install-WithWinget {
    param([string]$PackageId, [string]$DisplayName)
    if ($SkipWinget) { throw "$DisplayName no esta instalado y se pidio omitir winget." }
    if (-not (Test-Command "winget")) { throw "$DisplayName no esta instalado y winget no esta disponible." }
    Write-Info "Instalando $DisplayName con winget..."
    winget install --id $PackageId --exact --source winget --accept-source-agreements --accept-package-agreements
    Assert-Success "winget install $DisplayName"
}

function Ensure-Git {
    Write-Step "Verificando Git"
    if (-not (Test-Command "git")) { Install-WithWinget -PackageId "Git.Git" -DisplayName "Git" }
    if (-not (Test-Command "git")) { throw "Git no quedo disponible en PATH." }
    git --version
    git config --global http.sslBackend schannel
}

function Find-PythonExe {
    # Devuelve la ruta a python.exe preferida. Prioriza instalaciones reales de Python 3.12+
    # sobre el launcher py.exe, que a veces apunta a otro usuario desde PowerShell no interactivo.
    $candidates = @(
        "C:\Python312\python.exe",
        "C:\Python313\python.exe",
        "C:\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    if (Test-Command "py") { return "py" }
    if (Test-Command "python") { return "python" }
    return $null
}

function Test-Python {
    $exe = Find-PythonExe
    if ($null -eq $exe) { return $false }
    try {
        if ($exe -is [string] -and $exe -eq "py") {
            & py -3.12 --version | Out-Host
        } else {
            & $exe --version | Out-Host
        }
        return $true
    } catch {
        return $false
    }
}

function Ensure-Python {
    Write-Step "Verificando Python"
    if (-not (Test-Python)) {
        Install-WithWinget -PackageId "Python.Python.3.12" -DisplayName "Python 3.12"
    }
    if (-not (Test-Python)) {
        throw "Python no quedo disponible. Instalar Python 3.12 manualmente y volver a correr."
    }
}

function Invoke-BasePython {
    param([string[]]$Arguments)
    $exe = Find-PythonExe
    if ($null -eq $exe) {
        throw "No se encontro Python 3.12 para crear el venv."
    }
    if ($exe -is [string] -and $exe -eq "py") {
        & py -3.12 @Arguments
    } else {
        & $exe @Arguments
    }
    Assert-Success "Python base"
}

function Invoke-VenvPython {
    param([string[]]$Arguments)
    $pythonExe = Join-Path $RepoDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $pythonExe)) { throw "No se encontro venv Python en $pythonExe" }
    & $pythonExe @Arguments
    Assert-Success "venv python"
}

function Remove-RepoArtifacts {
    param([string]$Dir)
    foreach ($name in @(".venv", ".env", "femag_demo.sqlite3")) {
        $path = Join-Path $Dir $name
        if (Test-Path $path) { Write-Info "Borrando $path"; Remove-Item -Recurse -Force $path }
    }
}

$PipNetworkOptions = @("--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org")

Write-Host ""
Write-Host "FEMAG Desktop - instalador demo Orden de carga" -ForegroundColor Green
Write-Host "Repo: $RepoUrl"
Write-Host "Rama: $Branch"
Write-Host "Parametros: Reset=$Reset SkipWinget=$SkipWinget SkipInstall=$SkipInstall SkipUi=$SkipUi SkipDemoSeed=$SkipDemoSeed SkipSmoke=$SkipSmoke"
Write-Host ""
Write-Host "Nota: si el repo es privado, esta PC necesita acceso a GitHub." -ForegroundColor Yellow

try {
    Ensure-Git
    Ensure-Python

    Write-Step "Preparando carpeta de instalacion"
    $RepoDir = if ($InstallDir) { $InstallDir } else { Join-Path $InstallRoot "femag_desktop" }
    $RepoParent = Split-Path -Parent $RepoDir
    New-Item -ItemType Directory -Force -Path $RepoParent | Out-Null

    if (-not (Test-Path $RepoDir)) {
        Write-Step "Clonando FEMAG Desktop"
        git clone --branch $Branch $RepoUrl $RepoDir
        Assert-Success "git clone"
    } else {
        Write-Step "Actualizando repo existente"
        Push-Location $RepoDir
        try {
            git fetch origin; Assert-Success "git fetch"
            git checkout $Branch; Assert-Success "git checkout"
            git pull --ff-only origin $Branch; Assert-Success "git pull"
        } finally { Pop-Location }
    }

    Push-Location $RepoDir
    try {
        if ($Reset) {
            Write-Step "Limpiando .venv, .env y femag_demo.sqlite3 (-Reset)"
            Remove-RepoArtifacts -Dir $RepoDir
        }

        if (-not $SkipInstall) {
            Write-Step "Creando entorno virtual .venv"
            if (-not (Test-Path ".venv")) { Invoke-BasePython -Arguments @("-m", "venv", ".venv") }
            Write-Step "Actualizando pip"
            Invoke-VenvPython -Arguments (@("-m", "pip", "install") + $PipNetworkOptions + @("--upgrade", "pip"))
            if (Test-Path "requirements.txt") {
                Write-Step "Instalando dependencias"
                Invoke-VenvPython -Arguments (@("-m", "pip", "install") + $PipNetworkOptions + @("-r", "requirements.txt"))
            }
        }

        Write-Step "Configurando base SQLite local de demo"
        $DemoDatabasePath = "femag_demo.sqlite3"
        $EnvFile = Join-Path $RepoDir ".env"
        [System.IO.File]::WriteAllLines($EnvFile, @(
            "FEMAG_DB_ENGINE=sqlite",
            "FEMAG_SQLITE_PATH=femag_demo.sqlite3",
            "FEMAG_DEMO=1"
        ), (New-Object System.Text.UTF8Encoding -ArgumentList $false))
        $env:FEMAG_ENV_FILE = $EnvFile

        if (Test-Path "scripts\init_db.py") {
            Write-Step "Inicializando schema FEMAG en SQLite demo"
            Invoke-VenvPython -Arguments @("scripts\init_db.py")
        }

        if (-not $SkipDemoSeed) {
            if (Test-Path "scripts\issue_73_integral_demo.py") {
                Write-Step "Generando demo integral Orden de carga"
                Invoke-VenvPython -Arguments @("scripts\issue_73_integral_demo.py", "--database-path", $DemoDatabasePath, "--evidence-dir", "docs\prints\issue_73_integral_demo")
            } else {
                Write-Warn "scripts\issue_73_integral_demo.py no encontrado en rama $Branch."
            }
        }

        if (-not $SkipSmoke) {
            Write-Step "Ejecutando smoke check"
            Invoke-VenvPython -Arguments @("-m", "app.main", "--smoke")
        }

        if (-not $SkipUi) {
            Write-Step "Abriendo FEMAG Desktop demo"
            Write-Host "En la ventana, mostrar: Maestros minimos, Ordenes de carga, emitir, Imprimir y anular." -ForegroundColor Yellow
            Invoke-VenvPython -Arguments @("-m", "app.main", "--demo-ui")
        }

        Write-Step "Demo preparada"
        Write-Host "Carpeta del repo: $RepoDir" -ForegroundColor Green
        Write-Host "Evidencia PDF: $(Join-Path $RepoDir 'docs\prints\issue_73_integral_demo')" -ForegroundColor Green
        Write-Host ""
        Write-Host "Para reabrir la UI sin reinstalar:" -ForegroundColor Yellow
        Write-Host "  cd `"$RepoDir`"" -ForegroundColor Yellow
        Write-Host "  .\.venv\Scripts\python.exe -m app.main --demo-ui" -ForegroundColor Yellow
    } finally { Pop-Location }

    exit 0
}
catch {
    Write-Host ""
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Si el problema es de red o permisos, volve a correr este script." -ForegroundColor Yellow
    exit 1
}
