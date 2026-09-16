param(
    [ValidateSet("candidate")]
    [string]$Channel = "candidate"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Repo = "oscarvogel/femag_desktop"
$ReleaseRepo = "oscarvogel/vogel-releases"
$ReleaseTag = "femag-candidate"
$InstallerName = "FEMAG_Desktop_Produccion_Setup.exe"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Installer = Join-Path $RepoRoot "installer\output\$InstallerName"

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "No se encontro '$Name' en PATH."
    }
}

Push-Location $RepoRoot
try {
    Require-Command "git"
    Require-Command "gh"

    gh auth status *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI no esta autenticado. Ejecute: gh auth login"
    }

    if (-not (Test-Path $Python)) {
        throw "No existe $Python. Active/cree el .venv antes de publicar."
    }

    $branch = (git branch --show-current).Trim()
    if ($branch -ne "main") {
        throw "La publicacion local debe ejecutarse desde main. Rama actual: $branch"
    }

    $stashCreated = $false
    $dirty = git status --porcelain
    if ($dirty) {
        Write-Host "Guardando temporalmente cambios locales..." -ForegroundColor Yellow
        git stash push -u -m "femag-release-local-auto"
        if ($LASTEXITCODE -ne 0) { throw "No se pudieron guardar temporalmente los cambios locales." }
        $stashCreated = $true
    }

    Write-Host ""
    Write-Host "=== FEMAG LOCAL CANDIDATE ===" -ForegroundColor Cyan
    Write-Host "Actualizando main..."
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "No se pudo actualizar main." }

    $sourceSha = (git rev-parse HEAD).Trim()
    Write-Host "SOURCE_SHA: $sourceSha"

    # Los tests deben correr sobre la identidad de desarrollo versionada,
    # aunque haya restos locales de una compilacion anterior.
    git restore --source=HEAD -- app/build_info.py app/build_version.py
    if ($LASTEXITCODE -ne 0) { throw "No se pudo restaurar la identidad de desarrollo antes de los tests." }

    Write-Host ""
    Write-Host "[1/7] Tests..." -ForegroundColor Yellow
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Los tests fallaron. No se publica nada." }

    Write-Host ""
    Write-Host "[2/7] Compile..." -ForegroundColor Yellow
    & $Python -m compileall -q app scripts
    if ($LASTEXITCODE -ne 0) { throw "compileall fallo. No se publica nada." }

    Write-Host ""
    Write-Host "[3/7] Build EXE + instalador..." -ForegroundColor Yellow
    & (Join-Path $RepoRoot "scripts\build_production_installer.ps1") -SkipInstallDependencies -PythonPath $Python
    if ($LASTEXITCODE -ne 0) { throw "El build del instalador fallo." }
    if (-not (Test-Path $Installer)) { throw "No se genero $Installer" }

    $versionLine = Get-Content (Join-Path $RepoRoot "app\build_info.py") |
        Select-String -Pattern 'BUILD_VERSION = "(.+)"'
    $version = $versionLine.Matches.Groups[1].Value
    if (-not $version) { throw "No se pudo leer BUILD_VERSION." }

    Write-Host ""
    Write-Host "[4/7] Smoke del EXE..." -ForegroundColor Yellow
    $oldQt = $env:QT_QPA_PLATFORM
    $env:QT_QPA_PLATFORM = "offscreen"
    try {
        $exe = Resolve-Path (Join-Path $RepoRoot "dist\FEMAG Desktop\FEMAG Desktop.exe")
        $p = Start-Process -FilePath $exe -ArgumentList "--smoke" -PassThru -Wait
        if ($p.ExitCode -ne 0) { throw "El EXE no paso --smoke: $($p.ExitCode)" }

        $oldCi = $env:FEMAG_HEALTH_CHECK_CI
        $oldSkip = $env:FEMAG_HEALTH_CHECK_SKIP_SCHEMA
        $env:FEMAG_HEALTH_CHECK_CI = "1"
        $env:FEMAG_HEALTH_CHECK_SKIP_SCHEMA = "1"
        try {
            $h = Start-Process -FilePath $exe -ArgumentList "--production-health-check" -PassThru -Wait
            if ($h.ExitCode -ne 0) { throw "El EXE no paso production-health-check: $($h.ExitCode)" }
        } finally {
            $env:FEMAG_HEALTH_CHECK_CI = $oldCi
            $env:FEMAG_HEALTH_CHECK_SKIP_SCHEMA = $oldSkip
        }
    } finally {
        $env:QT_QPA_PLATFORM = $oldQt
    }

    Write-Host ""
    Write-Host "[5/7] Seguridad del artefacto..." -ForegroundColor Yellow
    $forbidden = @("*.ini", ".env", "*.env", "*secret*", "*credential*", "*.pem", "*.key")
    foreach ($root in @("dist\FEMAG Desktop", "installer\output")) {
        foreach ($pattern in $forbidden) {
            $matches = Get-ChildItem $root -Recurse -Force -File -Filter $pattern -ErrorAction SilentlyContinue
            if ($matches) {
                $names = ($matches | ForEach-Object FullName) -join ", "
                throw "Archivo prohibido en artefacto: $names"
            }
        }
    }

    Write-Host ""
    Write-Host "[6/7] SHA256..." -ForegroundColor Yellow
    $sha256 = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "Version: $version"
    Write-Host "SHA256 : $sha256"

    Write-Host ""
    Write-Host "[7/7] Publicando candidate..." -ForegroundColor Yellow
    gh release view $ReleaseTag --repo $ReleaseRepo *> $null
    if ($LASTEXITCODE -ne 0) {
        gh release create $ReleaseTag --repo $ReleaseRepo --title "FEMAG candidate" --notes "Validated FEMAG candidate. Do not distribute as production."
        if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el release candidate." }
    }

    gh release upload $ReleaseTag $Installer --repo $ReleaseRepo --clobber
    if ($LASTEXITCODE -ne 0) { throw "No se pudo subir el instalador candidate." }

    $temp = Join-Path $env:TEMP ("vogel-releases-femag-" + [guid]::NewGuid().ToString("N"))
    try {
        gh repo clone $ReleaseRepo $temp -- --depth 1
        if ($LASTEXITCODE -ne 0) { throw "No se pudo clonar vogel-releases." }

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
            download_url = "https://github.com/$ReleaseRepo/releases/download/$ReleaseTag/$InstallerName"
            sha256 = $sha256
            notes = "Candidate FEMAG $version validado localmente."
        }
        $json = $payload | ConvertTo-Json
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        $manifestPath = Join-Path $manifestDir "candidate.json"
        [System.IO.File]::WriteAllText($manifestPath, $json, $utf8NoBom)

        Push-Location $temp
        try {
            git config user.name "oscarvogel-local-release"
            git config user.email "release@vogelconsultoria.com.ar"
            git add -- apps/femag/candidate.json
            git diff --cached --quiet
            if ($LASTEXITCODE -ne 0) {
                git commit -m "release(femag): candidate $version"
                if ($LASTEXITCODE -ne 0) { throw "No se pudo crear commit en vogel-releases." }
                git push
                if ($LASTEXITCODE -ne 0) { throw "No se pudo publicar candidate.json." }
            }
        } finally {
            Pop-Location
        }
    } finally {
        Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
    }

    Write-Host ""
    Write-Host "CANDIDATE LOCAL PUBLICADO CORRECTAMENTE." -ForegroundColor Green
    Write-Host "Version : $version"
    Write-Host "SHA256  : $sha256"
    Write-Host "Source  : $sourceSha"
    Write-Host ""
    Write-Host "Para promoverlo a produccion: .\release.ps1 production" -ForegroundColor Cyan
} finally {
    # Si se creo stash al inicio, todo cambio que aparezca luego pertenece al proceso
    # de release/tests/build. Limpiarlo antes de restaurar el trabajo original evita
    # conflictos con capturas/PDFs generados por los tests.
    if ($stashCreated) {
        Write-Host ""
        Write-Host "Limpiando artefactos temporales del release..." -ForegroundColor Yellow
        git reset --hard HEAD *> $null
        git clean -fd *> $null
    } else {
        # Sin stash, limitar la limpieza a los archivos de identidad que modifica el build.
        git restore --source=HEAD -- app/build_info.py app/build_version.py 2>$null
    }

    if ($stashCreated) {
        Write-Host ""
        Write-Host "Restaurando cambios locales previos..." -ForegroundColor Yellow
        git stash pop
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "No se pudieron restaurar automaticamente todos los cambios locales. Revise: git stash list"
        }
    }

    Pop-Location
}
