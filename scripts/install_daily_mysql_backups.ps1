[CmdletBinding()]
param(
    [string]$PythonPath = "python",
    [string]$MysqldumpPath = "mysqldump",
    [ValidateSet("auto", "mysqldump", "python")]
    [string]$DumpEngine = "auto",
    [string]$BackupDirectory = (Join-Path $env:LOCALAPPDATA "FEMAG Desktop\backups\mysql"),
    [string]$TaskName = "FEMAG - Backup MySQL diario",
    [switch]$Force
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$backupScript = Join-Path $PSScriptRoot "backup_mysql_databases.py"

if (-not (Test-Path -LiteralPath $backupScript -PathType Leaf)) {
    throw "No se encontro el script de backup: $backupScript"
}
if (-not (Get-Command $PythonPath -ErrorAction SilentlyContinue)) {
    throw "No se encontro Python en '$PythonPath'. Indique -PythonPath con la ruta a python.exe."
}
if ((Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) -and -not $Force) {
    throw "La tarea '$TaskName' ya existe. Use -Force para actualizarla."
}

$arguments = '"{0}" --backup-dir "{1}" --dump-engine "{2}" --mysqldump "{3}"' -f `
    $backupScript, $BackupDirectory, $DumpEngine, $MysqldumpPath
$action = New-ScheduledTaskAction -Execute $PythonPath -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At 12:00PM
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal `
    -Description "Dump MySQL diario por base de datos para FEMAG."

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Write-Host "Tarea '$TaskName' instalada para todos los dias a las 12:00."
Write-Host "Se ejecuta como $currentUser y requiere que ese usuario tenga sesion iniciada."
