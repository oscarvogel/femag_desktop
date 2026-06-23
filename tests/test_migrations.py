def test_migration_runner_records_each_migration_once(db):
    from app.services.migration_service import MigrationRunner

    calls = []

    def migration(database):
        calls.append(database)

    runner = MigrationRunner(db, migrations=[("999_test_migration", migration)])

    assert runner.run_pending() == ["999_test_migration"]
    assert runner.run_pending() == []
    assert calls == [db]


def test_init_db_delegates_schema_changes_to_migration_runner():
    from pathlib import Path

    source = Path("scripts/init_db.py").read_text(encoding="utf-8")

    assert "MigrationRunner" in source
    assert "ALTER TABLE menuitem" not in source
