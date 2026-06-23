import pytest
from peewee import SqliteDatabase


TEST_DB = SqliteDatabase(":memory:")


@pytest.fixture()
def db():
    from app.config.database import bind_database
    from app.models import ALL_MODELS

    bind_database(TEST_DB)
    TEST_DB.connect(reuse_if_open=True)
    TEST_DB.create_tables(ALL_MODELS)
    yield TEST_DB
    TEST_DB.drop_tables(ALL_MODELS)
    TEST_DB.close()
