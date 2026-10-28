"""La imagen de Coolify no arrastra el escritorio y mantiene MySQL privada (#803)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _without_comments(relative: str) -> str:
    lines = _text(relative).splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def test_dockerfile_uses_only_the_webapp_requirements():
    dockerfile = _without_comments("deploy/coolify/Dockerfile")

    assert "requirements-container.txt" in dockerfile
    assert "requirements-web.txt" in dockerfile
    assert "requirements.txt" not in dockerfile
    assert "PyQt" not in dockerfile
    assert "USER femag" in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "curl" in dockerfile


def test_container_requirements_add_gunicorn_without_desktop():
    requirements = _without_comments("requirements-container.txt")

    assert "-r requirements-web.txt" in requirements
    assert "gunicorn" in requirements
    assert "PyQt" not in requirements
    assert "pyqt5libs" not in requirements


def test_entrypoint_runs_demo_seed_and_gunicorn_wsgi():
    entrypoint = _text("deploy/coolify/entrypoint.sh")
    gunicorn = _text("deploy/coolify/gunicorn.conf.py")

    assert "scripts/init_db.py" in entrypoint
    assert "FEMAG_WEB_AUTO_INIT_SCHEMA" in entrypoint
    assert "scripts/seed_webapp_demo.py" in entrypoint
    assert "webapp.wsgi:app" in entrypoint
    assert "gthread" in gunicorn
    assert "preload_app = False" in gunicorn


def test_wsgi_validates_schema_before_serving():
    wsgi = _text("webapp/wsgi.py")

    assert "initialize_runtime_database" in wsgi
    assert "validate_runtime_schema" in wsgi
    assert "create_app()" in wsgi


def test_demo_compose_keeps_mysql_private():
    compose = _text("deploy/coolify/docker-compose.demo.yml")

    assert "mysql:8.0" in compose
    assert "3306:3306" not in compose
    assert "condition: service_healthy" in compose
    assert "FEMAG_WEB_SEED_DEMO" in compose
    assert "FEMAG_WEB_AUTO_INIT_SCHEMA" in compose


def test_dockerignore_excludes_secrets_and_local_artifacts():
    ignored = _text(".dockerignore")

    for pattern in (".env", "tests", "docs", ".venv", "installer"):
        assert pattern in ignored
