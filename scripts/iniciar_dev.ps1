param(
    [switch]$SkipInstall,
    [switch]$SkipTests,
    [switch]$CreateDatabase,
    [string]$MysqlAdminUser = "root",
    [string]$MysqlAdminPassword = "",
    [string]$AdminUser = "admin",
    [string]$AdminPassword = "",
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Show-Help {
    Write-Host ""
    Write-Host "Uso:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\iniciar_dev.ps1"
    Write-Host ""
    Write-Host "Opciones utiles:"
    Write-Host "  -CreateDatabase              Crea la base MySQL y el usuario definidos en .env usando mysql.exe"
    Write-Host "  -MysqlAdminUser root          Usuario admin de MySQL para crear DB/usuario"
    Write-Host "  -MysqlAdminPassword clave     Clave admin de MySQL"
    Write-Host "  -AdminPassword clave          Crea el usuario FEMAG admin si no existe"
    Write-Host "  -SkipInstall                  No reinstala requirements.txt"
    Write-Host "  -SkipTests                    No ejecuta smoke/compileall al final"
    Write-Host ""
}

function Read-EnvFile {
    param([string]$Path)
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $values
    }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -eq 2) {
            $values[$parts[0].Trim()] = $parts[1].Trim()
        }
    }
    return $values
}

function Find-Python {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($python) {
        return @("py", "-3")
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @("python")
    }
    throw "No encontre Python. Instala Python 3 y volve a ejecutar este script."
}

function Invoke-Python {
    param(
        [string]$PythonExe,
        [string[]]$Arguments
    )
    & $PythonExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo Python: $PythonExe $($Arguments -join ' ')"
    }
}

function Invoke-Mysql {
    param(
        [string]$Sql,
        [hashtable]$Env
    )
    $mysql = Get-Command mysql -ErrorAction SilentlyContinue
    if (-not $mysql) {
        throw "No encontre mysql.exe en PATH. Instala el cliente MySQL o crea la base manualmente."
    }

    $args = @(
        "-h", $Env["DB_HOST"],
        "-P", $Env["DB_PORT"],
        "-u", $MysqlAdminUser
    )
    if ($MysqlAdminPassword -ne "") {
        $args += "-p$MysqlAdminPassword"
    }
    $args += "-e"
    $args += $Sql

    & $mysql.Source @args
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo mysql.exe al preparar la base."
    }
}

if ($Help) {
    Show-Help
    exit 0
}

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $projectRoot
$previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
if ($previousPythonPath) {
    $env:PYTHONPATH = "$projectRoot;$previousPythonPath"
} else {
    $env:PYTHONPATH = "$projectRoot"
}

Write-Host "== FEMAG Desktop dev =="
Write-Host "Proyecto: $projectRoot"

if (-not (Test-Path -LiteralPath ".env")) {
    if (-not (Test-Path -LiteralPath ".env.example")) {
        throw "No existe .env ni .env.example."
    }
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Cree .env desde .env.example. Revisalo si tus credenciales MySQL son distintas."
}

$envValues = Read-EnvFile ".env"
foreach ($required in @("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER")) {
    if (-not $envValues.ContainsKey($required) -or $envValues[$required] -eq "") {
        throw "Falta $required en .env"
    }
}
if (-not $envValues.ContainsKey("DB_PASSWORD")) {
    $envValues["DB_PASSWORD"] = ""
}

$venvDir = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    $pythonCommand = Find-Python
    Write-Host "Creando entorno virtual en .venv..."
    $pythonArgs = @()
    if ($pythonCommand.Count -gt 1) {
        $pythonArgs = $pythonCommand[1..($pythonCommand.Count - 1)]
    }
    & $pythonCommand[0] @pythonArgs -m venv ".venv"
    if ($LASTEXITCODE -ne 0) {
        throw "No pude crear el entorno virtual."
    }
}

if (-not $SkipInstall) {
    Write-Host "Instalando dependencias..."
    Invoke-Python $venvPython @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Python $venvPython @("-m", "pip", "install", "-r", "requirements.txt")
}

if ($CreateDatabase) {
    $dbName = $envValues["DB_NAME"]
    $dbUser = $envValues["DB_USER"]
    $dbPassword = $envValues["DB_PASSWORD"]
    $sql = @"
CREATE DATABASE IF NOT EXISTS ``$dbName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$dbUser'@'%' IDENTIFIED BY '$dbPassword';
CREATE USER IF NOT EXISTS '$dbUser'@'localhost' IDENTIFIED BY '$dbPassword';
GRANT ALL PRIVILEGES ON ``$dbName``.* TO '$dbUser'@'%';
GRANT ALL PRIVILEGES ON ``$dbName``.* TO '$dbUser'@'localhost';
FLUSH PRIVILEGES;
"@
    Write-Host "Preparando base MySQL $dbName..."
    Invoke-Mysql -Sql $sql -Env $envValues
}

Write-Host "Inicializando tablas y seed..."
Invoke-Python $venvPython @("scripts/init_db.py")

if ($AdminPassword -ne "") {
    $checkUser = @"
from app.config.database import initialize_runtime_database
from app.models.security import User
db = initialize_runtime_database()
db.connect(reuse_if_open=True)
raise SystemExit(0 if User.get_or_none(User.username == "$AdminUser") else 1)
"@
    $checkFile = Join-Path $env:TEMP "femag_check_admin.py"
    Set-Content -LiteralPath $checkFile -Value $checkUser -Encoding UTF8
    & $venvPython $checkFile
    $adminExists = $LASTEXITCODE -eq 0
    Remove-Item -LiteralPath $checkFile -Force
    if ($adminExists) {
        Write-Host "Usuario FEMAG '$AdminUser' ya existe."
    } else {
        Write-Host "Creando usuario FEMAG '$AdminUser'..."
        Invoke-Python $venvPython @("scripts/create_admin_user.py", $AdminUser, $AdminPassword)
    }
}

if (-not $SkipTests) {
    Write-Host "Validando imports y smoke..."
    Invoke-Python $venvPython @("-m", "compileall", "app")
    Invoke-Python $venvPython @("-m", "app.main", "--smoke")
}

Write-Host ""
Write-Host "Listo. Para iniciar FEMAG Desktop:"
Write-Host "  .\.venv\Scripts\python.exe -m app.main"
Write-Host ""
