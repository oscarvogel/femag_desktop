import pytest

from scripts.performance_mysql_common import assert_safe_performance_database


@pytest.mark.parametrize(
    "name",
    [
        "femag_performance",
        "femag_performance_1000",
        "test_performance_femag",
    ],
)
def test_performance_database_names_are_accepted(name):
    assert_safe_performance_database(name)


@pytest.mark.parametrize(
    "name",
    [
        "femag",
        "femag_prod",
        "production",
        "femag_test",
        "",
        "femag-performance",
    ],
)
def test_non_performance_database_names_are_rejected(name):
    with pytest.raises(ValueError):
        assert_safe_performance_database(name)
