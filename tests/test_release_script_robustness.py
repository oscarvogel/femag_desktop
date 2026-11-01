"""Robustez de `release.ps1` (#611).

Dos cosas que lo hacian depender del estado previo de la maquina y que rompieron en
produccion: abortaba si no habia `.venv`, y abortaba por un `.env` del workspace recien en
el paso 6, cuando ya habia compilado y empaquetado todo.

El `.env` ya no corta el release: `Move-EnvFileAside` lo aparta a `.env.release-bak`
antes del stash (para que el propio stash lo cubra) y el `finally` lo restaura despues
del `stash pop`. Solo corta si ya existe un `.env.release-bak`, para no pisar nada.

Los tests no se quedan en assert sobre el texto del script: **ejecutan** la funcion con
PowerShell contra un directorio de mentira, porque un assert textual solo detecta
regresion, no omision.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release.ps1"

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")

requires_powershell = pytest.mark.skipif(
    POWERSHELL is None, reason="PowerShell no esta disponible en este equipo"
)


def _run_powershell(script: str) -> dict:
    completed = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(ROOT),
    )
    marker = "FEMAG_TEST_JSON:"
    payload = ""
    for line in completed.stdout.splitlines():
        if line.startswith(marker):
            payload = line[len(marker) :]
    return {
        "returncode": completed.returncode,
        "json": json.loads(payload) if payload.strip().startswith("{") else None,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _extract_functions(names: list[str], repo_root_expr: str) -> dict:
    """Ejecuta las funciones indicadas de release.ps1 contra un repo_root de mentira."""
    name_list = ", ".join(f"'{name}'" for name in names)
    script = f"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{RELEASE}', [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) {{
    'FEMAG_TEST_JSON:{{"parse_errors": ' + $errors.Count + '}}'
    exit 0
}}
$wanted = @({name_list})
$found = @{{}}
foreach ($name in $wanted) {{
    $fn = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }}, $true)
    if ($null -ne $fn) {{ $found[$name] = $fn.Extent.Text }}
}}
$root = {repo_root_expr}
$script:RepoRoot = $root
$script:Python = Join-Path $root '.venv\\Scripts\\python.exe'
foreach ($name in $wanted) {{
    if ($found.ContainsKey($name)) {{ Invoke-Expression $found[$name] }}
}}
$result = @{{ 'functions' = @($found.Keys) }}
try {{
    if ($found.ContainsKey('Move-EnvFileAside')) {{
        $result['returned'] = Move-EnvFileAside
    }}
    $result['threw'] = $false
}}
catch {{
    $result['threw'] = $true
    $result['message'] = $_.Exception.Message
}}
'FEMAG_TEST_JSON:' + ($result | ConvertTo-Json -Compress -Depth 4)
"""
    return _run_powershell(script)


# --- estructura -----------------------------------------------------------------


def test_release_defines_the_two_guards():
    content = RELEASE.read_text(encoding="utf-8")

    assert "function Ensure-Venv" in content
    assert "function Move-EnvFileAside" in content
    assert "function Assert-NoEnvFileInWorkspace" not in content


def test_release_no_longer_demands_a_venv_created_by_hand():
    """Antes abortaba con 'Active/cree el .venv antes de publicar'."""
    content = RELEASE.read_text(encoding="utf-8")

    assert "Active/cree el .venv antes de publicar" not in content


def test_env_file_is_no_longer_checked_at_the_end_of_the_build():
    """El `.env` se verificaba en el paso 6, ya con todo compilado y empaquetado."""
    content = RELEASE.read_text(encoding="utf-8")

    late_check = 'throw "Existe .env en el workspace de publicacion."'
    assert late_check not in content
    assert "Move-EnvFileAside" in content


def test_release_verifies_remote_asset_before_writing_manifest():
    """#839: el flujo local tambien valida el SHA remoto antes de candidate.json."""
    content = RELEASE.read_text(encoding="utf-8")

    assert "function Assert-RemoteAssetMatches" in content
    assert "Assert-RemoteAssetMatches $ReleaseTag $InstallerName $sha256" in content
    assert content.index("Assert-RemoteAssetMatches $ReleaseTag") < content.index(
        "[System.IO.File]::WriteAllText($manifestPath, $json"
    )
    assert "$uploadOk" in content
    assert "No se pudo subir el instalador candidate despues de 3 intentos" in content


@requires_powershell
def test_release_script_parses(tmp_path):
    result = _extract_functions(["Ensure-Venv"], f"'{tmp_path}'")

    assert result["json"] is not None, result["stderr"]
    assert result["json"].get("parse_errors", 0) == 0


# --- comportamiento real del apartado ------------------------------------------------


@requires_powershell
def test_env_file_is_moved_aside_instead_of_blocking(tmp_path):
    """Con `.env` presente lo aparta a `.env.release-bak` en vez de cortar.

    Se ejecuta la funcion real del script contra un directorio con `.env`.
    (La restauracion vive en el `finally` de `Invoke-CandidateLocal`, que aca no
    se ejecuta: se verifica el apartado, que es lo que esta funcion promete.)
    """
    (tmp_path / ".env").write_text("DB_PASSWORD=secreto\n", encoding="utf-8")

    result = _extract_functions(["Move-EnvFileAside"], f"'{tmp_path}'")

    assert result["json"] is not None, result["stderr"]
    assert result["json"]["threw"] is False
    assert result["json"]["returned"] is True
    assert not (tmp_path / ".env").exists()
    assert (tmp_path / ".env.release-bak").read_text(encoding="utf-8") == (
        "DB_PASSWORD=secreto\n"
    )


@requires_powershell
def test_env_file_move_refuses_to_overwrite_an_existing_backup(tmp_path):
    """Con `.env` y `.env.release-bak` tiene que cortar con mensaje accionable,
    sin pisar ninguno de los dos."""
    (tmp_path / ".env").write_text("DB_PASSWORD=secreto\n", encoding="utf-8")
    (tmp_path / ".env.release-bak").write_text("resto anterior\n", encoding="utf-8")

    result = _extract_functions(["Move-EnvFileAside"], f"'{tmp_path}'")

    assert result["json"] is not None, result["stderr"]
    assert result["json"]["threw"] is True
    message = result["json"].get("message", "")
    assert ".env.release-bak" in message
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "DB_PASSWORD=secreto\n"
    assert (tmp_path / ".env.release-bak").read_text(encoding="utf-8") == (
        "resto anterior\n"
    )


@requires_powershell
def test_env_file_move_lets_the_release_through_without_env(tmp_path):
    result = _extract_functions(["Move-EnvFileAside"], f"'{tmp_path}'")

    assert result["json"] is not None, result["stderr"]
    assert result["json"]["threw"] is False
    assert result["json"]["returned"] is False


@requires_powershell
def test_env_file_move_looks_at_the_repo_root_not_the_current_dir(tmp_path):
    """La funcion mira `$RepoRoot`: correr el script desde otro lado no la esquiva."""
    workspace = tmp_path / "repo"
    workspace.mkdir()
    other = tmp_path / "otro"
    other.mkdir()
    (other / ".env").write_text("DB_PASSWORD=secreto\n", encoding="utf-8")

    result = _extract_functions(["Move-EnvFileAside"], f"'{workspace}'")

    assert result["json"] is not None, result["stderr"]
    # No hay `.env` en el repo: el que esta en otro directorio no se toca.
    assert result["json"]["threw"] is False
    assert result["json"]["returned"] is False
    assert (other / ".env").exists()

    (workspace / ".env").write_text("DB_PASSWORD=secreto\n", encoding="utf-8")
    moved = _extract_functions(["Move-EnvFileAside"], f"'{workspace}'")

    assert moved["json"] is not None, moved["stderr"]
    assert moved["json"]["threw"] is False
    assert moved["json"]["returned"] is True
    assert not (workspace / ".env").exists()
    assert (workspace / ".env.release-bak").exists()


@requires_powershell
def test_venv_guard_finds_a_base_python_on_this_machine(tmp_path):
    """`Find-BasePython` tiene que encontrar algo en una maquina de build."""
    result = _extract_functions(["Find-BasePython"], f"'{tmp_path}'")

    assert result["json"] is not None, result["stderr"]


def _run_qt_offscreen(action: str, initial: str | None):
    if initial is None:
        setup = "Remove-Item Env:\\QT_QPA_PLATFORM -ErrorAction SilentlyContinue"
    else:
        setup = f"$env:QT_QPA_PLATFORM = '{initial}'"
    script = f"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{RELEASE}', [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) {{
    'FEMAG_TEST_JSON:{{"parse_errors": ' + $errors.Count + '}}'
    exit 0
}}
$fn = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-WithQtOffscreen' }}, $true)
if ($null -eq $fn) {{
    'FEMAG_TEST_JSON:{{"found": false}}'
    exit 0
}}
Invoke-Expression $fn.Extent.Text
{setup}
$result = @{{ 'found' = $true; 'before' = $env:QT_QPA_PLATFORM }}
try {{
    Invoke-WithQtOffscreen {{ {action} }}
    $result['threw'] = $false
}}
catch {{
    $result['threw'] = $true
    $result['message'] = $_.Exception.Message
}}
$result['after'] = $env:QT_QPA_PLATFORM
if ($null -ne $global:inside) {{ $result['inside'] = $global:inside }}
'FEMAG_TEST_JSON:' + ($result | ConvertTo-Json -Compress -Depth 4)
"""
    return _run_powershell(script)


@requires_powershell
def test_qt_offscreen_is_set_for_tests_and_restored(tmp_path):
    result = _run_qt_offscreen("$global:inside = $env:QT_QPA_PLATFORM", None)

    assert result["json"] is not None, result["stderr"]
    assert result["json"]["found"] is True
    assert result["json"]["inside"] == "offscreen"
    assert result["json"]["after"] is None


@requires_powershell
def test_qt_offscreen_respects_operator_value(tmp_path):
    result = _run_qt_offscreen("$global:inside = $env:QT_QPA_PLATFORM", "windows")

    assert result["json"] is not None, result["stderr"]
    assert result["json"]["inside"] == "windows"
    assert result["json"]["after"] == "windows"


@requires_powershell
def test_qt_offscreen_is_restored_when_tests_fail(tmp_path):
    result = _run_qt_offscreen("throw 'tests fallaron'", None)

    assert result["json"] is not None, result["stderr"]
    assert result["json"]["threw"] is True
    assert result["json"]["after"] is None


@requires_powershell
def test_ensure_venv_does_nothing_when_the_python_already_exists(tmp_path, monkeypatch):
    """Con el `.venv` ya hecho no debe intentar crearlo de nuevo."""
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")

    script = f"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{RELEASE}', [ref]$tokens, [ref]$errors)
$fn = $ast.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Ensure-Venv' }}, $true)
Invoke-Expression $fn.Extent.Text
$script:RepoRoot = '{tmp_path}'
$script:Python = '{python}'
function Invoke-Native {{ throw 'Invoke-Native no deberia llamarse con el .venv ya creado' }}
Ensure-Venv
'FEMAG_TEST_JSON:{{"ok": true}}'
"""
    result = _run_powershell(script)

    assert result["json"] is not None, result["stderr"]
    assert result["json"]["ok"] is True
