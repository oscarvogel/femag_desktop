param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("candidate", "production")]
    [string]$Channel
)

$ErrorActionPreference = "Stop"
$repo = "oscarvogel/femag_desktop"

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "No se encontro '$Name' en PATH."
    }
}

function Wait-And-WatchRun([string]$Workflow, [string]$Branch) {
    Write-Host ""
    Write-Host "Buscando ejecucion de $Workflow en $Branch..." -ForegroundColor Cyan
    $runId = $null
    for ($i = 0; $i -lt 20 -and -not $runId; $i++) {
        Start-Sleep -Seconds 2
        $json = gh run list --repo $repo --workflow $Workflow --branch $Branch --limit 1 --json databaseId,status,conclusion,createdAt | ConvertFrom-Json
        if ($json -and $json.Count -gt 0) { $runId = $json[0].databaseId }
    }
    if (-not $runId) { throw "No se encontro la ejecucion recien lanzada." }
    Write-Host "Run: $runId" -ForegroundColor Green
    gh run watch $runId --repo $repo --exit-status
    if ($LASTEXITCODE -ne 0) { throw "El workflow termino con error." }
    Write-Host ""
    gh run view $runId --repo $repo
}

Require-Command "gh"
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { throw "GitHub CLI no esta autenticado. Ejecute: gh auth login" }

if ($Channel -eq "candidate") {
    Require-Command "git"
    $branch = (git branch --show-current).Trim()
    if (-not $branch) { throw "No se pudo determinar la rama actual." }
    Write-Host "FEMAG CANDIDATE" -ForegroundColor Yellow
    Write-Host "Rama: $branch"
    gh workflow run publish-production.yml --repo $repo --ref $branch
    if ($LASTEXITCODE -ne 0) { throw "No se pudo lanzar Publish FEMAG candidate." }
    Wait-And-WatchRun "publish-production.yml" $branch
    Write-Host ""
    Write-Host "CANDIDATE PUBLICADO CORRECTAMENTE." -ForegroundColor Green
    exit 0
}

Write-Host "FEMAG PRODUCCION" -ForegroundColor Yellow
Write-Host "Leyendo candidate publicado..."
$candidateUrl = "https://raw.githubusercontent.com/oscarvogel/vogel-releases/main/apps/femag/candidate.json"
$candidate = Invoke-RestMethod -Uri $candidateUrl -UseBasicParsing
if (-not $candidate.version -or -not $candidate.sha256) { throw "candidate.json no contiene version/sha256 validos." }
if ($candidate.channel -ne "candidate") { throw "El manifest publicado no es channel=candidate." }
Write-Host "Version: $($candidate.version)"
Write-Host "SHA256 : $($candidate.sha256)"
Write-Host ""
Write-Host "Promoviendo exactamente este candidate a produccion..." -ForegroundColor Cyan
gh workflow run promote-production.yml --repo $repo --ref main -f operation=promote_candidate -f expected_version="$($candidate.version)" -f expected_sha256="$($candidate.sha256)" -f confirmation=PROMOTE
if ($LASTEXITCODE -ne 0) { throw "No se pudo lanzar Promote FEMAG production." }
Wait-And-WatchRun "promote-production.yml" "main"
Write-Host ""
Write-Host "PRODUCCION PROMOVIDA CORRECTAMENTE." -ForegroundColor Green