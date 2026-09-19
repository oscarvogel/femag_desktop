param(
    [switch]$Reset
)

$ErrorActionPreference = "Stop"

$env:FEMAG_SECURE_CONFIG = "0"
$env:FEMAG_ENV_FILE = ".env.issue472-audit-demo-not-present"
$env:FEMAG_DEMO = "0"
$env:FEMAG_DB_ENGINE = "sqlite"
$env:FEMAG_SQLITE_PATH = "femag_audit_demo.sqlite3"
$env:WHATSAPP_ENABLED = "false"

$seedArgs = @("scripts/seed_issue_472_audit_demo.py")
if ($Reset) {
    $seedArgs += "--reset"
}

& py @seedArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Abriendo FEMAG contra femag_audit_demo.sqlite3"
Write-Host "Usuario: audit_demo"
Write-Host "Clave: demo"
Write-Host ""
Write-Host "Prueba sugerida:"
Write-Host "1. Abrir Ordenes de carga y revisar Historial de las tres OC AUDIT472."
Write-Host "2. En la OC EMITIDA_PARA_ANULAR, pulsar Anular."
Write-Host "3. Ingresar un motivo controlado, por ejemplo: Prueba manual auditoria #472."
Write-Host "4. Volver a Historial y verificar una sola fila Orden anulada con ese motivo."
Write-Host ""

& py -m app.main --ui
exit $LASTEXITCODE
