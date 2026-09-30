"""La tarea de esquema tiene que ser alcanzable desde el EXE congelado.

Dos restricciones reales de producción que estos tests fijan:

1. El instalador empaqueta **sólo** ``dist/FEMAG Desktop/*``. No viaja el
   repositorio ni ``scripts/``. Por eso la migración tiene que ser alcanzable
   desde ``app/``.
2. La tarea debe correr **antes** de abrir la ventana y bloquear el arranque si
   aborta, para que nadie opere con un esquema de importes que no soporta los
   valores correctos.
"""

import ast
import inspect
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def test_la_tarea_vive_en_app_y_no_en_scripts():
    """Si la migración viviera en scripts/, el EXE congelado no la tendría."""
    assert (RAIZ / "app/services/money_schema_migration.py").is_file()
    assert (RAIZ / "app/services/mysql_dump.py").is_file()

    tarea = inspect.getsource(
        __import__(
            "app.services.money_schema_migration", fromlist=["x"]
        )
    )
    assert "scripts." not in tarea


def test_el_dump_vive_en_app_para_que_la_app_pueda_respaldar():
    """El respaldo previo a ALTER tiene que poder correr sin mysqldump."""
    modulo = __import__("app.services.mysql_dump", fromlist=["x"])
    assert callable(modulo.dump_database_with_python)
    fuente = inspect.getsource(modulo.dump_database_with_python)
    assert "import pymysql" in inspect.getsource(modulo)


def test_el_script_de_backup_consume_el_modulo_de_app():
    """Una sola implementación del dump: el script no la duplica."""
    fuente = (RAIZ / "scripts/backup_mysql_databases.py").read_text(encoding="utf-8")
    assert "from app.services.mysql_dump import" in fuente
    # Y ya no define su propia copia.
    arbol = ast.parse(fuente)
    definidos = {
        n.name
        for n in ast.walk(arbol)
        if isinstance(n, (ast.FunctionDef, ast.ClassDef))
    }
    assert "dump_database_with_python" not in definidos
    assert "DatabaseDump" not in definidos


def test_el_arranque_invoca_la_tarea_antes_de_abrir_la_interfaz():
    """La migración tiene que correr antes de que FEMAG abra para operar."""
    fuente = (RAIZ / "app/production_entrypoint.py").read_text(encoding="utf-8")
    posicion_tarea = fuente.index("_run_money_schema_task(runtime_dir, log_path)")
    posicion_ui = fuente.index("result = main(args)")
    assert posicion_tarea < posicion_ui, "la migración debe correr antes de abrir la UI"
    assert "--skip-money-schema-task" in fuente


def test_si_la_tarea_aborta_el_arranque_no_continua():
    fuente = (RAIZ / "app/production_entrypoint.py").read_text(encoding="utf-8")
    assert "if codigo != 0:" in fuente
    assert "return codigo" in fuente
    assert "_show_fatal_error" in fuente


def test_la_tarea_corre_por_defecto_y_el_escape_es_optativo():
    """El camino normal es migrar; saltar la tarea requiere pedirlo explícito."""
    fuente = (RAIZ / "app/production_entrypoint.py").read_text(encoding="utf-8")
    assert 'if "--skip-money-schema-task" not in args:' in fuente
    # El escape no habilita la tarea: sólo permite omitirla.
    assert "--skip-money-schema-task" not in fuente.split("def run()")[0]


def test_la_tarea_no_toca_la_herramienta_de_reparacion():
    """Migración de esquema y reparación de históricos son dos caminos."""
    import app.services.money_schema_migration as tarea

    fuente = inspect.getsource(tarea)
    assert "repair" not in fuente.lower().replace("repara", "")
    assert not hasattr(tarea, "apply_plan")


def test_la_tarea_no_promueve_ni_despliega():
    """La tarea migra el esquema local; no toca canales ni empaques."""
    import app.services.money_schema_migration as tarea

    fuente = inspect.getsource(tarea).lower()
    for prohibido in ("candidate", "promote", "publish_femag", "manifest", "http"):
        assert prohibido not in fuente


@pytest.mark.parametrize(
    "prohibido",
    ["apply_plan", "repair_monetary_integrity", "auditoria", "budget.total_amount"],
)
def test_la_tarea_no_escribe_importes_de_documento(prohibido):
    import app.services.money_schema_migration as tarea

    fuente = inspect.getsource(tarea)
    assert prohibido not in fuente
