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
    Write-Host "  -CreateDatabase              Crea la base MySQL y el usuario definidos en .env usando PyMySQL"
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

function Invoke-MySqlAdminSql {
    param(
        [string]$PythonExe,
        [hashtable]$Env
    )

    $adminScript = @'
import os
import pymysql


def quote_identifier(value):
    return "`" + value.replace("`", "``") + "`"


host = os.environ["FEMAG_DB_HOST"]
port = int(os.environ["FEMAG_DB_PORT"])
admin_user = os.environ["FEMAG_MYSQL_ADMIN_USER"]
admin_password = os.environ["FEMAG_MYSQL_ADMIN_PASSWORD"]
db_name = os.environ["FEMAG_DB_NAME"]
db_user = os.environ["FEMAG_DB_USER"]
db_password = os.environ["FEMAG_DB_PASSWORD"]
same_admin_and_app_user = db_user.lower() == admin_user.lower()

conn = pymysql.connect(
    host=host,
    port=port,
    user=admin_user,
    password=admin_password,
    autocommit=True,
    charset="utf8mb4",
)

try:
    with conn.cursor() as cursor:
        escaped_db_password = conn.escape_string(db_password)
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS {quote_identifier(db_name)} "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        if same_admin_and_app_user:
            print(
                "DB_USER coincide con el usuario admin de MySQL; "
                "omito CREATE USER/GRANT para evitar tocar cuentas administrativas."
            )
            raise SystemExit(0)
        for host_pattern in ("%", "localhost"):
            escaped_host = conn.escape_string(host_pattern)
            escaped_user = conn.escape_string(db_user)
            cursor.execute(
                f"CREATE USER IF NOT EXISTS '{escaped_user}'@'{escaped_host}' "
                f"IDENTIFIED BY '{escaped_db_password}'"
            )
            cursor.execute(
                f"GRANT ALL PRIVILEGES ON {quote_identifier(db_name)}.* "
                f"TO '{escaped_user}'@'{escaped_host}'"
            )
        cursor.execute("FLUSH PRIVILEGES")
finally:
    conn.close()
'@
    $adminFile = Join-Path $env:TEMP "femag_prepare_db.py"
    Set-Content -LiteralPath $adminFile -Value $adminScript -Encoding UTF8

    $oldDbHost = [Environment]::GetEnvironmentVariable("FEMAG_DB_HOST", "Process")
    $oldDbPort = [Environment]::GetEnvironmentVariable("FEMAG_DB_PORT", "Process")
    $oldDbName = [Environment]::GetEnvironmentVariable("FEMAG_DB_NAME", "Process")
    $oldDbUser = [Environment]::GetEnvironmentVariable("FEMAG_DB_USER", "Process")
    $oldDbPassword = [Environment]::GetEnvironmentVariable("FEMAG_DB_PASSWORD", "Process")
    $oldAdminUser = [Environment]::GetEnvironmentVariable("FEMAG_MYSQL_ADMIN_USER", "Process")
    $oldAdminPassword = [Environment]::GetEnvironmentVariable("FEMAG_MYSQL_ADMIN_PASSWORD", "Process")

    $env:FEMAG_DB_HOST = $Env["DB_HOST"]
    $env:FEMAG_DB_PORT = $Env["DB_PORT"]
    $env:FEMAG_DB_NAME = $Env["DB_NAME"]
    $env:FEMAG_DB_USER = $Env["DB_USER"]
    $env:FEMAG_DB_PASSWORD = $Env["DB_PASSWORD"]
    $env:FEMAG_MYSQL_ADMIN_USER = $MysqlAdminUser
    $env:FEMAG_MYSQL_ADMIN_PASSWORD = $MysqlAdminPassword

    & $PythonExe $adminFile
    $exitCode = $LASTEXITCODE
    Remove-Item -LiteralPath $adminFile -Force

    $env:FEMAG_DB_HOST = $oldDbHost
    $env:FEMAG_DB_PORT = $oldDbPort
    $env:FEMAG_DB_NAME = $oldDbName
    $env:FEMAG_DB_USER = $oldDbUser
    $env:FEMAG_DB_PASSWORD = $oldDbPassword
    $env:FEMAG_MYSQL_ADMIN_USER = $oldAdminUser
    $env:FEMAG_MYSQL_ADMIN_PASSWORD = $oldAdminPassword

    if ($exitCode -ne 0) {
        throw "Fallo PyMySQL al preparar la base."
    }
}

function Test-FemagDatabaseConnection {
    param([string]$PythonExe)

    $checkScript = @"
from app.config.database import initialize_runtime_database

try:
    db = initialize_runtime_database()
    db.connect(reuse_if_open=True)
    db.close()
except Exception as exc:
    print(exc)
    raise SystemExit(1)
"@
    $checkFile = Join-Path $env:TEMP "femag_check_db.py"
    Set-Content -LiteralPath $checkFile -Value $checkScript -Encoding UTF8
    $output = & $PythonExe $checkFile 2>&1
    $exitCode = $LASTEXITCODE
    Remove-Item -LiteralPath $checkFile -Force

    if ($exitCode -ne 0) {
        Write-Host ""
        Write-Host "No pude conectar a MySQL con los datos de .env:"
        Write-Host "  DB_HOST=$($envValues["DB_HOST"])"
        Write-Host "  DB_PORT=$($envValues["DB_PORT"])"
        Write-Host "  DB_NAME=$($envValues["DB_NAME"])"
        Write-Host "  DB_USER=$($envValues["DB_USER"])"
        if ($envValues["DB_PASSWORD"] -eq "") {
            Write-Host "  DB_PASSWORD=(vacio)"
            Write-Host ""
            Write-Host "MySQL rechazo al usuario sin clave. Edita .env y completa DB_PASSWORD,"
            Write-Host "o ejecuta el script con -CreateDatabase usando un usuario admin de MySQL:"
            Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\iniciar_dev.ps1 -CreateDatabase -MysqlAdminUser root -MysqlAdminPassword TU_CLAVE"
        } else {
            Write-Host "  DB_PASSWORD=(configurado)"
            Write-Host ""
            Write-Host "Revisa que la base exista y que el usuario tenga permisos."
        }
        Write-Host ""
        Write-Host "Detalle MySQL:"
        Write-Host "  $output"
        throw "No se pudo conectar a la base FEMAG."
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
    Write-Host "Preparando base MySQL $dbName..."
    Invoke-MySqlAdminSql -PythonExe $venvPython -Env $envValues
}

Write-Host "Inicializando tablas y seed..."
Test-FemagDatabaseConnection $venvPython
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
