import json

import pandas as pd
import pytest

from pipeline import config, ingest, paths

SAMPLE_FILES = {
    "fire_archive_M-C61_sample.csv.gz": "MODIS",
    "fire_archive_SV-C2_sample.csv.gz": "VIIRS",
    "fire_archive_J1V-C2_sample.csv.gz": "VIIRS",
}


@pytest.fixture(scope="module")
def sample():
    return {n: pd.read_csv(paths.SAMPLE_FIRMS / n) for n in SAMPLE_FILES}


def test_sample_files_use_firms_columns(sample):
    for name, df in sample.items():
        bright = "bright_ti4" if SAMPLE_FILES[name] == "VIIRS" else "brightness"
        for col in ["latitude", "longitude", bright, "acq_date", "acq_time", "satellite",
                    "instrument", "confidence", "frp", "daynight", "type"]:
            assert col in df.columns, (name, col)
        assert set(df.instrument) == {SAMPLE_FILES[name]}


def test_sample_covers_window_and_both_sensors(sample):
    years = set()
    for df in sample.values():
        years |= set(pd.to_datetime(df.acq_date).dt.year)
    first = config.first_year()
    current = config.bands()["data_window"]["current_year"]
    assert years == set(range(first, current + 1))


def test_snpp_ends_and_noaa20_continues(sample):
    snpp = pd.to_datetime(sample["fire_archive_SV-C2_sample.csv.gz"].acq_date)
    n20 = pd.to_datetime(sample["fire_archive_J1V-C2_sample.csv.gz"].acq_date)
    assert snpp.max() <= pd.Timestamp("2026-11-02")
    assert n20.max() > pd.Timestamp("2026-11-02")


def test_sample_has_rows_cleaning_must_remove(sample):
    mod = sample["fire_archive_M-C61_sample.csv.gz"]
    assert (mod.type != 0).any() and (mod.confidence < 30).any()


processed = pytest.mark.skipif(not any(paths.HOTSPOTS_DIR.glob("year=*.parquet")),
                               reason="data/processed not built")


@processed
def test_processed_files_under_size_limit():
    limit = config.data_cfg()["processed"]["max_file_mb"] * 1e6
    files = list(paths.HOTSPOTS_DIR.glob("year=*.parquet")) + [paths.BOUNDARIES]
    assert all(f.stat().st_size < limit for f in files)


@processed
def test_processed_schema_and_meta():
    df = ingest.load_processed()
    meta = json.loads(paths.INGEST_META.read_text())
    assert list(df.columns) == ingest.SCHEMA
    assert meta["rows"] == len(df)
    assert set(df.province.astype(str)) <= set(config.data_cfg()["areas"])
    assert set(df.confidence.astype(str)) <= {"nominal", "high"}
    assert set(df.type.astype(int)) <= {0, -1}
    if meta["is_sample"]:
        assert set(df.source.astype(str)) == {"sample"}
