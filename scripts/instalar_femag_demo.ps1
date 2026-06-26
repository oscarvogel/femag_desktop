param(
    [string]$InstallRoot = "$env:USERPROFILE\FEMAG",
    [string]$RepoUrl = "https://github.com/oscarvogel/femag_desktop.git",
    [string]$Branch = "main",
    [switch]$SkipWinget,
    [switch]$SkipUi
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Info {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor Gray
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Install-WithWinget {
    param(
        [string]$PackageId,
        [string]$DisplayName
    )
    if ($SkipWinget) {
        throw "$DisplayName no esta instalado y se pidio omitir winget."
    }
    if (-not (Test-Command "winget")) {
        throw "$DisplayName no esta instalado y winget no esta disponible. Instalar $DisplayName manualmente y volver a ejecutar."
    }
    Write-Info "Intentando instalar $DisplayName con winget..."
    winget install --id $PackageId --exact --source winget --accept-source-agreements --accept-package-agreements
}

function Ensure-Git {
    Write-Step "Verificando Git"
    if (-not (Test-Command "git")) {
        Install-WithWinget -PackageId "Git.Git" -DisplayName "Git"
    }
    if (-not (Test-Command "git")) {
        throw "Git no quedo disponible en PATH. Cerrar y abrir PowerShell, o instalar Git manualmente."
    }
    git --version
}

function Test-Python {
    if (Test-Command "py") {
        try {
            py -3.12 --version | Out-Host
            return $true
        } catch {
            return $false
        }
    }
    if (Test-Command "python") {
        try {
            python --version | Out-Host
            return $true
        } catch {
            return $false
        }
    }
    return $false
}

function Ensure-Python {
    Write-Step "Verificando Python"
    if (-not (Test-Python)) {
        Install-WithWinget -PackageId "Python.Python.3.12" -DisplayName "Python 3.12"
    }
    if (-not (Test-Python)) {
        throw "Python no quedo disponible en PATH. Cerrar y abrir PowerShell, o instalar Python 3.12 manualmente."
    }
}

function Invoke-BasePython {
    param([string[]]$Arguments)
    if (Test-Command "py") {
        & py -3.12 @Arguments
        return
    }
    & python @Arguments
}

function Invoke-VenvPython {
    param([string[]]$Arguments)
    $pythonExe = Join-Path $RepoDir ".venv\Scripts\python.exe"
    & $pythonExe @Arguments
}

Write-Host "FEMAG Desktop - instalador demo Orden de carga" -ForegroundColor Green
Write-Host "Repo: $RepoUrl"
Write-Host "Rama: $Branch"
Write-Host ""
Write-Host "Nota: si el repo es privado, esta PC necesita acceso/autenticacion a GitHub." -ForegroundColor Yellow

Ensure-Git
Ensure-Python

Write-Step "Preparando carpeta de instalacion"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$RepoDir = Join-Path $InstallRoot "femag_desktop"

if (-not (Test-Path $RepoDir)) {
    Write-Step "Clonando FEMAG Desktop"
    git clone --branch $Branch $RepoUrl $RepoDir
} else {
    Write-Step "Actualizando repo existente"
    Push-Location $RepoDir
    try {
        git fetch origin
        git checkout $Branch
        git pull --ff-only origin $Branch
    } finally {
        Pop-Location
    }
}

Push-Location $RepoDir
try {
    Write-Step "Creando entorno virtual .venv"
    if (-not (Test-Path ".venv")) {
        Invoke-BasePython -Arguments @("-m", "venv", ".venv")
    }

    Write-Step "Actualizando pip"
    Invoke-VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")

    if (Test-Path "requirements.txt") {
        Write-Step "Instalando dependencias"
        Invoke-VenvPython -Arguments @("-m", "pip", "install", "-r", "requirements.txt")
    } else {
        Write-Info "No se encontro requirements.txt; se omite instalacion de dependencias."
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
    Write-Info "Demo configurada para usar SQLite local: $DemoDatabasePath"

    if (Test-Path "scripts\init_db.py") {
        Write-Step "Inicializando schema FEMAG en SQLite demo"
        Invoke-VenvPython -Arguments @("scripts\init_db.py")
    } else {
        Write-Info "No se encontro scripts\init_db.py; se omite inicializacion."
    }

    if (Test-Path "scripts\issue_73_integral_demo.py") {
        Write-Step "Generando demo integral Orden de carga"
        Invoke-VenvPython -Arguments @(
            "scripts\issue_73_integral_demo.py",
            "--database-path", $DemoDatabasePath,
            "--evidence-dir", "docs\prints\issue_73_integral_demo"
        )
    } else {
        throw "No se encontro scripts\issue_73_integral_demo.py en la rama $Branch."
    }

    Write-Step "Ejecutando smoke check"
    Invoke-VenvPython -Arguments @("-m", "app.main", "--smoke")

    if ($SkipUi) {
        Write-Step "Demo UI omitida por parametro -SkipUi"
    } else {
        Write-Step "Abriendo FEMAG Desktop demo"
        Write-Host "En la ventana, mostrar: Maestros minimos, Ordenes de carga, emitir, imprimir/reimprimir y anular." -ForegroundColor Yellow
        Invoke-VenvPython -Arguments @("-m", "app.main", "--demo-ui")
    }

    Write-Step "Demo preparada"
    Write-Host "Carpeta del repo: $RepoDir" -ForegroundColor Green
    Write-Host "Evidencia HTML: $(Join-Path $RepoDir 'docs\prints\issue_73_integral_demo')" -ForegroundColor Green
} finally {
    Pop-Location
}
