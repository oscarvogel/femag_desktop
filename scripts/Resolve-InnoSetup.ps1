# Shared Inno Setup 6 resolver for FEMAG build scripts.
# Dot-source this file:  . "$PSScriptRoot\Resolve-InnoSetup.ps1"
# Provides: Resolve-InnoSetup [-IsccPath <path>] [-NoAutoInstall]

function Resolve-InnoSetup {
    [CmdletBinding()]
    param(
        [string]$IsccPath,
        [switch]$NoAutoInstall
    )

    $attempts = New-Object System.Collections.Generic.List[string]

    function Find-Iscc {
        $found = @()

        # 1. Explicit path (parameter or ISCC_PATH env).
        $explicit = @()
        if ($IsccPath) { $explicit += $IsccPath }
        if ($env:ISCC_PATH) { $explicit += $env:ISCC_PATH }
        foreach ($candidate in $explicit) {
            $attempts.Add("explicit:$candidate") | Out-Null
            if ($candidate -and (Test-Path -LiteralPath $candidate)) {
                return $candidate
            }
        }

        # 2. Well-known install locations.
        $known = @(
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
        )
        foreach ($candidate in $known) {
            $attempts.Add("known:$candidate") | Out-Null
            if ($candidate -and (Test-Path -LiteralPath $candidate)) {
                return $candidate
            }
        }

        # 3. Registro de Windows (soporta instalaciones en rutas no estándar).
        $attempts.Add("registry:Uninstall\Inno Setup 6_is1 InstallLocation") | Out-Null
        try {
            $regPaths = @(
                "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
                "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
                "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
            )
            foreach ($regPath in $regPaths) {
                $location = (Get-ItemProperty -LiteralPath $regPath -ErrorAction SilentlyContinue).InstallLocation
                if ($location) {
                    $regCandidate = Join-Path $location "ISCC.exe"
                    $attempts.Add("registry:$regCandidate") | Out-Null
                    if (Test-Path -LiteralPath $regCandidate) {
                        return $regCandidate
                    }
                }
            }
        } catch { }

        # 4. ISCC.exe reachable via PATH.
        $attempts.Add("path:ISCC.exe") | Out-Null
        try {
            $cmd = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
            if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) {
                return $cmd.Source
            }
        } catch { }

        return $null
    }

    function Install-InnoSetup {
        if ($NoAutoInstall) {
            Write-Host "Auto-instalación de Inno Setup desactivada (-NoAutoInstall)." -ForegroundColor Yellow
            return $false
        }

        $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
        if (-not $winget) { $winget = Get-Command "winget" -ErrorAction SilentlyContinue }
        if ($winget) {
            Write-Host "Inno Setup 6 no encontrado. Instalando con winget (JRSoftware.InnoSetup)..." -ForegroundColor Cyan
            $attempts.Add("install:winget JRSoftware.InnoSetup") | Out-Null
            try {
                # --force: instalación directa aunque winget crea que el paquete
                # ya existe (cubre registros huérfanos sin archivos en disco,
                # caso que de otro modo termina en "No available upgrade found").
                & winget install --id JRSoftware.InnoSetup --exact --silent --force `
                    --accept-package-agreements --accept-source-agreements
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "winget instaló Inno Setup. Re-localizando ISCC.exe..." -ForegroundColor Green
                    return $true
                }
                Write-Warning "winget terminó con código $LASTEXITCODE."
            } catch {
                Write-Warning "winget falló: $($_.Exception.Message)"
            }
        } else {
            $attempts.Add("install:winget no disponible") | Out-Null
        }

        $choco = Get-Command "choco.exe" -ErrorAction SilentlyContinue
        if (-not $choco) { $choco = Get-Command "choco" -ErrorAction SilentlyContinue }
        if ($choco) {
            Write-Host "Intentando instalar Inno Setup con Chocolatey..." -ForegroundColor Cyan
            $attempts.Add("install:choco innosetup") | Out-Null
            try {
                & choco install innosetup --yes --no-progress
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "Chocolatey instaló Inno Setup. Re-localizando ISCC.exe..." -ForegroundColor Green
                    return $true
                }
                Write-Warning "choco terminó con código $LASTEXITCODE."
            } catch {
                Write-Warning "choco falló: $($_.Exception.Message)"
            }
        } else {
            $attempts.Add("install:choco no disponible") | Out-Null
        }

        return $false
    }

    $resolved = Find-Iscc
    if ($resolved) {
        Write-Host "Inno Setup localizado: $resolved" -ForegroundColor Green
        return $resolved
    }

    Write-Host "ISCC.exe no encontrado en rutas conocidas ni en PATH. Intentos hasta ahora:" -ForegroundColor Yellow
    foreach ($attempt in $attempts) { Write-Host "  - $attempt" }

    $installed = Install-InnoSetup
    if ($installed) {
        # Refrescar PATH de la sesión por si el instalador lo modificó.
        try {
            $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
            $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
            if ($machinePath -or $userPath) { $env:Path = "$machinePath;$userPath" }
        } catch { }
        $resolved = Find-Iscc
        if ($resolved) {
            Write-Host "Inno Setup localizado tras instalación: $resolved" -ForegroundColor Green
            return $resolved
        }
    }

    $detail = ($attempts | ForEach-Object { "  - $_" }) -join "`n"
    throw (
        "No se encontró Inno Setup 6 (ISCC.exe) incluso después de intentar resolverlo.`n" +
        "Intentos:`n$detail`n" +
        "Soluciones: instalá Inno Setup 6 manualmente, o definí `$env:ISCC_PATH con la ruta completa a ISCC.exe, " +
        "o ejecutá sin -NoAutoInstall con winget/choco disponibles."
    )
}
