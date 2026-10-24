"""El CI tiene que cubrir las dos listas de dependencias (#781).

``requirements-web.txt`` se separo de ``requirements.txt`` para que el servidor
de la fabrica no necesite PyQt ni Git. Esa separacion rompio el CI en silencio:
el job de Linux instalaba solo la lista de la webapp y la suite no arrancaba
("No module named pytest"), asi que el job quedo en rojo sin que nadie lo
viera. Estos tests fijan las dos listas que cada job tiene que instalar.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
WEB_REQUIREMENTS = ROOT / "requirements-web.txt"
TEST_REQUIREMENTS = ROOT / "requirements-test.txt"


def test_linux_job_installs_the_full_stack_for_the_whole_suite():
    """La suite completa es la del escritorio: incluye tests de UI con PyQt5."""
    content = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "python -m pip install -r requirements.txt -r requirements-web.txt" in content


def test_ci_has_a_job_that_runs_the_webapp_without_the_desktop_stack():
    """La garantia del servidor tiene que estar verificada por el CI.

    Es lo que justifies separar las listas: en el Windows Server 2019 no hay
    PyQt ni Git. Si la webapp empieza a importarlos, el job tiene que ponerse
    rojo.
    """
    content = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "webapp-only:" in content
    assert "python -m pip install -r requirements-web.txt -r requirements-test.txt" in content
    assert 'if python -c "import PyQt5"' in content


def test_pytest_is_a_test_dependency_and_not_a_server_dependency():
    """pytest no va en el servidor de la fabrica: solo se usa para testear."""
    assert "pytest" in TEST_REQUIREMENTS.read_text(encoding="utf-8")

    web = WEB_REQUIREMENTS.read_text(encoding="utf-8")
    assert "pytest" not in web
