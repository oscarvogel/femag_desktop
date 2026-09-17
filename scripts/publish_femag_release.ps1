[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('candidate', 'promote')]
    [string]$Mode,

    [string]$Version,
    [string]$Sha256,
    [string]$Confirmation,
    [switch]$SkipLocalValidation,
    [switch]$SkipProductionHealthCheck,
    [switch]$AllowDirty,
    [string]$Repo = 'oscarvogel/femag_desktop',
    [string]$ReleaseRepo = 'oscarvogel/vogel-releases'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$installerName = 'FEMAG_Desktop_Produccion_Setup.exe'
$candidateTag = 'femag-candidate'
$latestTag = 'latest'
$previousTag = 'femag-previous'
$releaseManifestRelativePath = 'apps/femag'
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("femag-release-{0}" -f [Guid]::NewGuid().ToString('N'))

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)] [string]$Command,
        [Parameter(Mandatory = $true)] [string[]]$Arguments
    )

    # Enviar la salida operativa a la consola sin devolverla por el pipeline.
    # Así las funciones que retornan objetos (por ejemplo el artefacto) no
    # reciben también cada línea de PyInstaller/Inno Setup.
    & $Command @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Falló el comando: $Command $($Arguments -join ' ')"
    }
}

function Get-CheckedOutput {
    param(
        [Parameter(Mandatory = $true)] [string]$Command,
        [Parameter(Mandatory = $true)] [string[]]$Arguments
    )

    $output = & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falló el comando: $Command $($Arguments -join ' ')"
    }
    return ($output -join "`n").Trim()
}

function Assert-GhAvailable {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw 'No se encontró GitHub CLI (gh) en PATH.'
    }

    # Permite usar el secreto local VOGEL_RELEASES_TOKEN sin escribirlo en la línea de comandos.
    if (-not $env:GH_TOKEN -and $env:VOGEL_RELEASES_TOKEN) {
        $env:GH_TOKEN = $env:VOGEL_RELEASES_TOKEN
    }

    & gh auth status *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'GitHub CLI no está autenticado. Ejecutá gh auth login o definí GH_TOKEN/VOGEL_RELEASES_TOKEN.'
    }
}

function Assert-CleanWorkspace {
    if ($AllowDirty) {
        Write-Warning 'Se permite publicar desde un workspace con cambios locales por -AllowDirty.'
        return
    }

    $status = @(git -C $repoRoot status --porcelain)
    $releaseInputs = @('app/', 'installer/', 'scripts/', 'requirements.txt', 'requirements-web.txt', 'requirements-build.txt')
    $relevant = @($status | Where-Object {
        $path = $_.Substring([Math]::Min(3, $_.Length)).Trim().Replace('\', '/')
        $releaseInputs | Where-Object { $path -eq $_ -or $path.StartsWith($_) }
    })
    if ($relevant.Count -gt 0) {
        throw 'El workspace tiene cambios en archivos del release. Commiteá sólo los archivos correctos o usá -AllowDirty de forma deliberada.'
    }
    if ($status.Count -gt 0) {
        Write-Host 'Se ignoran cambios locales fuera del código y artefactos del release.'
    }
}

function Invoke-LocalValidation {
    if ($SkipLocalValidation) {
        Write-Host 'Validación local omitida por -SkipLocalValidation.'
        return
    }

    $python = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        $python = 'python'
    }

    Write-Host 'Ejecutando git diff --check...'
    Invoke-Checked 'git' @('-C', $repoRoot, 'diff', '--check')
    Write-Host 'Ejecutando tests locales...'
    Invoke-Checked $python @('-m', 'pytest', '-q')
    Write-Host 'Ejecutando compileall local...'
    Invoke-Checked $python @('-m', 'compileall', 'app')
}

function Invoke-ProductionBuild {
    Write-Host 'Compilando EXE e instalador localmente...'
    Invoke-Checked 'powershell.exe' @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', (Join-Path $repoRoot 'scripts\build_production_installer.ps1'),
        '-SkipInstallDependencies'
    )

    $exe = Join-Path $repoRoot 'dist\FEMAG Desktop\FEMAG Desktop.exe'
    $installer = Join-Path $repoRoot 'installer\output\FEMAG_Desktop_Produccion_Setup.exe'
    if (-not (Test-Path $exe)) { throw "No se encontró el EXE generado: $exe" }
    if (-not (Test-Path $installer)) { throw "No se encontró el instalador generado: $installer" }

    Write-Host 'Ejecutando smoke test sobre el EXE congelado...'
    Invoke-Checked $exe @('--smoke')

    if (-not $SkipProductionHealthCheck) {
        Write-Host 'Ejecutando production health-check sobre el EXE congelado...'
        $oldCi = $env:FEMAG_HEALTH_CHECK_CI
        try {
            $env:FEMAG_HEALTH_CHECK_CI = '1'
            Invoke-Checked $exe @('--production-health-check')
        }
        finally {
            if ($null -eq $oldCi) { Remove-Item Env:FEMAG_HEALTH_CHECK_CI -ErrorAction SilentlyContinue }
            else { $env:FEMAG_HEALTH_CHECK_CI = $oldCi }
        }
    }

    $forbidden = @('*.ini', '.env', '*.env', '*secret*', '*credential*', '*.pem', '*.key')
    foreach ($root in @((Join-Path $repoRoot 'dist\FEMAG Desktop'), (Join-Path $repoRoot 'installer\output'))) {
        foreach ($pattern in $forbidden) {
            $matches = @(Get-ChildItem -LiteralPath $root -Recurse -Force -File -Filter $pattern -ErrorAction SilentlyContinue)
            if ($matches.Count -gt 0) {
                throw "Archivo prohibido en artefacto: $($matches[0].FullName)"
            }
        }
    }

    $versionMatch = Select-String -Path (Join-Path $repoRoot 'app\build_info.py') -Pattern 'BUILD_VERSION = "(.+)"'
    if (-not $versionMatch) { throw 'No se pudo obtener BUILD_VERSION.' }
    $version = $versionMatch.Matches[0].Groups[1].Value
    $sha = (Get-FileHash $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    return [pscustomobject]@{ Installer = $installer; Version = $version; Sha256 = $sha }
}

function Ensure-Release {
    param([string]$Tag, [string]$Title)

    & gh release view $Tag --repo $ReleaseRepo *> $null
    if ($LASTEXITCODE -ne 0) {
        Invoke-Checked 'gh' @('release', 'create', $Tag, '--repo', $ReleaseRepo, '--title', $Title, '--notes', 'Managed by FEMAG local release script.')
    }
}

function Write-Utf8Json {
    param([string]$Path, [object]$Value)

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force $parent | Out-Null
    $json = $Value | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($Path, $json + "`n", [System.Text.UTF8Encoding]::new($false))
}

function Read-Manifest {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Assert-Manifest {
    param([object]$Manifest, [string]$Name)
    if ($null -eq $Manifest) { throw "$Name manifest no existe." }
    if ($Manifest.schema_version -ne 1 -or $Manifest.app_id -ne 'femag') { throw "$Name manifest inválido." }
    if ([string]$Manifest.version -notmatch '^\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{2}$') { throw "$Name version inválida." }
    if ([string]$Manifest.sha256 -notmatch '^[0-9a-fA-F]{64}$') { throw "$Name SHA256 inválido." }
}

function Download-And-Verify {
    param([string]$Tag, [object]$Manifest, [string]$Folder)

    New-Item -ItemType Directory -Force $Folder | Out-Null
    Invoke-Checked 'gh' @('release', 'download', $Tag, '--repo', $ReleaseRepo, '--pattern', $installerName, '--dir', $Folder, '--clobber')
    $path = Join-Path $Folder $installerName
    if (-not (Test-Path $path)) { throw "No se descargó el asset $Tag/$installerName." }
    $actual = (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne ([string]$Manifest.sha256).ToLowerInvariant()) { throw "El SHA256 de $Tag no coincide con su manifest." }
    return $path
}

function Clone-ReleasesRepository {
    $path = Join-Path $tempRoot 'vogel-releases'
    Invoke-Checked 'gh' @('repo', 'clone', $ReleaseRepo, $path, '--', '--depth=1')
    return $path
}

function Copy-Manifest {
    param([object]$Manifest)
    $copy = [ordered]@{}
    foreach ($property in $Manifest.psobject.Properties) {
        $copy[$property.Name] = $property.Value
    }
    return $copy
}

function Compare-FemagVersion {
    param([string]$Left, [string]$Right)

    $leftParts = $Left.Split('.')
    $rightParts = $Right.Split('.')
    for ($index = 0; $index -lt 6; $index++) {
        $leftNumber = [int]$leftParts[$index]
        $rightNumber = [int]$rightParts[$index]
        if ($leftNumber -lt $rightNumber) { return -1 }
        if ($leftNumber -gt $rightNumber) { return 1 }
    }
    return 0
}

function Commit-ReleasesRepository {
    param([string]$Path, [string]$Message)

    Invoke-Checked 'git' @('-C', $Path, 'config', 'user.name', 'FEMAG local release')
    Invoke-Checked 'git' @('-C', $Path, 'config', 'user.email', 'femag-release@users.noreply.github.com')
    Invoke-Checked 'git' @('-C', $Path, 'add', '--', 'apps/femag/candidate.json', 'apps/femag/latest.json', 'apps/femag/previous.json', 'apps/femag/history.jsonl')
    $unexpected = @(git -C $Path diff --cached --name-only | Where-Object {
        $_ -notin @('apps/femag/candidate.json', 'apps/femag/latest.json', 'apps/femag/previous.json', 'apps/femag/history.jsonl')
    })
    if ($unexpected.Count -gt 0) { throw "El script intentó modificar archivos inesperados: $($unexpected -join ', ')" }

    & git -C $Path diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        Invoke-Checked 'git' @('-C', $Path, 'commit', '-m', $Message)
        Invoke-Checked 'git' @('-C', $Path, 'push', 'origin', 'main')
    }
    else {
        Write-Host 'No hubo cambios de manifest para commitear.'
    }
}

function Publish-Candidate {
    Assert-CleanWorkspace
    Invoke-LocalValidation
    $artifact = Invoke-ProductionBuild
    Write-Host "Versión local: $($artifact.Version)"
    Write-Host "SHA256: $($artifact.Sha256)"

    Ensure-Release $candidateTag 'FEMAG candidate'
    Invoke-Checked 'gh' @('release', 'upload', $candidateTag, $artifact.Installer, '--repo', $ReleaseRepo, '--clobber')

    $releasePath = Clone-ReleasesRepository
    try {
        $manifest = [ordered]@{
            schema_version = 1
            app_id = 'femag'
            channel = 'candidate'
            version = $artifact.Version
            published_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
            validated_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
            source_sha = Get-CheckedOutput 'git' @('-C', $repoRoot, 'rev-parse', 'HEAD')
            source_dirty = [bool]$AllowDirty
            mandatory = $false
            download_url = "https://github.com/$ReleaseRepo/releases/download/$candidateTag/$installerName"
            sha256 = $artifact.Sha256
            notes = "Candidate FEMAG $($artifact.Version) validado localmente."
        }
        Write-Utf8Json (Join-Path $releasePath "$releaseManifestRelativePath\candidate.json") $manifest
        Commit-ReleasesRepository $releasePath "release(femag): candidate $($artifact.Version)"
    }
    finally {
        Remove-Item -LiteralPath $releasePath -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host 'Candidate publicada directamente en vogel-releases.' -ForegroundColor Green
    Write-Host "Versión: $($artifact.Version)"
    Write-Host "SHA256: $($artifact.Sha256)"
}

function Promote-Candidate {
    if ($Confirmation -cne 'PROMOTE') { throw 'La promoción requiere -Confirmation PROMOTE.' }

    $releasePath = Clone-ReleasesRepository
    try {
        $candidatePath = Join-Path $releasePath "$releaseManifestRelativePath\candidate.json"
        $latestPath = Join-Path $releasePath "$releaseManifestRelativePath\latest.json"
        $previousPath = Join-Path $releasePath "$releaseManifestRelativePath\previous.json"
        $historyPath = Join-Path $releasePath "$releaseManifestRelativePath\history.jsonl"
        $candidate = Read-Manifest $candidatePath
        Assert-Manifest $candidate 'candidate'
        if ([string]$candidate.channel -ne 'candidate') { throw 'candidate.json no declara channel=candidate.' }
        if ([string]::IsNullOrWhiteSpace($Version)) { $Version = [string]$candidate.version }
        if ([string]::IsNullOrWhiteSpace($Sha256)) { $Sha256 = [string]$candidate.sha256 }
        if ($Version -notmatch '^\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{2}$') { throw "Versión inválida: $Version" }
        if ($Sha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'SHA256 inválido en candidate.json.' }
        if ([string]$candidate.version -ne $Version) { throw 'La versión candidate cambió.' }
        if (([string]$candidate.sha256).ToLowerInvariant() -ne $Sha256.ToLowerInvariant()) { throw 'El SHA256 candidate cambió.' }

        $latest = Read-Manifest $latestPath
        if ($null -ne $latest) { Assert-Manifest $latest 'latest' }
        if ($null -ne $latest -and [string]$latest.version -eq $Version -and ([string]$latest.sha256).ToLowerInvariant() -eq $Sha256.ToLowerInvariant()) {
            Write-Host 'La candidate ya está promovida exactamente. No se hacen cambios.'
            return
        }
        if ($null -ne $latest -and (Compare-FemagVersion $Version ([string]$latest.version)) -le 0) {
            throw "La candidate $Version no es superior a latest $($latest.version); no se permite una regresión de producción."
        }

        Ensure-Release $candidateTag 'FEMAG candidate'
        Ensure-Release $latestTag 'Vogel Releases - Latest'
        Ensure-Release $previousTag 'FEMAG previous production'
        $candidateAsset = Download-And-Verify $candidateTag $candidate (Join-Path $tempRoot 'candidate')

        if ($null -ne $latest) {
            $latestAsset = Download-And-Verify $latestTag $latest (Join-Path $tempRoot 'latest')
            Invoke-Checked 'gh' @('release', 'upload', $previousTag, $latestAsset, '--repo', $ReleaseRepo, '--clobber')
            $previous = Copy-Manifest $latest
            $previous['channel'] = 'previous'
            $previous['download_url'] = "https://github.com/$ReleaseRepo/releases/download/$previousTag/$installerName"
            $previous['archived_at'] = (Get-Date).ToUniversalTime().ToString('o')
            Write-Utf8Json $previousPath $previous
        }

        Invoke-Checked 'gh' @('release', 'upload', $latestTag, $candidateAsset, '--repo', $ReleaseRepo, '--clobber')
        $promoted = Copy-Manifest $candidate
        $promoted['channel'] = 'latest'
        $promoted['download_url'] = "https://github.com/$ReleaseRepo/releases/download/$latestTag/$installerName"
        $promoted['approved_at'] = (Get-Date).ToUniversalTime().ToString('o')
        $promoted['approved_by'] = Get-CheckedOutput 'gh' @('api', 'user', '--jq', '.login')
        $promoted['approval_source'] = 'local-script'
        Write-Utf8Json $latestPath $promoted

        $historyEntry = [ordered]@{
            operation = 'promote_candidate'
            at = (Get-Date).ToUniversalTime().ToString('o')
            actor = $promoted['approved_by']
            version = $Version
            sha256 = $Sha256.ToLowerInvariant()
            source = 'local-script'
        }
        Add-Content -LiteralPath $historyPath -Value ($historyEntry | ConvertTo-Json -Compress) -Encoding utf8
        Commit-ReleasesRepository $releasePath "release(femag): promote $Version"
    }
    finally {
        Remove-Item -LiteralPath $releasePath -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Candidate $Version promovida directamente a producción." -ForegroundColor Green
}

Assert-GhAvailable
New-Item -ItemType Directory -Force $tempRoot | Out-Null
try {
    if ($Mode -eq 'candidate') {
        Publish-Candidate
    }
    else {
        Promote-Candidate
    }
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
