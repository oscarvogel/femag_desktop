<#.
.SYNOPSIS
    Único punto de entrada del release FEMAG Desktop.

.DESCRIPTION
    .\release.ps1 candidate            -> build + validación + publicación local del candidate (por defecto).
    .\release.ps1 candidate -Local     -> idéntico al anterior (forma explícita).
    .\release.ps1 candidate -UseActions-> dispara el workflow publish-production.yml y lo sigue.
    .\release.ps1 production           -> promueve el candidate publicado a producción vía workflow.
    .\release.ps1 production -Local    -> promueve con el script local sin pasar por Actions.

    El flujo candidate local hace automáticamente: verificación de main,
    stash seguro de cambios locales (con restore garantizado), fetch +
    fast-forward de origin/main, preflight de herramientas, auto-instalación
    de Inno Setup 6 (winget/choco), tests, compileall, build del EXE,
    construcción del instalador, smoke + health-check, chequeo de secretos,
    SHA256, publicación en oscarvogel/vogel-releases y actualización de
    apps/femag/candidate.json. Nunca desactiva tests.
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("candidate", "production")]
    [string]$Channel,

    [switch]$Local,
    [switch]$UseActions,
    [switch]$SkipDeps,
    [switch]$NoAutoInstall,
    [string]$IsccPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Repo = "oscarvogel/femag_desktop"
$ReleaseRepo = "oscarvogel/vogel-releases"
$ReleaseTag = "femag-candidate"
$InstallerName = "FEMAG_Desktop_Produccion_Setup.exe"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $RepoRoot "scripts\Invoke-Native.ps1")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { $Python = "python" }
$Installer = Join-Path $RepoRoot "installer\output\$InstallerName"

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "No se encontro '$Name' en PATH."
    }
}

function Assert-GhAuth {
    $previousEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & gh auth status *> $null
    } finally {
        $ErrorActionPreference = $previousEAP
    }
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI no esta autenticado. Ejecute: gh auth login"
    }
}

function Get-LatestRunId([string]$Workflow, [string]$Branch) {
    $raw = Invoke-Capture -Command "gh" `
        -Arguments @("run", "list", "--repo", $Repo, "--workflow", $Workflow, "--branch", $Branch, "--limit", "1", "--json", "databaseId") `
        -FailureMessage "No se pudo listar runs de $Workflow."
    if (-not $raw -or $raw.Trim() -eq "[]") { return [long]0 }
    $item = $raw | ConvertFrom-Json
    if ($item -is [array]) { $item = $item[0] }
    if ($null -eq $item) { return [long]0 }
    return [long]$item.databaseId
}

function Wait-And-WatchRun([string]$Workflow, [string]$Branch, [long]$BeforeId) {
    # Detección por ID monótono (no por reloj): el reloj local puede estar
    # desviado del servidor y el filtro por createdAt perdía el run recién
    # lanzado aunque existiera.
    Write-Host ""
    Write-Host "Buscando ejecucion de $Workflow en $Branch..." -ForegroundColor Cyan
    $runId = $null
    for ($i = 0; $i -lt 30 -and -not $runId; $i++) {
        Start-Sleep -Seconds 4
        $raw = Invoke-Capture -Command "gh" `
            -Arguments @("run", "list", "--repo", $Repo, "--workflow", $Workflow, "--branch", $Branch, "--limit", "5", "--json", "databaseId") `
            -FailureMessage "No se pudo listar runs de $Workflow."
        $json = $raw | ConvertFrom-Json
        if ($json) {
            $fresh = @($json | Where-Object { try { [long]$_.databaseId -gt $BeforeId } catch { $false } })
            if ($fresh.Count -gt 0) { $runId = ($fresh | Sort-Object -Property databaseId | Select-Object -Last 1).databaseId }
        }
    }
    if (-not $runId) { throw "No se encontro la ejecucion recien lanzada de $Workflow." }
    Write-Host "Run: $runId" -ForegroundColor Green
    Invoke-Native -Command "gh" -Arguments @("run", "watch", "$runId", "--repo", $Repo, "--exit-status") `
        -FailureMessage "El workflow termino con error. Ver: gh run view $runId --repo $Repo --log-failed"
    Write-Host ""
    Invoke-Native -Command "gh" -Arguments @("run", "view", "$runId", "--repo", $Repo) `
        -FailureMessage "No se pudo ver el run $runId."
}

function Invoke-CandidateViaActions {
    Require-Command "git"
    $branch = Invoke-Capture -Command "git" -Arguments @("branch", "--show-current") `
        -FailureMessage "No se pudo determinar la rama actual."
    if (-not $branch) { throw "No se pudo determinar la rama actual." }
    Write-Host "FEMAG CANDIDATE (GitHub Actions)" -ForegroundColor Yellow
    Write-Host "Rama: $branch"
    $beforeId = Get-LatestRunId "publish-production.yml" $branch
    Invoke-Native -Command "gh" -Arguments @("workflow", "run", "publish-production.yml", "--repo", $Repo, "--ref", $branch) `
        -FailureMessage "No se pudo lanzar Publish FEMAG candidate."
    Wait-And-WatchRun "publish-production.yml" $branch $beforeId
    Write-Host ""
    Write-Host "CANDIDATE PUBLICADO CORRECTAMENTE (Actions)." -ForegroundColor Green
}

function Invoke-CandidateLocal {
    Require-Command "git"
    Require-Command "gh"

    Assert-GhAuth

    if ($env:VOGEL_RELEASES_TOKEN -and -not $env:GH_TOKEN) {
        $env:GH_TOKEN = $env:VOGEL_RELEASES_TOKEN
    }

    if (-not (Test-Path -LiteralPath $Python)) {
        throw "No existe $Python. Active/cree el .venv antes de publicar."
    }

    $branch = Invoke-Capture -Command "git" -Arguments @("branch", "--show-current") `
        -FailureMessage "No se pudo determinar la rama actual."
    if ($branch -ne "main") {
        throw "El release candidate debe ejecutarse desde main. Rama actual: $branch"
    }

    $stashCreated = $false
    $dirty = Invoke-Capture -Command "git" -Arguments @("status", "--porcelain") `
        -FailureMessage "No se pudo leer el estado del workspace."
    if ($dirty) {
        Write-Host "Detectados cambios locales: stash seguro temporal (se restauran al final)..." -ForegroundColor Yellow
        Invoke-Native -Command "git" -Arguments @("stash", "push", "--include-untracked", "-m", "femag-release-auto") `
            -FailureMessage "No se pudieron guardar temporalmente los cambios locales."
        $stashCreated = $true
    }

    Push-Location $RepoRoot
    try {
        Write-Host ""
        Write-Host "=== FEMAG CANDIDATE LOCAL ===" -ForegroundColor Cyan
        Write-Host "Sincronizando con origin/main (fast-forward, sin tocar cambios stasheados)..."
        Invoke-Native -Command "git" -Arguments @("fetch", "origin", "--prune") `
            -FailureMessage "No se pudo hacer fetch de origin."
        Invoke-Native -Command "git" -Arguments @("merge", "--ff-only", "origin/main") `
            -FailureMessage "main local divergió de origin/main y no admite fast-forward. Resolvé el divergente manualmente; no se tocó tu stash."

        $sourceSha = Invoke-Capture -Command "git" -Arguments @("rev-parse", "HEAD") `
            -FailureMessage "No se pudo obtener SOURCE_SHA."
        Write-Host "SOURCE_SHA: $sourceSha"

        # Los tests deben correr sobre la identidad de desarrollo versionada,
        # aunque haya restos locales de una compilacion anterior.
        Invoke-Native -Command "git" -Arguments @("restore", "--source=HEAD", "--", "app/build_info.py", "app/build_version.py") `
            -FailureMessage "No se pudo restaurar la identidad de desarrollo antes de los tests."

        Write-Host ""
        Write-Host "[1/7] Preflight de herramientas..." -ForegroundColor Yellow
        & $Python --version
        if ($LASTEXITCODE -ne 0) { throw "Python no funciona: $Python" }
        Write-Host "Resolviendo Inno Setup 6 (auto-instalación si falta y está permitida)..."
        $resolveArgs = @{}
        if ($IsccPath) { $resolveArgs["IsccPath"] = $IsccPath }
        elseif ($env:ISCC_PATH) { $resolveArgs["IsccPath"] = $env:ISCC_PATH }
        if ($NoAutoInstall) { $resolveArgs["NoAutoInstall"] = $true }
        . (Join-Path $RepoRoot "scripts\Resolve-InnoSetup.ps1")
        $preflightIscc = Resolve-InnoSetup @resolveArgs
        Write-Host "ISCC preflight OK: $preflightIscc" -ForegroundColor Green

        Write-Host ""
        Write-Host "[2/7] Tests (no se omiten, el fallo se muestra tal cual)..." -ForegroundColor Yellow
        Invoke-Native -Command $Python -Arguments @("-m", "pytest", "-q") `
            -FailureMessage "Los tests fallaron. No se publica nada. Ver el detalle arriba."

        Write-Host ""
        Write-Host "[3/7] Compile..." -ForegroundColor Yellow
        Invoke-Native -Command $Python -Arguments @("-m", "compileall", "-q", "app", "scripts") `
            -FailureMessage "compileall fallo. No se publica nada."

        Write-Host ""
        Write-Host "[4/7] Build EXE + instalador..." -ForegroundColor Yellow
        $buildArgs = @("-PythonPath", $Python)
        if ($IsccPath) { $buildArgs += @("-IsccPath", $IsccPath) }
        elseif ($env:ISCC_PATH) { $buildArgs += @("-IsccPath", $env:ISCC_PATH) }
        if ($NoAutoInstall) { $buildArgs += "-NoAutoInstall" }
        if (-not $SkipDeps) {
            Write-Host "Instalando dependencias de build (requirements-build.txt)..."
        } else {
            $buildArgs += "-SkipInstallDependencies"
        }
        # El script de build hace throw ante cualquier fallo; si retorna, verificar artefacto.
        & (Join-Path $RepoRoot "scripts\build_production_installer.ps1") @buildArgs
        if (-not (Test-Path -LiteralPath $Installer)) { throw "No se genero $Installer" }

        $versionLine = Get-Content (Join-Path $RepoRoot "app\build_info.py") |
            Select-String -Pattern 'BUILD_VERSION = "(.+)"'
        if (-not $versionLine) { throw "No se pudo leer BUILD_VERSION." }
        $version = $versionLine.Matches.Groups[1].Value
        if (-not $version) { throw "No se pudo leer BUILD_VERSION." }

        Write-Host ""
        Write-Host "[5/7] Smoke + health-check del EXE congelado..." -ForegroundColor Yellow
        $oldQt = $env:QT_QPA_PLATFORM
        $env:QT_QPA_PLATFORM = "offscreen"
        try {
            $exe = Resolve-Path (Join-Path $RepoRoot "dist\FEMAG Desktop\FEMAG Desktop.exe")
            $smokeRuntime = Join-Path ([System.IO.Path]::GetTempPath()) ("femag-smoke-" + [guid]::NewGuid().ToString("N"))
            New-Item -ItemType Directory -Force $smokeRuntime | Out-Null
            $oldLocalAppData = $env:LOCALAPPDATA
            try {
                $env:LOCALAPPDATA = $smokeRuntime
                $p = Start-Process -FilePath $exe -ArgumentList "--smoke" -PassThru -Wait
                if ($p.ExitCode -ne 0) { throw "El EXE no paso --smoke: $($p.ExitCode)" }

                $oldCi = $env:FEMAG_HEALTH_CHECK_CI
                $oldCiSkip = $env:FEMAG_HEALTH_CHECK_SKIP_SCHEMA
                $env:FEMAG_HEALTH_CHECK_CI = "1"
                $env:FEMAG_HEALTH_CHECK_SKIP_SCHEMA = "1"
                try {
                    $h = Start-Process -FilePath $exe -ArgumentList "--production-health-check" -PassThru -Wait
                    if ($h.ExitCode -ne 0) { throw "El EXE no paso production-health-check: $($h.ExitCode)" }
                } finally {
                    if ($null -eq $oldCi) { Remove-Item Env:FEMAG_HEALTH_CHECK_CI -ErrorAction SilentlyContinue } else { $env:FEMAG_HEALTH_CHECK_CI = $oldCi }
                    if ($null -eq $oldCiSkip) { Remove-Item Env:FEMAG_HEALTH_CHECK_SKIP_SCHEMA -ErrorAction SilentlyContinue } else { $env:FEMAG_HEALTH_CHECK_SKIP_SCHEMA = $oldCiSkip }
                }
            } finally {
                $env:LOCALAPPDATA = $oldLocalAppData
                Remove-Item -Recurse -Force $smokeRuntime -ErrorAction SilentlyContinue
            }
        } finally {
            $env:QT_QPA_PLATFORM = $oldQt
        }

        Write-Host ""
        Write-Host "[6/7] Seguridad del artefacto + SHA256..." -ForegroundColor Yellow
        $forbidden = @("*.ini", ".env", "*.env", "*secret*", "*credential*", "*.pem", "*.key")
        foreach ($root in @("dist\FEMAG Desktop", "installer\output")) {
            foreach ($pattern in $forbidden) {
                $hits = Get-ChildItem $root -Recurse -Force -File -Filter $pattern -ErrorAction SilentlyContinue
                if ($hits) {
                    $names = ($hits | ForEach-Object FullName) -join ", "
                    throw "Archivo prohibido en artefacto: $names"
                }
            }
        }
        if (Test-Path -LiteralPath ".env") { throw "Existe .env en el workspace de publicacion." }
        $sha256 = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-Host "Version: $version"
        Write-Host "SHA256 : $sha256"

        Write-Host ""
        Write-Host "[7/7] Publicando candidate en $ReleaseRepo..." -ForegroundColor Yellow
        $previousEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & gh release view $ReleaseTag --repo $ReleaseRepo *> $null
            $releaseExists = ($LASTEXITCODE -eq 0)
        } finally {
            $ErrorActionPreference = $previousEAP
        }
        if (-not $releaseExists) {
            Invoke-Native -Command "gh" -Arguments @("release", "create", $ReleaseTag, "--repo", $ReleaseRepo, "--title", "FEMAG candidate", "--notes", "Validated FEMAG candidate. Do not distribute as production.") `
                -FailureMessage "No se pudo crear el release candidate."
        }

        Invoke-Native -Command "gh" -Arguments @("release", "upload", $ReleaseTag, $Installer, "--repo", $ReleaseRepo, "--clobber") `
            -FailureMessage "No se pudo subir el instalador candidate."

        $downloadUrl = "https://github.com/$ReleaseRepo/releases/download/$ReleaseTag/$InstallerName"
        $temp = Join-Path $env:TEMP ("vogel-releases-femag-" + [guid]::NewGuid().ToString("N"))
        try {
            Invoke-Native -Command "gh" -Arguments @("repo", "clone", $ReleaseRepo, $temp, "--", "--depth", "1") `
                -FailureMessage "No se pudo clonar vogel-releases."

            $manifestDir = Join-Path $temp "apps\femag"
            New-Item -ItemType Directory -Force $manifestDir | Out-Null
            $payload = [ordered]@{
                schema_version = 1
                app_id = "femag"
                channel = "candidate"
                version = $version
                published_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                validated_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                source_sha = $sourceSha
                mandatory = $false
                download_url = $downloadUrl
                sha256 = $sha256
                notes = "Candidate FEMAG $version validado localmente."
            }
            $json = $payload | ConvertTo-Json
            $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            $manifestPath = Join-Path $manifestDir "candidate.json"
            [System.IO.File]::WriteAllText($manifestPath, $json, $utf8NoBom)

            Push-Location $temp
            try {
                Invoke-Native -Command "git" -Arguments @("config", "user.name", "oscarvogel-local-release") `
                    -FailureMessage "No se pudo configurar git en vogel-releases."
                Invoke-Native -Command "git" -Arguments @("config", "user.email", "release@vogelconsultoria.com.ar") `
                    -FailureMessage "No se pudo configurar git en vogel-releases."
                Invoke-Native -Command "git" -Arguments @("add", "--", "apps/femag/candidate.json") `
                    -FailureMessage "No se pudo staged candidate.json."
                $staged = Invoke-Capture -Command "git" -Arguments @("diff", "--cached", "--name-only") `
                    -FailureMessage "No se pudo leer el stage de vogel-releases."
                $unexpected = @($staged -split "`n" | Where-Object { $_.Trim() -ne "" -and $_.Trim() -ne "apps/femag/candidate.json" })
                if ($unexpected.Count -gt 0) { throw "Candidate intento modificar archivos inesperados: $($unexpected -join ', ')" }
                $prevEAP = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                try {
                    & git diff --cached --quiet
                    $hasChanges = ($LASTEXITCODE -ne 0)
                } finally {
                    $ErrorActionPreference = $prevEAP
                }
                if ($hasChanges) {
                    Invoke-Native -Command "git" -Arguments @("commit", "-m", "release(femag): candidate $version") `
                        -FailureMessage "No se pudo crear commit en vogel-releases."
                    Invoke-Native -Command "git" -Arguments @("push") `
                        -FailureMessage "No se pudo publicar candidate.json."
                }
            } finally {
                Pop-Location
            }
        } finally {
            Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
        }

        Write-Host ""
        Write-Host "VERSION=$version"
        Write-Host "SHA256=$sha256"
        Write-Host "SOURCE_SHA=$sourceSha"
        Write-Host "INSTALLER_PATH=$Installer"
        Write-Host "DOWNLOAD_URL=$downloadUrl"
        Write-Host "CANDIDATE_STATUS=OK"
        Write-Host ""
        Write-Host "Para promoverlo a produccion: .\release.ps1 production" -ForegroundColor Cyan
    } finally {
        # Los archivos que el build/tests generan no deben bloquear el pop del
        # stash del usuario: se descartan antes de restaurar su trabajo.
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            if ($stashCreated) {
                Write-Host ""
                Write-Host "Limpiando artefactos temporales del release..." -ForegroundColor Yellow
                & git reset --hard HEAD *> $null
                & git clean -fd *> $null
            } else {
                & git restore --source=HEAD -- app/build_info.py app/build_version.py 2>$null
            }

            if ($stashCreated) {
                Write-Host ""
                Write-Host "Restaurando cambios locales previos..." -ForegroundColor Yellow
                & git stash pop
                if ($LASTEXITCODE -ne 0) {
                    Write-Warning "No se pudieron restaurar automaticamente todos los cambios locales. Revise: git stash list (su trabajo sigue en el stash, no se perdio nada)."
                }
            }
        } finally {
            $ErrorActionPreference = $prevEAP
        }

        Pop-Location
    }
}

function Invoke-Production {
    if ($Local) {
        Write-Host "FEMAG PRODUCCION (local, sin Actions)" -ForegroundColor Yellow
        $promoteArgs = @("-Mode", "promote", "-Confirmation", "PROMOTE")
        & (Join-Path $RepoRoot "scripts\publish_femag_release.ps1") @promoteArgs
        if ($LASTEXITCODE -ne 0) { throw "La promocion local fallo." }
        Write-Host ""
        Write-Host "PRODUCCION PROMOVIDA CORRECTAMENTE (local)." -ForegroundColor Green
        return
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
    $beforeId = Get-LatestRunId "promote-production.yml" "main"
    Invoke-Native -Command "gh" -Arguments @("workflow", "run", "promote-production.yml", "--repo", $Repo, "--ref", "main", "-f", "operation=promote_candidate", "-f", "expected_version=$($candidate.version)", "-f", "expected_sha256=$($candidate.sha256)", "-f", "confirmation=PROMOTE") `
        -FailureMessage "No se pudo lanzar Promote FEMAG production."
    Wait-And-WatchRun "promote-production.yml" "main" $beforeId
    Write-Host ""
    Write-Host "PRODUCCION PROMOVIDA CORRECTAMENTE." -ForegroundColor Green
}

Require-Command "gh"
Assert-GhAuth

if ($Channel -eq "candidate") {
    if ($UseActions -and $Local) { throw "Use -Local o -UseActions, no ambos." }
    if ($UseActions) {
        Invoke-CandidateViaActions
    } else {
        Invoke-CandidateLocal
    }
    exit 0
}

Invoke-Production
