import subprocess
import sys

from peewee import SqliteDatabase


def test_seed_demo_data_is_idempotent_and_creates_operational_sample(tmp_path):
    from app.config.database import bind_database
    from app.models import ALL_MODELS
    from app.models.load_orders import LoadOrder
    from app.models.masters import Client, Driver, PalletType, Product
    from app.models.security import User
    from scripts.seed_demo_data import seed_demo_data

    db = SqliteDatabase(tmp_path / "demo.sqlite3")
    bind_database(db)
    db.connect()
    db.create_tables(ALL_MODELS)

    first = seed_demo_data()
    second = seed_demo_data()

    assert first["users"] == second["users"] == 4
    assert User.select().count() == 4
    assert Client.select().count() == 3
    assert Product.select().count() == 3
    assert PalletType.select().count() == 2
    assert LoadOrder.select().count() == 1
    assert Driver.select().where(Driver.available == False).count() == 1  # noqa: E712

    db.drop_tables(ALL_MODELS)
    db.close()


def test_demo_no_show_initializes_demo_database_and_ui_contract(tmp_path):
    db_path = tmp_path / "femag_demo.sqlite3"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.main",
            "--demo",
            "--no-show",
            "--demo-db",
            str(db_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "FEMAG demo UI OK" in completed.stdout
    assert db_path.exists()


def test_demo_runner_script_imports_main_entrypoint():
    import scripts.run_demo_ui as runner

    assert runner.main(["--smoke"]) == 0
