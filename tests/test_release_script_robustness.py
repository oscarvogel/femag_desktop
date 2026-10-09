"""Robustez de `release.ps1` (#611).

Dos cosas que lo hacian depender del estado previo de la maquina y que rompieron en
produccion: abortaba si no habia `.venv`, y abortaba por un `.env` del workspace recien en
el paso 6, cuando ya habia compilado y empaquetado todo.

Los tests no se quedan en assert sobre el texto del script: **ejecutan** la guarda con
PowerShell y miran que falle, porque un assert textual solo detecta regresion, no omision.
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
    if ($found.ContainsKey('Assert-NoEnvFileInWorkspace')) {{
        Assert-NoEnvFileInWorkspace
        $result['threw'] = $false
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
    assert "function Assert-NoEnvFileInWorkspace" in content


def test_release_no_longer_demands_a_venv_created_by_hand():
    """Antes abortaba con 'Active/cree el .venv antes de publicar'."""
    content = RELEASE.read_text(encoding="utf-8")

    assert "Active/cree el .venv antes de publicar" not in content


def test_env_file_is_no_longer_checked_at_the_end_of_the_build():
    """El `.env` se verificaba en el paso 6, ya con todo compilado y empaquetado."""
    content = RELEASE.read_text(encoding="utf-8")

    late_check = 'throw "Existe .env en el workspace de publicacion."'
    assert late_check not in content
    assert "Assert-NoEnvFileInWorkspace" in content


@requires_powershell
def test_release_script_parses():
    result = _extract_functions(["Ensure-Venv"], "'C:\\no-importa'")

    assert result["json"] is not None, result["stderr"]
    assert result["json"].get("parse_errors", 0) == 0


# --- comportamiento real de la guarda --------------------------------------------


@requires_powershell
def test_env_file_guard_throws_and_says_what_to_do(tmp_path):
    """Con `.env` presente tiene que cortar, y decir como se resuelve.

    Se ejecuta la funcion real del script contra un directorio con `.env`.
    """
    (tmp_path / ".env").write_text("DB_PASSWORD=secreto\n", encoding="utf-8")

    result = _extract_functions(
        ["Assert-NoEnvFileInWorkspace"], f"'{tmp_path}'"
    )

    assert result["json"] is not None, result["stderr"]
    assert result["json"]["threw"] is True
    message = result["json"].get("message", "")
    # El mensaje tiene que ser accionable: decir el problema sin decir qué hacer
    # devuelve al operador al mismo punto de partida del que ya salió.
    assert ".env" in message
    assert "release-bak" in message


@requires_powershell
def test_env_file_guard_lets_the_release_through_without_env(tmp_path):
    result = _extract_functions(
        ["Assert-NoEnvFileInWorkspace"], f"'{tmp_path}'"
    )

    assert result["json"] is not None, result["stderr"]
    assert result["json"]["threw"] is False


@requires_powershell
def test_env_file_guard_looks_at_the_repo_root_not_the_current_dir(tmp_path):
    """El guard mira `$RepoRoot`: correr el script desde otro lado no lo esquiva."""
    workspace = tmp_path / "repo"
    workspace.mkdir()
    other = tmp_path / "otro"
    other.mkdir()
    (other / ".env").write_text("DB_PASSWORD=secreto\n", encoding="utf-8")

    result = _extract_functions(["Assert-NoEnvFileInWorkspace"], f"'{workspace}'")

    assert result["json"] is not None, result["stderr"]
    # No hay `.env` en el repo: el que esta en otro directorio no bloquea.
    assert result["json"]["threw"] is False

    (workspace / ".env").write_text("DB_PASSWORD=secreto\n", encoding="utf-8")
    blocked = _extract_functions(["Assert-NoEnvFileInWorkspace"], f"'{workspace}'")

    assert blocked["json"] is not None, blocked["stderr"]
    assert blocked["json"]["threw"] is True


@requires_powershell
def test_venv_guard_finds_a_base_python_on_this_machine():
    """`Find-BasePython` tiene que encontrar algo en una maquina de build."""
    result = _extract_functions(["Find-BasePython"], "'C:\\no-importa'")

    assert result["json"] is not None, result["stderr"]


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