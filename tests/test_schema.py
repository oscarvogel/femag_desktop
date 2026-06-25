from peewee import SqliteDatabase


def test_ensure_runtime_schema_adds_missing_columns_to_existing_tables():
    from app.config.database import bind_database
    from app.config.schema import ensure_runtime_schema

    db = SqliteDatabase(":memory:")
    bind_database(db)
    db.connect(reuse_if_open=True)
    db.execute_sql(
        """
        CREATE TABLE driver (
            id INTEGER PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )

    ensure_runtime_schema(db)

    column_names = {column.name for column in db.get_columns("driver")}

    assert "carrier_id" in column_names
    assert "available" in column_names
