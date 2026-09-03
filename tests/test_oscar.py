import pytest

from resmed_health_bridge.adapters.oscar import import_oscar_csv


def test_import_oscar_compatible_csv(tmp_path):
    path = tmp_path / "synthetic.csv"
    path.write_text("date,usage_minutes,ahi,leak_95_lpm,pressure_95_cmh2o\n"
                    "2026-01-03,390,1.5,7.2,9.8\n", encoding="utf-8")
    records = import_oscar_csv(path)
    assert len(records) == 1
    assert records[0].source == "oscar_csv"
    assert records[0].usage_minutes == 390


def test_import_requires_minimum_columns(tmp_path):
    path = tmp_path / "synthetic.csv"
    path.write_text("date,ahi\n2026-01-03,1.5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="usage_minutes"):
        import_oscar_csv(path)


def test_import_row_count_is_bounded(tmp_path, monkeypatch):
    from resmed_health_bridge.adapters import oscar

    monkeypatch.setattr(oscar, "MAX_IMPORT_ROWS", 1)
    path = tmp_path / "synthetic.csv"
    path.write_text("date,usage_minutes\n2026-01-01,1\n2026-01-02,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="row count"):
        oscar.import_oscar_csv(path)


def test_import_file_size_is_bounded(tmp_path, monkeypatch):
    from resmed_health_bridge.adapters import oscar

    monkeypatch.setattr(oscar, "MAX_IMPORT_BYTES", 10)
    path = tmp_path / "synthetic.csv"
    path.write_text("date,usage_minutes\n2026-01-01,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="import size"):
        oscar.import_oscar_csv(path)
