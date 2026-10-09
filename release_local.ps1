# Shim de compatibilidad: el flujo único vive en release.ps1.
# release_local.ps1 se conserva para no romper atajos existentes.
param(
    [ValidateSet("candidate")]
    [string]$Channel = "candidate"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Warning "release_local.ps1 está unificado en release.ps1. Delegando a: .\release.ps1 candidate -Local"
& (Join-Path $RepoRoot "release.ps1") candidate -Local
exit $LASTEXITCODE
