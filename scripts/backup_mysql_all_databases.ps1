# Dump diario de MySQL: un archivo .sql por base, sobrescribiendo el anterior.
#
# Este script se despliega SOLO en el servidor (por ejemplo C:\resguardo) y no
# necesita el repositorio ni la aplicacion. El motor de dump se detecta solo:
#
#   1. Si estan mysqldump y el cliente mysql, se usan: es el camino nativo y no
#      requiere Python ni PyMySQL en el servidor.
#   2. Si no, se busca Python con PyMySQL y se usa el exportador que vive en el
#      mismo directorio (backup_mysql_databases.py), que no necesita las
#      herramientas cliente de MySQL.
#
# Uso en el servidor:
#   1. Completar el bloque CONFIGURACION.
#   2. Ejecutar una vez:
#      .\backup_mysql_all_databases.ps1
#   3. Registrar la tarea diaria (requiere PowerShell como administrador):
#      .\backup_mysql_all_databases.ps1 -RegisterTask
#
# Con -DumpEngine se puede forzar el motor (auto, mysqldump o python). Por
# defecto el script lo detecta solo.
#
# Salida: <BackupDir>\<base>.sql  (se reemplaza en cada ejecucion)
# Log:    <BackupDir>\backup.log
# Manifiesto: <BackupDir>\manifest.json
#
# La contrasena nunca viaja en la linea de comandos: el motor nativo la recibe
# por MYSQL_PWD y el exportador Python por variable de entorno.
#
# No subir este archivo al repositorio con la clave cargada.

[CmdletBinding()]
param(
    [switch]$RegisterTask,
    [switch]$UnregisterTask,
    [string]$TaskName = "FEMAG - Dump MySQL diario",
    [string]$TaskTime = "12:00",
    [string]$PythonPath = "",
    [string]$MysqldumpPath = "",
    [string]$MysqlClientPath = "",
    [string]$DumpEngine = "",
    [string]$MysqlHost = "",
    [string]$MysqlPort = "",
    [string]$MysqlUser = "",
    [string]$MysqlPassword = "",
    [string]$BackupDir = "",
    [string[]]$ExcludeDatabases = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Los parametros explicitos pisan el bloque CONFIGURACION. Se los guarda antes
# de que el bloque los sobrescriba con los valores por defecto.
$Overrides = @{}
foreach ($key in $PSBoundParameters.Keys) {
    $Overrides[$key] = $PSBoundParameters[$key]
}

# =========================== CONFIGURACION ===========================
# Completar antes de ejecutar o registrar la tarea.
$MysqlHost = "127.0.0.1"
$MysqlPort = 3306
$MysqlUser = 'CAMBIAR_USUARIO'
$MysqlPassword = 'CAMBIAR_CLAVE'

# Carpeta donde queda un .sql por base (se sobrescribe siempre).
$BackupDir = "C:\FEMAG\backups\mysql"

# Bases a saltear ademas de las del sistema. Ejemplo: @("demo", "test")
$ExcludeDatabases = @()
# =====================================================================

foreach ($key in @("MysqlHost", "MysqlPort", "MysqlUser", "MysqlPassword", "BackupDir", "ExcludeDatabases", "DumpEngine")) {
    if ($Overrides.ContainsKey($key)) {
        Set-Variable -Name $key -Value $Overrides[$key]
    }
}

$ScriptDir = Split-Path -Parent $PSCommandPath
$DumpScript = Join-Path $ScriptDir "backup_mysql_databases.py"
$CurrentScript = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }

# La carpeta de destino se resuelve a una ruta absoluta ANTES de usarla. Una
# ruta relativa depende del directorio desde el que se lanza el script, y eso
# deja los respaldos en un nivel distinto al esperado segun como se ejecute
# (a mano, desde otra carpeta o desde la tarea programada).
if (-not [System.IO.Path]::IsPathRooted($BackupDir)) {
    $BackupDir = Join-Path $ScriptDir $BackupDir
}
$BackupDir = [System.IO.Path]::GetFullPath($BackupDir)

$LogFile = Join-Path $BackupDir "backup.log"
$ManifestFile = Join-Path $BackupDir "manifest.json"

# Bases del sistema que nunca se respaldan.
$SystemDatabases = @("information_schema", "mysql", "performance_schema", "sys")

function Resolve-Tool {
    <#
    .SYNOPSIS
        Busca una herramienta: la indicada, la del PATH o la de MySQL instalado.
    #>
    param(
        [string]$ExplicitPath,
        [string[]]$Names
    )

    if ($ExplicitPath) {
        if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Leaf)) {
            throw "No existe la herramienta indicada: $ExplicitPath"
        }
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }

    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) {
            return $command.Source
        }
    }

    # MySQL Server y MySQL Client instalan las herramientas en el mismo bin.
    $roots = @(
        "C:\Program Files\MySQL",
        "C:\Program Files (x86)\MySQL",
        "C:\Program Files\MariaDB",
        "C:\xampp\mysql\bin"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }
        $directories = @($root)
        $directories += @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            Join-Path $_.FullName "bin"
        })
        foreach ($directory in $directories) {
            foreach ($name in $Names) {
                $candidate = Join-Path $directory $name
                if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                    return $candidate
                }
            }
        }
    }

    return $null
}

function Resolve-DumpEngine {
    <#
    .SYNOPSIS
        Elige el motor de dump: el nativo (mysqldump) si esta, si no Python.
    .DESCRIPTION
        El motor nativo no necesita Python ni PyMySQL en el servidor. El
        exportador Python es el respaldo para equipos donde no esta instalado
        MySQL Client.

        Con -DumpEngine se puede forzar uno de los dos motores. Por defecto
        (auto) la decision es del script.
    #>
    $requested = if ($DumpEngine) { "$DumpEngine".ToLower() } else { "auto" }
    if ($requested -notin @("auto", "mysqldump", "python")) {
        throw "Motor de dump invalido: $DumpEngine. Use auto, mysqldump o python."
    }

    if ($requested -ne "python") {
        $dump = Resolve-Tool -ExplicitPath $MysqldumpPath -Names @("mysqldump.exe", "mysqldump", "mariadb-dump.exe", "mariadb-dump")
        if ($dump) {
            $client = Resolve-Tool -ExplicitPath $MysqlClientPath -Names @("mysql.exe", "mysql", "mariadb.exe", "mariadb")
            if ($client) {
                return @{ Kind = "mysqldump"; Dump = $dump; Client = $client }
            }
            Write-Host "Se encontro mysqldump pero no el cliente mysql: no se pueden enumerar las bases." -ForegroundColor Yellow
        }
        elseif ($requested -eq "mysqldump") {
            throw "Se pidio el motor mysqldump pero no esta instalado en este equipo."
        }
    }

    if (-not (Test-Path -LiteralPath $DumpScript -PathType Leaf)) {
        throw "No se encontro mysqldump ni el script de dump: $DumpScript"
    }
    $python = Resolve-Python
    return @{ Kind = "python"; Python = $python }
}

function Resolve-Python {
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
            throw "No existe el Python indicado: $PythonPath"
        }
        return (Resolve-Path -LiteralPath $PythonPath).Path
    }
    foreach ($candidate in @("python.exe", "python", "py.exe")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) {
            return $command.Source
        }
    }
    throw "No se encontro Python. Indique -PythonPath con la ruta a python.exe."
}

function ConvertTo-NativeArgument {
    <#
    .SYNOPSIS
        Prepara un argumento para la linea de comandos de un proceso nativo.
    .DESCRIPTION
        Start-Process junta los argumentos con espacios y no los entrecomilla:
        un camino con espacios se parte en dos. Este helper entrecomilla lo que
        haga falta, que es lo que el parser de la linea de comandos espera.
    #>
    param([string]$Value)

    if ($null -eq $Value) {
        return '""'
    }
    if ($Value -notmatch '[\s"]') {
        return $Value
    }
    $escaped = $Value -replace '(\\*)"', '$1$1\"'
    $escaped = $escaped -replace '(\\+)$', '$1$1'
    return '"' + $escaped + '"'
}

function Invoke-NativeTool {
    <#
    .SYNOPSIS
        Ejecuta una herramienta y devuelve su codigo de salida.
    .DESCRIPTION
        stdout y stderr van a archivos separados con Start-Process, que no los
        mezcla ni los decora. Con 2>&1 y ErrorActionPreference = "Stop", la
        primera linea de stderr se convierte en excepcion terminante y el resto
        del mensaje se pierde: el log quedaba con una sola linea y sin poder
        saber que paso.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$StdOutFile,
        [string]$StdErrFile
    )

    $commandLine = ($Arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' '
    $parameters = @{
        FilePath = $FilePath
        ArgumentList = $commandLine
        NoNewWindow = $true
        Wait = $true
        PassThru = $true
    }
    if ($StdOutFile) {
        $parameters["RedirectStandardOutput"] = $StdOutFile
    }
    if ($StdErrFile) {
        $parameters["RedirectStandardError"] = $StdErrFile
    }

    $process = Start-Process @parameters
    return $process.ExitCode
}

function Write-BackupLog {
    param(
        [string[]]$Lines,
        [string]$Prefix = ""
    )

    foreach ($line in $Lines) {
        if ($null -eq $line) {
            continue
        }
        $text = "$line"
        if ($text.Trim().Length -eq 0) {
            continue
        }
        Write-Host $text
        Add-Content -LiteralPath $LogFile -Value ($Prefix + $text) -Encoding UTF8
    }
}

function Get-AccessibleDatabases {
    <#
    .SYNOPSIS
        Lista las bases visibles para el usuario MySQL configurado.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$ClientPath
    )

    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()
    try {
        $arguments = @(
            "--host=$MysqlHost",
            "--port=$MysqlPort",
            "--user=$MysqlUser",
            "--batch",
            "--skip-column-names",
            "--execute=SHOW DATABASES"
        )
        $exitCode = Invoke-NativeTool -FilePath $ClientPath -Arguments $arguments `
            -StdOutFile $stdoutFile -StdErrFile $stderrFile
        if ($exitCode -ne 0) {
            $error = (Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue)
            throw "No se pudieron listar las bases (exit=$exitCode): $error"
        }
        $names = @()
        foreach ($line in (Get-Content -LiteralPath $stdoutFile -ErrorAction SilentlyContinue)) {
            $name = $line.Trim()
            if ($name.Length -gt 0) {
                $names += $name
            }
        }
        return $names
    }
    finally {
        Remove-Item -LiteralPath $stdoutFile, $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function ConvertTo-SafeDatabaseName {
    <#
    .SYNOPSIS
        Nombre de archivo portable y determinista, sin cambiar el nombre real.
    #>
    param([string]$Database)

    $safe = $Database -replace '[^A-Za-z0-9._-]+', '_'
    $safe = $safe.Trim('.', '_')
    if ($safe.Length -eq 0) {
        return "database"
    }
    return $safe
}

function Invoke-NativeDump {
    <#
    .SYNOPSIS
        Dump por base con mysqldump y manifiesto.
    #>
    param(
        [Parameter(Mandatory = $true)][hashtable]$Engine
    )

    # MYSQL_PWD es la via que usan el cliente mysql y mysqldump para leer la
    # clave sin que viaje en la linea de comandos.
    $env:MYSQL_PWD = $MysqlPassword

    $databases = @(Get-AccessibleDatabases -ClientPath $Engine.Client)
    $excluded = @($ExcludeDatabases | ForEach-Object { "$_".ToLower() })
    $targets = @($databases | Where-Object {
        $name = "$_"
        ($SystemDatabases -notcontains $name.ToLower()) -and ($excluded -notcontains $name.ToLower())
    } | Sort-Object)

    if ($targets.Count -eq 0) {
        throw "No hay bases de datos de usuario accesibles para respaldar."
    }

    $results = @()
    foreach ($database in $targets) {
        $destination = Join-Path $BackupDir ((ConvertTo-SafeDatabaseName $database) + ".sql")
        $temporary = $destination + ".tmp"
        $stdoutFile = [System.IO.Path]::GetTempFileName()
        $stderrFile = [System.IO.Path]::GetTempFileName()
        try {
            $arguments = @(
                "--host=$MysqlHost",
                "--port=$MysqlPort",
                "--user=$MysqlUser",
                "--single-transaction",
                "--routines",
                "--events",
                "--triggers",
                "--databases", $database
            )
            $exitCode = Invoke-NativeTool -FilePath $Engine.Dump -Arguments $arguments `
                -StdOutFile $stdoutFile -StdErrFile $stderrFile
            $errors = @(Get-Content -LiteralPath $stderrFile -ErrorAction SilentlyContinue)
            $produced = Get-Item -LiteralPath $stdoutFile -ErrorAction SilentlyContinue
            if ($exitCode -eq 0 -and $produced -and $produced.Length -gt 0) {
                # Se publica por reemplazo: un dump fallido no deja un archivo
                # a medias que alguien pueda restaurar por error.
                Move-Item -LiteralPath $stdoutFile -Destination $destination -Force
                $size = [math]::Round($produced.Length / 1MB, 2)
                $results += @{ database = $database; file_path = $destination; status = "success"; message = $null }
                Write-BackupLog -Lines @("OK $database -> $destination ($size MB)")
            }
            elseif ($exitCode -eq 0) {
                # Salio bien pero sin contenido: un .sql de 0 bytes no es un
                # respaldo. No se publica, y el respaldo anterior queda intacto.
                $message = "el dump salio vacio: no se publico nada para esta base"
                $results += @{ database = $database; file_path = $null; status = "error"; message = $message }
                Write-BackupLog -Lines @("ERROR $database : $message")
            }
            else {
                $message = ($errors -join " ").Trim()
                if (-not $message) { $message = "mysqldump finalizo con codigo $exitCode" }
                $results += @{ database = $database; file_path = $null; status = "error"; message = $message }
                Write-BackupLog -Lines @("ERROR $database : $message")
            }
        }
        finally {
            Remove-Item -LiteralPath $stdoutFile, $stderrFile -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Manifest -Results $results
    Remove-Item Env:\MYSQL_PWD -ErrorAction SilentlyContinue
    return $results
}

function Invoke-PythonDump {
    <#
    .SYNOPSIS
        Dump por base con el exportador Python y manifiesto.
    #>
    param(
        [Parameter(Mandatory = $true)][hashtable]$Engine
    )

    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()
    try {
        $arguments = @(
            $DumpScript,
            "--host", $MysqlHost,
            "--port", [string]$MysqlPort,
            "--backup-dir", $BackupDir,
            "--dump-engine", "python",
            "--overwrite"
        )
        foreach ($database in $ExcludeDatabases) {
            if ($database) {
                $arguments += @("--exclude-database", $database)
            }
        }

        $env:MYSQL_HOST = $MysqlHost
        $env:MYSQL_PORT = [string]$MysqlPort
        $env:MYSQL_USER = $MysqlUser
        $env:MYSQL_PASSWORD = $MysqlPassword
        $env:PYTHONIOENCODING = "utf-8"

        $exitCode = Invoke-NativeTool -FilePath $Engine.Python -Arguments $arguments `
            -StdOutFile $stdoutFile -StdErrFile $stderrFile

        Write-BackupLog -Lines @(Get-Content -LiteralPath $stdoutFile -ErrorAction SilentlyContinue)
        Write-BackupLog -Lines @(Get-Content -LiteralPath $stderrFile -ErrorAction SilentlyContinue)

        # Un .sql de 0 bytes no es un respaldo: el exportador publica por
        # reemplazo, asi que un vacio delata una corrida que no sirvio.
        $vacios = @(Get-ChildItem -LiteralPath $BackupDir -Filter "*.sql" -ErrorAction SilentlyContinue |
            Where-Object { $_.Length -eq 0 })
        foreach ($vacio in $vacios) {
            Write-BackupLog -Lines @("ERROR $($vacio.BaseName) : el dump salio vacio ($($vacio.FullName))")
            $exitCode = 1
        }

        return $exitCode
    }
    finally {
        Remove-Item -LiteralPath $stdoutFile, $stderrFile -Force -ErrorAction SilentlyContinue
        Remove-Item Env:\MYSQL_HOST, Env:\MYSQL_PORT, Env:\MYSQL_USER, Env:\MYSQL_PASSWORD -ErrorAction SilentlyContinue
    }
}

function Write-Manifest {
    <#
    .SYNOPSIS
        Manifiesto del dump: que base se respaldo, donde y con que resultado.
    #>
    param(
        [Parameter(Mandatory = $true)][object[]]$Results
    )

    $manifest = @{
        created_at = (Get-Date).ToString("o")
        databases = @($Results | ForEach-Object {
            @{
                database = $_.database
                file_path = $_.file_path
                status = $_.status
                message = $_.message
            }
        })
    }
    $json = $manifest | ConvertTo-Json -Depth 4
    Set-Content -LiteralPath $ManifestFile -Value $json -Encoding UTF8
}

function Register-DailyTask {
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$CurrentScript`""
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $ScriptDir
    $trigger = New-ScheduledTaskTrigger -Daily -At $TaskTime
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Host "Tarea '$TaskName' registrada todos los dias a las $TaskTime (SYSTEM)." -ForegroundColor Green
}

if ($UnregisterTask) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tarea '$TaskName' eliminada." -ForegroundColor Yellow
    exit 0
}

if ($MysqlUser -eq "CAMBIAR_USUARIO" -or $MysqlPassword -eq "CAMBIAR_CLAVE") {
    throw "Complete `$MysqlUser y `$MysqlPassword en el bloque CONFIGURACION."
}

if ($RegisterTask) {
    Register-DailyTask
    exit 0
}

New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

$timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$header = "[$timestamp] Inicio dump MySQL en $BackupDir"
Add-Content -LiteralPath $LogFile -Value $header -Encoding UTF8
Write-Host $header

$engine = Resolve-DumpEngine
Write-Host "Motor de dump: $($engine.Kind)"

if ($engine.Kind -eq "mysqldump") {
    $results = @(Invoke-NativeDump -Engine $engine)
    $failed = @($results | Where-Object { $_.status -ne "success" })
    $exitCode = if ($failed.Count -eq 0) { 0 } else { 1 }
}
else {
    $exitCode = Invoke-PythonDump -Engine $engine
}

# Resumen: que quedo respaldado de verdad, con el tamano en disco. Es lo que
# hay que mirar para saber si el ultimo respaldo sirve.
$publicados = @(Get-ChildItem -LiteralPath $BackupDir -Filter "*.sql" -ErrorAction SilentlyContinue |
    Sort-Object Name)
foreach ($publicado in $publicados) {
    Write-BackupLog -Lines @("Archivo $($publicado.FullName) ($([math]::Round($publicado.Length / 1MB, 2)) MB)")
}

$footer = "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] Fin (exit=$exitCode)"
Add-Content -LiteralPath $LogFile -Value $footer -Encoding UTF8
Write-Host $footer

exit $exitCode
