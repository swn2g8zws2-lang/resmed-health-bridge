from datetime import date

import pytest

from resmed_health_bridge.models import NightlyRecord
from resmed_health_bridge.service import TherapyQueries
from resmed_health_bridge.storage import NightlyStore


def populated(tmp_path):
    store = NightlyStore(tmp_path / "synthetic.sqlite3")
    store.initialize()
    store.upsert(NightlyRecord(night="2026-01-01", usage_minutes=420, ahi=2.0,
                               leak_95_lpm=8.0, pressure_95_cmh2o=10.0, source="synthetic"))
    store.upsert(NightlyRecord(night="2026-01-02", usage_minutes=480, ahi=4.0,
                               leak_95_lpm=12.0, pressure_95_cmh2o=12.0, source="synthetic"))
    return TherapyQueries(store)


def test_last_night_and_range(tmp_path):
    queries = populated(tmp_path)
    assert queries.last_night()["night"] == "2026-01-02"
    assert len(queries.therapy_range(date(2026, 1, 1), date(2026, 1, 2))) == 2


def test_trends_and_pressure(tmp_path):
    queries = populated(tmp_path)
    start, end = date(2026, 1, 1), date(2026, 1, 2)
    assert queries.metric_trend("ahi", start, end)["average"] == 3.0
    assert queries.metric_trend("usage_minutes", start, end)["average"] == 450
    assert queries.pressure_summary(start, end) == {
        "metric": "pressure_95_cmh2o", "start": "2026-01-01", "end": "2026-01-02",
        "nights_with_data": 2, "minimum": 10.0, "maximum": 12.0, "average": 11.0,
    }


def test_invalid_range_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="start"):
        populated(tmp_path).therapy_range(date(2026, 1, 2), date(2026, 1, 1))


def test_database_permissions_are_owner_only(tmp_path):
    path = tmp_path / "sensitive.sqlite3"
    NightlyStore(path).initialize()
    assert path.stat().st_mode & 0o777 == 0o600
    assert not path.with_name(path.name + "-wal").exists()
    assert not path.with_name(path.name + "-shm").exists()


def test_tilde_path_is_expanded_and_directory_is_private(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    store = NightlyStore("~/private/cache.sqlite3")
    store.initialize()
    assert store.path == str(tmp_path / "private" / "cache.sqlite3")
    assert (tmp_path / "private").stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "private" / "cache.sqlite3").stat().st_mode & 0o777 == 0o600


def test_insecure_preexisting_directory_is_rejected(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o755)
    with pytest.raises(PermissionError, match="0700"):
        NightlyStore(directory / "cache.sqlite3").initialize()


def test_query_range_is_bounded(tmp_path):
    with pytest.raises(ValueError, match="366 days"):
        populated(tmp_path).therapy_range(date(2025, 1, 1), date(2026, 1, 2))
