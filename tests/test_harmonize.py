"""Phase 2 harmonization rules (docs/technical.md Data D-E, docs/logic-explained.md section 1)."""
import json

import numpy as np
import pandas as pd
import pytest

from pipeline import harmonize as hz
from pipeline import paths


def det(lat, lon, sensor="VIIRS", satellite=None, when="2026-09-21 05:30", frp=10.0, type_=0,
        province="Central Kalimantan", district="Pulang Pisau", daynight="D"):
    t = pd.Timestamp(when)
    sat = satellite or ("S-NPP" if sensor == "VIIRS" else "Aqua")
    return dict(lat=lat, lon=lon, datetime_utc=t, date_myt=(t + pd.Timedelta(hours=8)).strftime("%Y-%m-%d"),
                sensor=sensor, satellite=sat, daynight=daynight, frp=frp, type=type_,
                country="Indonesia", province=province, district=district)


def frame(rows):
    return pd.DataFrame(rows)


def run(rows, static=()):
    d = hz.mask_static(hz.prepare(frame(rows)), static)
    return d, hz.merge(d)


# --------------------------------------------------------------------------- worked example: 2 and 9 -> 4
def worked_example_rows():
    """21 Sep 2026, Pulang Pisau. Fire A: 1 MODIS pixel, 9 VIIRS pixels over 3 cells.
    Fire B (~20 km away, under a cloud edge): 1 MODIS pixel, no VIIRS."""
    rows = [det(-2.7050, 114.2050, "MODIS", when="2026-09-21 05:40")]                 # fire A, MODIS
    for cell_lon in (114.2050, 114.2150, 114.2250):                                   # fire A, VIIRS: 3 cells
        for i in range(3):                                                            # 3 pixels each
            rows.append(det(-2.7050 + i * 0.002, cell_lon + i * 0.001, "VIIRS", when="2026-09-21 05:30"))
    rows.append(det(-2.7050, 114.3850, "MODIS", when="2026-09-21 05:40"))             # fire B, MODIS only
    return rows


def test_worked_example_raw_2_and_9_gives_4():
    d, h = run(worked_example_rows())
    assert (d.sensor == "MODIS").sum() == 2 and (d.sensor == "VIIRS").sum() == 9
    assert len(h) == 4
    assert sorted(h.seen_by) == ["MODIS", "VIIRS", "VIIRS", "both"]
    assert h.weight.sum() == 4


def test_worked_example_in_monthly_counts():
    d, h = run(worked_example_rows())
    m = hz.monthly_counts(d, h).set_index("sensor")["count"]
    assert m["MODIS"] == 2 and m["VIIRS"] == 9 and m["harmonized"] == 4


# --------------------------------------------------------------------------- grid / once per day
def test_cell_index_is_floor_of_hundredths_without_float_error():
    assert list(hz.cell_index([0.29, -2.705, 114.2, -0.001])) == [29, -271, 11420, -1]


def test_one_cell_counts_once_per_day_and_again_next_day():
    rows = [det(-2.701, 114.201), det(-2.702, 114.203), det(-2.704, 114.206, when="2026-09-21 06:20"),
            det(-2.701, 114.201, when="2026-09-22 05:30")]
    _, h = run(rows)
    assert len(h) == 2 and sorted(h.day) == ["2026-09-21", "2026-09-22"]


def test_snpp_and_noaa20_same_cell_same_day_count_once():
    rows = [det(-2.701, 114.201, satellite="S-NPP", when="2026-09-21 05:10"),
            det(-2.702, 114.202, satellite="NOAA-20", when="2026-09-21 06:00")]
    _, h = run(rows)
    assert len(h) == 1
    assert h.iloc[0].satellites == "NOAA-20,S-NPP" and h.iloc[0].n == 2


def test_two_viirs_satellites_in_different_cells_count_twice():
    rows = [det(-2.701, 114.201, satellite="S-NPP"), det(-2.701, 114.221, satellite="NOAA-20")]
    assert len(run(rows)[1]) == 2


# --------------------------------------------------------------------------- matching +-1 km, +-1 h
@pytest.mark.parametrize("dlon, dt_min, expected", [
    (0.009, 50, 1),     # within 1 km and 1 h -> same fire
    (0.0, 60, 1),       # exactly 1 h
    (0.0, 61, 1),       # more than 1 h apart but the same cell, same day -> counts once per day
    (0.009, 61, 2),     # next cell and more than 1 h apart -> different fires
    (0.015, 0, 2),      # more than 1 km apart
])
def test_match_window(dlon, dt_min, expected):
    v = det(-2.7055, 114.2055, "VIIRS", when="2026-09-21 05:30")
    t = pd.Timestamp("2026-09-21 05:30") + pd.Timedelta(minutes=dt_min)
    m = det(-2.7055, 114.2055 + dlon, "MODIS", when=str(t))
    _, h = run([v, m])
    assert len(h) == expected


def test_match_across_cell_border():
    """MODIS in the next cell but within 0.01 deg of a VIIRS pixel is the same fire."""
    v = det(-2.7001, 114.2099, "VIIRS")
    m = det(-2.7001, 114.2101, "MODIS", when="2026-09-21 05:40")
    _, h = run([v, m])
    assert len(h) == 1 and h.iloc[0].base_sensor == "VIIRS"


def test_terra_morning_and_viirs_afternoon_same_cell_count_once():
    """Terra (10:30 local) and VIIRS (13:30 local) over one fire cell on one day: one record, not two."""
    v = det(-2.7055, 114.2055, "VIIRS", satellite="NOAA-20", when="2026-09-21 05:30")
    m = det(-2.7041, 114.2062, "MODIS", satellite="Terra", when="2026-09-21 02:30")
    _, h = run([v, m])
    assert len(h) == 1 and h.iloc[0].base_sensor == "VIIRS" and h.iloc[0].seen_by == "both"


def test_harmonized_is_one_row_per_cell_per_day_on_a_mixed_day():
    """Any mix of MODIS (Terra, Aqua day/night) and VIIRS (S-NPP, NOAA-20) never repeats a day+cell."""
    rng = np.random.default_rng(7)
    rows = []
    for _ in range(400):
        sensor, sat = [("VIIRS", "S-NPP"), ("VIIRS", "NOAA-20"), ("MODIS", "Terra"), ("MODIS", "Aqua")][rng.integers(4)]
        hour = int(rng.choice([2, 5, 14, 17]))
        rows.append(det(-2.70 + rng.integers(20) * 0.01 + 0.004, 114.20 + rng.integers(20) * 0.01 + 0.004,
                        sensor, satellite=sat, when=f"2026-09-21 {hour:02d}:{int(rng.integers(60)):02d}"))
    _, h = run(rows)
    assert not h.duplicated(["day", "cell_lat", "cell_lon"]).any()


def test_merge_keeps_all_viirs_and_viirs_frp():
    v = det(-2.7055, 114.2055, "VIIRS", frp=12.0)
    m = det(-2.7055, 114.2055, "MODIS", when="2026-09-21 05:40", frp=80.0)
    _, h = run([v, m])
    assert len(h) == 1 and h.iloc[0].frp == 12.0 and h.iloc[0].seen_by == "both"


# --------------------------------------------------------------------------- calibration
def counts(rows):
    return pd.DataFrame(rows, columns=["province", "year", "month", "modis", "viirs"])


def test_k_calibration_example_26000_over_10000():
    """Ten Septembers in Central Kalimantan: VIIRS 26,000 cells, MODIS 10,000 -> k = 2.6."""
    c = counts([("Central Kalimantan", y, 9, 1000, 2600) for y in range(2016, 2026)])
    kt = hz.fit_k(c)
    assert kt["provinces"]["Central Kalimantan"]["dry"]["k"] == pytest.approx(2.6)
    assert hz.k_for(kt, "Central Kalimantan", 9) == pytest.approx(2.6)


def test_k_is_sum_ratio_per_province_and_season():
    c = counts([("Sarawak", 2018, 8, 100, 300), ("Sarawak", 2019, 9, 300, 600),     # dry: 900/400
                ("Sarawak", 2018, 1, 50, 100), ("Sarawak", 2019, 2, 50, 150)])     # wet: 250/100
    kt = hz.fit_k(c)
    assert kt["provinces"]["Sarawak"]["dry"]["k"] == pytest.approx(2.25)
    assert kt["provinces"]["Sarawak"]["wet"]["k"] == pytest.approx(2.5)


def test_k_falls_back_when_province_season_is_thin():
    c = counts([("Sarawak", 2018, 8, 100, 300), ("Sarawak", 2018, 1, 5, 50),          # wet too thin
                ("Sabah", 2018, 1, 100, 200)])
    kt = hz.fit_k(c)
    assert kt["provinces"]["Sarawak"]["wet"]["source"] == "province all seasons"
    assert kt["provinces"]["Sarawak"]["wet"]["k"] == pytest.approx(350 / 105, abs=1e-4)
    assert kt["provinces"]["Brunei"]["dry"]["source"] == "Borneo season"           # no Brunei data


def test_season_of_every_month():
    assert [hz.season_of(m) for m in range(1, 13)] == ["wet"] * 5 + ["dry"] * 5 + ["wet"] * 2


def test_calibration_uses_aqua_with_viirs_at_the_same_pass_only():
    rows = [
        det(-2.705, 114.205, "MODIS", "Aqua", "2026-09-21 05:40"),
        det(-2.805, 114.305, "MODIS", "Terra", "2026-09-21 02:40"),           # Terra: not a matching pass
        det(-2.705, 114.205, "VIIRS", "S-NPP", "2026-09-21 05:30"),
        det(-2.715, 114.215, "VIIRS", "NOAA-20", "2026-09-21 06:20"),         # inside +-1 h of the Aqua pass
        det(-2.905, 114.405, "VIIRS", "NOAA-20", "2026-09-21 08:00"),         # outside the pass window
        det(-2.705, 114.205, "MODIS", "Aqua", "2026-09-22 05:40"),            # no VIIRS at that pass
    ]
    c = hz.calibration_counts(hz.prepare(frame(rows)))
    assert c[["modis", "viirs"]].sum().tolist() == [1, 2]


def test_calibration_counts_two_viirs_satellites_in_one_cell_once():
    rows = [det(-2.705, 114.205, "MODIS", "Aqua", "2026-09-21 05:40"),
            det(-2.705, 114.205, "VIIRS", "S-NPP", "2026-09-21 05:30"),
            det(-2.706, 114.206, "VIIRS", "NOAA-20", "2026-09-21 06:20")]
    c = hz.calibration_counts(hz.prepare(frame(rows)))
    assert c[["modis", "viirs"]].sum().tolist() == [1, 1]


# --------------------------------------------------------------------------- gap fill: 40 x 2.6 = 104
def gap_day_rows(n=40):
    return [det(-2.0 - i * 0.05, 113.5, "MODIS", "Aqua", "2026-09-21 05:40") for i in range(n)]


def test_k_fill_40_modis_cells_times_2_6_is_104():
    d = hz.prepare(frame(gap_day_rows(40)))
    kt = hz.fit_k(counts([("Central Kalimantan", y, 9, 1000, 2600) for y in range(2016, 2026)]))
    gaps = hz.viirs_gap_days(d)
    assert gaps == {"2026-09-21"}
    h = hz.apply_gap_fill(hz.merge(d), gaps, kt)
    assert h.filled.all() and len(h) == 40
    assert h.weight.sum() == pytest.approx(104)
    m = hz.monthly_counts(d, h).set_index("sensor")["count"]
    assert m["harmonized"] == 104 and m["MODIS"] == 40


def test_no_gap_fill_when_viirs_has_data():
    rows = gap_day_rows(5) + [det(1.0, 116.0, "VIIRS", when="2026-09-21 05:30")]
    assert hz.viirs_gap_days(hz.prepare(frame(rows))) == set()


def test_quiet_day_with_few_modis_cells_is_not_a_gap():
    assert hz.viirs_gap_days(hz.prepare(frame(gap_day_rows(2)))) == set()


# --------------------------------------------------------------------------- static sources (NRT)
def test_static_mask_drops_unknown_type_near_static_cell_only():
    rows = [det(-2.7055, 114.2055, type_=-1), det(-2.7055, 114.2055, type_=0),
            det(-2.5055, 114.2055, type_=-1)]
    d = hz.mask_static(hz.prepare(frame(rows)), [[-271, 11420]])
    assert sorted(zip(d.type, d.lat.round(4))) == [(-1, -2.5055), (0, -2.7055)]


# --------------------------------------------------------------------------- leave-one-year-out
def test_leave_one_year_out_perfect_ratio_gives_r2_1_and_zero_error():
    rows = [(p, y, m, 10 * m, 25 * m) for p in ("Sarawak", "Sabah") for y in range(2017, 2026)
            for m in range(1, 13)]
    chk = hz.leave_one_year_out(counts(rows), range(2017, 2026))
    for res in [chk["borneo"], *chk["provinces"].values()]:
        assert res["r2"] == pytest.approx(1.0) and res["avg_error_pct"] == pytest.approx(0.0)
    assert set(chk["borneo"]["per_year"]) == {str(y) for y in range(2017, 2026)}


def test_leave_one_year_out_hides_the_test_year():
    """One odd year: its own k is not used, so its prediction misses (error > 0)."""
    rows = [("Sarawak", y, 9, 100, 300 if y == 2019 else 200) for y in range(2017, 2026)]
    chk = hz.leave_one_year_out(counts(rows), range(2017, 2026))
    assert chk["provinces"]["Sarawak"]["per_year"]["2019"]["predicted_viirs"] == pytest.approx(200)


def test_r2_helper():
    assert hz.r2([1, 2, 3], [1, 2, 3]) == 1.0
    assert hz.r2([1, 1], [1, 1]) is None


# --------------------------------------------------------------------------- committed outputs
def test_processed_outputs_exist_and_are_small():
    for p in (paths.HARMONIZED_CELLS, paths.MONTHLY_COUNTS, paths.CALIBRATION_K, paths.STATIC_CELLS):
        assert p.exists(), f"run python -m pipeline.harmonize ({p.name} missing)"
    for p in (paths.HARMONIZED_CELLS, paths.MONTHLY_COUNTS):
        assert p.stat().st_size / 1e6 < 90
    cols = set(pd.read_parquet(paths.MONTHLY_COUNTS).columns)
    assert {"province", "district", "year", "month", "sensor", "count", "frp_mean", "frp_high_count"} <= cols


def test_processed_harmonized_cells_are_one_row_per_cell_per_day():
    """The committed table itself: no day+cell appears twice (VIIRS + MODIS-only double count)."""
    h = pd.read_parquet(paths.HARMONIZED_CELLS, columns=["day", "cell_lat", "cell_lon"])
    assert not h.duplicated().any()


def test_calibration_file_flags_sample_and_has_k_per_province_season():
    doc = json.loads(paths.CALIBRATION_K.read_text(encoding="utf-8"))
    meta = json.loads(paths.INGEST_META.read_text(encoding="utf-8"))
    assert doc["is_sample"] == meta["is_sample"]
    for prov, by_season in doc["k"]["provinces"].items():
        assert set(by_season) == {"dry", "wet"}
        assert all(np.isfinite(v["k"]) and v["k"] > 0 for v in by_season.values())
