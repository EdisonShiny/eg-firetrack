"""Phase 3 export: runs the exporter on data/processed into a temp folder and checks every file."""
import json
import subprocess
import sys

import pytest

from pipeline import config, export, ingest, paths
from pipeline import stats as st


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    if not paths.HARMONIZED_CELLS.exists():
        pytest.skip("run python -m pipeline.harmonize first")
    d = tmp_path_factory.mktemp("data")
    sizes = export.run(d)
    return d, sizes


def load(d, name):
    return json.loads((d / name).read_text(encoding="utf-8"))


def test_all_files_written(out):
    d, _ = out
    for name in ("meta.json", "bands.json", "places.json", "boundaries.json", "hotspots_30d.json",
                 "grid_12m.json", "grid_5y.json", "grid_all.json", "ranking.json", "alerts.json",
                 "model.json", "export/monthly.csv"):
        assert (d / name).exists(), name
    ids = ["borneo"] + [export.slug(a) for a in config.data_cfg()["areas"]] + \
          [export.slug(p["name"]) for p in config.load("places.yaml")["places"]]
    assert len(ids) == 26
    for i in ids:
        assert (d / "area" / f"{i}.json").exists(), i


def test_sizes_within_budget(out):
    _, sizes = out
    assert export.over_budget(sizes) == []


def test_meta_sample_and_window(out):
    d, _ = out
    m = load(d, "meta.json")
    assert m["is_sample"] is bool(ingest.read_meta().get("is_sample", True))   # follows data/processed
    assert m["data_window"]["median_years"] == [2017, 2025]
    assert m["stubs"] == [] and m["mode"] in ("model", "compared-to-normal fallback")
    assert m["data_through_myt"] and m["versions"]["rules"]
    assert m["periods_days"] == config.data_cfg()["export"]["periods_days"]   # the web reads windows from here


def test_meta_data_status_fields(out, monkeypatch):
    d, _ = out
    m = load(d, "meta.json")
    for k in ("archive_range", "archive_rows", "archive_is_real", "api_last_attempt", "api_last_success",
              "api_ok", "api_rows_by_source", "api_error", "archive_through", "newest_detection"):
        assert k in m, k
    assert m["api_fresh_hours"] == config.data_cfg()["firms"]["status_fresh_hours"]
    assert m["archive_is_real"] is (not m["is_sample"] and m["archive_rows"] > 0)
    assert m["newest_detection"].startswith(m["data_through_utc"][:13])
    key = __import__("os").environ.get("FIRMS_MAP_KEY", "").strip()
    if key:
        assert key not in (d / "meta.json").read_text(encoding="utf-8")


def test_archive_summary():
    """Range covers archive + NRT rows (the NRT CSVs in the archive zips and daily API appends)."""
    import pandas as pd
    hot = pd.DataFrame({"source": ["archive", "archive", "nrt"], "date": ["2017-01-02", "2026-08-31", "2026-11-09"]})
    assert export.archive_summary(hot, False) == {"range": ["2017-01-02", "2026-11-09"], "rows": 3, "is_real": True,
                                                  "archive_through": "2026-08-31"}
    assert export.archive_summary(hot, True)["is_real"] is False
    assert export.archive_summary(hot[hot.source == "nrt"], False)["archive_through"] is None
    assert export.archive_summary(hot.iloc[:0], False) == {"range": None, "rows": 0, "is_real": False,
                                                           "archive_through": None}


def test_bands_json_is_bands_yaml(out):
    d, _ = out
    assert load(d, "bands.json") == config.bands()


def test_alerts_and_model_json(out):
    """Phase 6: real alerts (levels, P-ranks, shares adding to 100) and the model check."""
    d, _ = out
    a, m, meta = load(d, "alerts.json"), load(d, "model.json"), load(d, "meta.json")
    assert not a["is_stub"] and a["is_sample"] == meta["is_sample"]
    assert ("SAMPLE" in a["note"]) == meta["is_sample"]
    assert a["mode"] == m["mode"] == meta["mode"]
    assert set(a["counts"]["borneo"]) == {r["name"].lower() for r in config.bands()["levels"]}
    total = sum(a["counts"]["borneo"].values())
    assert total == len(a["alerts"])
    assert total == sum(sum(a["counts"][x].values()) for x in a["counts"] if x != "borneo")
    crit = [x for x in a["alerts"] if x["level"] == 4]
    if crit:
        assert sum(x["priority"]["share_pct"] for x in crit) == 100
        assert sorted(x["priority"]["rank"] for x in crit) == list(range(1, len(crit) + 1))
    for x in a["alerts"]:
        assert x["level_name"] == next(r["name"] for r in config.bands()["levels"] if r["level"] == x["level"])
        assert set(x["report"]) == {"situation", "assessment", "recommendation"}
        assert x["actions"] and x["resources"]["rows"] and x["coordination"]["lead"]
        assert (x["priority"] is not None) == (x["level"] == 4)
    assert not m["is_stub"] and m["next_day_check"]["days"] == 30
    if m["mode"] == "model":
        assert m["beats_baselines"] and m["model"]["auc"] > m["baselines"]["burned_yesterday"]["auc"]
        assert m["model"]["brier"] < m["baselines"]["usual_for_month"]["brier"]
    else:
        assert "fallback" in m["mode"]


def test_places_area_and_district(out):
    d, _ = out
    p = load(d, "places.json")
    by = {x["id"]: x for x in p["places"]}
    assert by["miri"]["area"] == "sarawak" and by["miri"]["district"] == "miri"
    assert by["pulang-pisau"]["area"] == "central-kalimantan"
    juris = config.load("jurisdictions.json")["_places"]
    for x in p["places"]:
        assert export.slug(juris[x["name"]]) == x["area"]
    assert len(p["areas"]) == 9 and len(p["districts"]) == 116
    dist_ids = {x["id"] for x in p["districts"]}
    assert all(x["district"] in dist_ids for x in p["places"])
    assert p["custom_point_radius_km"] == config.load("places.yaml")["custom_point_radius_km"]


def test_boundaries_have_provinces_and_districts(out):
    d, _ = out
    f = load(d, "boundaries.json")["features"]
    levels = [x["properties"]["level"] for x in f]
    assert levels.count("province") == 8 and levels.count("district") == 116


def test_hotspots_30d_columns_align(out):
    d, _ = out
    h = load(d, "hotspots_30d.json")
    n = h["count"]
    for col in ("lat", "lon", "t", "sat", "frp", "conf", "bright", "area", "district"):
        assert len(h[col]) == n, col
    assert h["days"] == config.data_cfg()["export"]["points_max_days"] <= 30
    assert max(h["t"]) <= 31 * 24 * 60


def test_grids_and_ranking(out):
    d, _ = out
    for name in ("grid_12m", "grid_5y", "grid_all"):
        g = load(d, f"{name}.json")
        assert len(g["lat"]) == len(g["count"]) == len(g["area"])
    assert len(load(d, "grid_12m.json")["lat"]) <= len(load(d, "grid_all.json")["lat"])
    r = load(d, "ranking.json")
    assert len(r["districts"]) == 116
    assert {"now", "month", "year"} <= set(r["districts"][0])


def test_area_borneo_totals_match_sum_of_areas(out):
    d, _ = out
    b = load(d, "area/borneo.json")
    areas = [load(d, f"area/{export.slug(a)}.json") for a in config.data_cfg()["areas"]]
    tot = lambda a: sum(r["total"] for r in a["calendar"]["rows"])
    assert abs(tot(b) - sum(tot(a) for a in areas)) <= len(areas) * 10      # rounding per year/area


def test_calendar_shape_and_rules(out):
    d, _ = out
    a = load(d, "area/central-kalimantan.json")
    c = a["calendar"]
    assert c["years"] == st.all_years()
    assert all(len(r["cells"]) == 12 for r in c["rows"])
    y, mth = map(int, c["last_data_month"].split("-"))
    last = c["rows"][-1]["cells"]
    assert all(x is None for x in last[mth:])               # future months of 2026 = no data yet
    assert last[mth - 1]["partial"] is True
    assert len(c["bin_edges"]) == 8 and len(c["usual"]) == 12
    for r in c["rows"]:
        for m, cell in enumerate(r["cells"]):
            if cell:
                assert cell["unusual"] == st.is_unusual(cell["count"], c["usual"][m]["count"]) or \
                    abs(cell["count"] - 2 * c["usual"][m]["count"]) < 1     # rounding at the 2x edge
    # sample data: Central Kalimantan season in the dry months, El Nino years stand out
    assert set(c["fire_season"]["months"]) & {8, 9, 10}
    top2 = sorted((t for t in c["yearly_totals"] if not t["so_far"]), key=lambda t: -t["total"])[:2]
    assert {t["year"] for t in top2} == {2019, 2023}
    assert c["facts"]["record_year"]["year"] == 2019


def test_analysis_series_and_check(out):
    d, _ = out
    a = load(d, "area/borneo.json")["analysis"]
    n = len(a["months"])
    for s in ("modis_raw", "viirs_raw", "harmonized"):
        assert len(a["series"][s]["count"]) == len(a["series"][s]["frp"]) == n
    assert a["months"][0] == "2017-01"
    assert not a["prediction"]["is_stub"] and len(a["prediction"]["count"]) == 3
    assert a["prediction"]["count_method"] in ("model", "usual")
    assert [p["range_pct"] for p in a["prediction"]["count"]] == [15, 25, 35]
    hc = a["harmonization_check"]
    assert len(hc["harmonized"]) == len(st.all_years()) and hc["k"]
    tags = [r["tag"] for r in a["trend_summary"]]
    assert tags == ["PAST", "PAST", "NOW", "NOW", "NEXT", "DATA"]
    rr = a["rescue_risk"]
    assert not rr["is_stub"] and rr["level"] in (1, 2, 3, 4) and rr["tiles"]["fuel_type"]["value"]
    assert rr["tiles"]["people_nearby"]["value"].isdigit()


def test_summary_tiles(out):
    d, _ = out
    s = load(d, "area/borneo.json")["summary"]
    for k in ("now", "month", "year", "yearly_avg", "avg_frp", "compared_to_normal"):
        assert k in s
    assert s["count_by_period"]["current"] == s["now"]
    assert s["count_by_period"]["7d"] <= s["count_by_period"]["30d"] <= s["count_by_period"]["all"]
    cn = s["compared_to_normal"]
    assert cn["status"] == st.anomaly_status(cn["pct"])
    bw = s["compared_to_normal_by_window"]
    assert set(bw) == set(st.cmp_rule()["windows"]) and bw["month"] == cn
    floor = st.cmp_rule()["floor_cells"]
    for w in bw.values():                      # one function everywhere: floor, band and label agree
        assert w["usual"] >= floor and w["status"] == st.anomaly_status(w["pct"])
        # pct is stored rounded to a whole percent; the label comes from the exact value
        assert w["label"] in {st.vs_normal_label(w["pct"] + e) for e in (-0.5, 0, 0.49)}
    rr = load(d, "area/borneo.json")["analysis"]["rescue_risk"]["tiles"]["compared_to_normal"]
    assert rr["label"] == cn["label"]


def test_every_tile_ranking_and_calendar_use_harmonized_fire_cells(out):
    """One unit everywhere: the weighted harmonized fire cells in harmonized_cells.parquet."""
    import pandas as pd
    d, _ = out
    b = load(d, "area/borneo.json")
    s, cal, an = b["summary"], b["calendar"], b["analysis"]
    cells = pd.read_parquet(paths.HARMONIZED_CELLS, columns=["year", "month", "weight"])
    y, m = map(int, cal["last_data_month"].split("-"))
    year_cells = cells.loc[cells["year"] == y, "weight"].sum()
    by_year = cells[cells["year"].isin(st.median_years())].groupby("year")["weight"].sum()

    assert s["year"] == round(year_cells)                                   # This year tile
    assert s["month"] == round(cells.loc[(cells["year"] == y) & (cells["month"] == m), "weight"].sum())
    assert s["yearly_avg"] == round(by_year.mean()) == cal["facts"]["average_per_year"]
    cal_row = next(r for r in cal["rows"] if r["year"] == y)
    assert cal_row["total"] == s["year"]                                    # calendar
    assert cal_row["cells"][m - 1]["count"] == s["month"]
    assert abs(sum(an["series"]["harmonized"]["count"][-m:]) - s["year"]) <= m   # analysis (rounded per month)
    assert s["compared_to_normal_by_window"]["year"]["current"] == s["year"]   # compared to normal
    assert s["compared_to_normal_by_window"]["month"]["current"] == s["month"]
    r = load(d, "ranking.json")["districts"]                                # ranking (rounded per district)
    assert abs(sum(x["year"] for x in r) - s["year"]) <= len(r)
    assert abs(sum(x["month"] for x in r) - s["month"]) <= len(r)
    raw = ingest.load_processed()                                           # never raw detections
    assert s["year"] < (pd.to_datetime(raw["date_myt"].astype(str)).dt.year == y).sum()


def test_run_daily_accepts_workflow_command():
    """.github/workflows/daily.yml runs exactly: python -m pipeline.run_daily --export web/public/data"""
    wf = (paths.ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    assert "python -m pipeline.run_daily --export web/public/data" in wf
    r = subprocess.run([sys.executable, "-m", "pipeline.run_daily", "--help"], cwd=paths.ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0 and "--export" in r.stdout
