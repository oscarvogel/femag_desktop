# Helper compartido para ejecutar comandos nativos (python, pip, pytest,
# PyInstaller, ISCC.exe, ...) de forma segura en Windows PowerShell 5.1 y 7.
#
# Problema que resuelve: con $ErrorActionPreference = "Stop", PowerShell 5.1
# convierte el stderr de un comando nativo en error terminante cuando la
# salida está redirigida (logs a archivo, captura del runner, etc.).
# Herramientas normales como pip o PyInstaller escriben progreso en stderr,
# lo que abortaba builds perfectamente válidos solo en ejecución local.
#
# Uso:
#   . "$PSScriptRoot\Invoke-Native.ps1"
#   Invoke-Native -Command $Python -Arguments @('-m', 'pytest', '-q') `
#       -FailureMessage 'Los tests fallaron.'

function Invoke-Native {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    $previousEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command @Arguments 2>&1 | ForEach-Object { Write-Host "$_" }
    } finally {
        $ErrorActionPreference = $previousEAP
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit=$LASTEXITCODE)"
    }
}

# Variante que captura la salida (para git/gh cuyo stdout se procesa).
# También neutraliza el stderr bajo PowerShell 5.1 + redirección.
function Invoke-Capture {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    $previousEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Command @Arguments 2>&1 | ForEach-Object { "$_" }
    } finally {
        $ErrorActionPreference = $previousEAP
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit=$LASTEXITCODE)"
    }
    return ($output -join "`n").Trim()
}
