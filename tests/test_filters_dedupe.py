from datetime import datetime

import pandas as pd

from pipeline import ingest

NOW = datetime(2026, 11, 9, 12, 0)


def raw(**over):
    base = dict(lat=-2.5, lon=113.5, date="2026-09-21", time_utc="05:30", sensor="VIIRS",
                satellite="S-NPP", confidence="nominal", frp=10.0, brightness=340.0,
                daynight="D", type=0, source="archive")
    base.update(over)
    return base


def std(*rows):
    return ingest.standardize(pd.DataFrame(list(rows)), NOW)


def test_keeps_vegetation_fires_only():
    df = std(raw(type=0), raw(type=1), raw(type=2), raw(type=3))
    assert list(df.type) == [0]


def test_nrt_unknown_type_is_kept():
    assert len(std(raw(type=-1, source="nrt"))) == 1


def test_low_confidence_dropped():
    df = std(raw(confidence="low"), raw(confidence="nominal"), raw(confidence="high"))
    assert sorted(df.confidence) == ["high", "nominal"]


def test_window_drops_before_first_year_and_future():
    df = std(raw(date="2016-12-31"), raw(date="2017-01-01"), raw(date="2026-11-10"))
    assert list(df.date) == ["2017-01-01"]


def test_dedupe_prefers_archive_over_nrt():
    df = std(raw(source="nrt", frp=1.0), raw(source="archive", frp=2.0),
             raw(source="archive", satellite="NOAA-20"))
    out = ingest.dedupe(df)
    assert len(out) == 2
    snpp = out[out.satellite == "S-NPP"].iloc[0]
    assert snpp.source == "archive" and snpp.frp == 2.0


def test_dedupe_keeps_different_time_or_place():
    df = std(raw(), raw(time_utc="05:31"), raw(lat=-2.51))
    assert len(ingest.dedupe(df)) == 3


def test_clean_end_to_end(squares):
    df = ingest.clean(pd.DataFrame([raw(), raw(lon=113.9, type=2), raw(lat=5.0, lon=200.0)]),
                      squares, NOW)
    assert len(df) == 1
    assert list(df.columns) == ingest.SCHEMA
    assert df.province.iloc[0] == "Central Kalimantan"


def _row(lat, lon, date, time, source="archive"):
    return {"lat": lat, "lon": lon, "date": date, "time_utc": time, "sensor": "VIIRS", "satellite": "S-NPP",
            "source": source, "datetime_utc": pd.Timestamp(f"{date} {time}"), "confidence": "nominal",
            "frp": 1.0, "brightness": 300.0, "daynight": "D", "type": 0, "date_myt": date,
            "time_myt": pd.Timestamp(f"{date} {time}"), "country": "Indonesia", "province": "Central Kalimantan",
            "district": "Kapuas"}


def test_dedupe_is_stable_after_float32_storage():
    """Two points that differ only below float32 precision are one row both before and after storage."""
    df = pd.DataFrame([_row(-2.123450001, 113.5, "2022-09-01", "05:30"),
                       _row(-2.123449999, 113.5, "2022-09-01", "05:30")])
    fresh = ingest.dedupe(df)
    stored = ingest.dedupe(ingest.finalize(fresh).astype({c: str for c in ingest.CATEGORIES}))
    assert len(fresh) == len(stored)


def test_merge_new_leaves_untouched_years_alone():
    """--update only rewrites the years of the new rows, so it must not dedupe other years either."""
    old = pd.DataFrame([_row(-2.5, 113.5, "2022-09-01", "05:30"), _row(-2.5, 113.5, "2022-09-01", "05:30"),
                        _row(-2.6, 113.6, "2026-11-08", "05:30")])
    new = pd.DataFrame([_row(-2.6, 113.6, "2026-11-08", "05:30", "nrt"), _row(-2.7, 113.7, "2026-11-09", "05:30", "nrt")])
    merged, years = ingest.merge_new(ingest.finalize(old), ingest.finalize(new))
    assert years == {2026}
    assert (merged["date"] == "2022-09-01").sum() == 2          # old year kept exactly as stored
    assert (merged["date"].str.startswith("2026")).sum() == 2   # duplicate across old/new removed
    assert set(merged.loc[merged["date"] == "2026-11-08", "source"]) == {"archive"}


# --------------------------------------------------------------------------- archive + NRT overlap
def _firms(source_rows, acq_time, lat="-2.6169"):
    """One FIRMS VIIRS row as the archive zip / NRT zip / area API deliver it."""
    return pd.DataFrame([{"latitude": lat, "longitude": "113.9380", "bright_ti4": "340.1", "acq_date": "2026-11-08",
                          "acq_time": acq_time, "satellite": "N20", "instrument": "VIIRS", "confidence": "n",
                          "version": source_rows, "frp": "5.2", "daynight": "D"}])


def test_same_detection_in_archive_nrt_zip_and_api_counts_once(squares):
    """The archive overlap (and the NRT zip vs the area API copy of the same pass) is counted once,
    even when one file writes acq_time 510 and the other 0510, or lat -2.6169 vs -2.61690."""
    from pipeline import harmonize as hz
    raw = pd.concat([
        ingest.normalize_raw(_firms("2", "510"), "archive"),
        ingest.normalize_raw(_firms("2.0NRT", "0510", lat="-2.61690"), "nrt"),   # NRT zip
        ingest.normalize_raw(_firms("2.0NRT", "0510"), "nrt"),                  # area API cache
    ], ignore_index=True)
    df = ingest.clean(raw, squares, NOW)
    assert len(df) == 1 and df.source.iloc[0] == "archive"
    assert len(hz.merge(hz.prepare(df))) == 1


def test_update_does_not_double_count_rows_already_in_the_archive():
    """--update fetches the last days again; rows already stored (archive or earlier NRT) stay single."""
    old = pd.DataFrame([_row(-2.6, 113.6, "2026-11-08", "05:10"), _row(-2.6, 113.7, "2026-11-08", "05:10", "nrt")])
    new = pd.DataFrame([_row(-2.6, 113.6, "2026-11-08", "05:10", "nrt"), _row(-2.6, 113.7, "2026-11-08", "05:10", "nrt")])
    merged, _ = ingest.merge_new(ingest.finalize(old), ingest.finalize(new))
    assert len(merged) == 2
