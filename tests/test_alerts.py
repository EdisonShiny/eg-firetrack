"""Phase 6 daily alerts end to end (fallback mode, synthetic data): events -> chance -> rules ->
reports, state between days (IDs, stability, closing, same-day re-run), next-day check, area status,
model.json; plus the situation report and the weather / haze helpers."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pipeline import alerts, config, forecast, reports, rules, weather
from pipeline import stats as st

PALANGKA = (-2.2161, 113.9135)
KM = 1 / 111.32
AREAS = ["central-kalimantan", "sarawak"]


def make_cells(event_days, n=12, lat0=PALANGKA[0] - 12 * KM, lon0=PALANGKA[1]):
    """History: 2 cells in Kapuas on 10 Sep of every full year. Event: n cells ~12 km south of
    Palangka Raya on each of `event_days` (05:00 UTC)."""
    rows = []
    for y in range(2017, 2026):
        for k in range(2):
            rows.append((f"{y}-09-10", -2.8 + k * 0.05, 113.2, 30.0))
    for d in event_days:
        for k in range(n):
            rows.append((d, lat0 + (k % 4) * 0.5 * KM, lon0 + (k // 4) * 0.5 * KM, 40.0))
    df = pd.DataFrame(rows, columns=["day", "lat", "lon", "frp"])
    df["t"] = pd.to_datetime(df["day"]) + pd.Timedelta(hours=5)
    df["year"] = df["t"].dt.year
    df["month"] = df["t"].dt.month
    df["weight"] = 1.0
    df["province"], df["district"], df["country"] = "Central Kalimantan", "Kapuas", "Indonesia"
    return df


WIND_EAST = {"dry_days": 19, "rain_next_mm": 2.0, "cloud_pct": 55, "wind_kmh": 10, "wind_from_deg": 270,
             "humidity_pct": 52, "temp_max_c": 34}


def run(cells, through, squares, state, wx=WIND_EAST):
    return alerts.build(cells, pd.Timestamp(through), squares, AREAS, forecaster=None,
                        weather_fn=lambda la, lo: [wx] * len(la), state=state, is_sample=True)


@pytest.fixture
def low_floor(monkeypatch):
    """The fixture history is only 2 cells a year; these tests check the alert pipeline, not the
    compared-to-normal floor (tested in test_stats.py), so use a floor of 1 cell here."""
    rule = {**st.cmp_rule(), "floor_cells": 1}
    monkeypatch.setattr(st, "cmp_rule", lambda: rule)


@pytest.fixture
def day1(squares, low_floor):
    c = make_cells(["2026-09-19", "2026-09-20"])
    return c, run(c, "2026-09-20 06:00", squares, {})


def test_build_fallback_critical_alert(day1):
    _, res = day1
    doc = res["doc"]
    assert doc["mode"] == forecast.FALLBACK and not doc["is_stub"]
    assert "fallback" in doc["note"]
    assert len(doc["alerts"]) == 1
    a = doc["alerts"][0]
    assert a["anomaly_status"] == "Unusual" and a["chance_source"] == "fallback"
    assert a["chance_72h_pct"] == 80 and a["chance_word"] == "Very likely"
    assert a["peat"] == "deep" and a["town"]["name"] == "Palangka Raya"
    assert a["town"]["km"] == pytest.approx(12, abs=1.5)
    assert a["haze"] == {"to_border": True, "country": "Malaysia"}
    assert a["level"] == 4 and a["level_name"] == "Critical"
    assert a["priority"]["rank"] == 1 and a["priority"]["share_pct"] == 100
    assert "ASMC and the neighbouring country" in a["coordination"]["also_inform"]
    assert "BNPB" in a["coordination"]["also_inform"]
    assert a["coordination"]["channel"] == rules.notification(4)["channel"]
    assert a["utc_offset_h"] == 7
    assert sum(a["score_parts"].values()) == pytest.approx(a["score"], abs=0.6)
    assert doc["counts"]["borneo"]["critical"] == 1 and doc["counts"]["central-kalimantan"]["critical"] == 1
    assert "Rescue priority P1: assign about 100%" in a["report"]["recommendation"]
    assert a["report"]["situation"].endswith("No rain for 19 days.")
    assert "(chance from compared-to-normal fallback)" in a["report"]["assessment"]
    assert any(x["town"] == "Palangka Raya" for x in a["nearby_teams"])


def test_state_keeps_id_holds_level_and_reruns_same(day1, squares):
    c, r1 = day1
    s1 = r1["state"]
    a1 = r1["doc"]["alerts"][0]
    # next day: no new hotspots -> score drops, level held (down only after 2 days below)
    r2 = run(c, "2026-09-21 06:00", squares, s1)
    a2 = r2["doc"]["alerts"][0]
    assert a2["id"] == a1["id"] and a2["issued_utc"] == a1["issued_utc"]
    assert a2["hotspots_24h"] == 0 and a2["days_without_hotspots"] == 1
    assert a2["level_computed"] < 4 and a2["level"] == 4 and a2["days_below"] == 1
    assert a2["status"] == config.bands()["alert_status"]["closing"]
    # same-day re-run with the new state gives the same answer
    r2b = run(c, "2026-09-21 06:00", squares, r2["state"])
    b = r2b["doc"]["alerts"][0]
    assert (b["id"], b["level"], b["days_below"], b["days_without_hotspots"]) == \
           (a2["id"], a2["level"], a2["days_below"], a2["days_without_hotspots"])


def test_alert_closes_after_three_days_without_hotspots(day1, squares):
    c, r = day1
    state = r["state"]
    for i, d in enumerate(["2026-09-21", "2026-09-22"], start=1):
        r = run(c, f"{d} 06:00", squares, state)
        state = r["state"]
        assert len(r["doc"]["alerts"]) == 1 and r["doc"]["alerts"][0]["days_without_hotspots"] == i
    r = run(c, "2026-09-23 06:00", squares, state)
    assert r["doc"]["alerts"] == [] and r["doc"]["closed_today"] == [state["events"][0]["id"]]


def test_no_weather_means_no_haze_and_honest_text(squares):
    c = make_cells(["2026-09-19", "2026-09-20"])
    r = run(c, "2026-09-20 06:00", squares, {}, wx=None)
    a = r["doc"]["alerts"][0]
    assert a["haze"]["to_border"] is False and a["weather"] is None
    assert a["report"]["situation"].endswith(config.bands()["report"]["rain_unknown"])
    assert r["doc"]["weather_note"]


def test_next_day_check_counts(day1):
    chk = day1[1]["check"]
    assert chk["days"] == 30
    assert chk["correct"] + chk["missed"] + chk["false_alarm"] == chk["cell_days"]


def test_last_check_result_words():
    assert alerts.check_word(0.6, True) == "correct"
    assert alerts.check_word(0.4, False) == "correct"
    assert alerts.check_word(0.4, True) == "missed"
    assert alerts.check_word(0.5, False) == "false_alarm"   # 50% is the cut-off


def test_anomalies_month_so_far_vs_median_same_days():
    d = pd.DataFrame([
        *[{"day": f"{y}-09-05", "province": "P", "district": "D", "weight": w} for y, w in
          zip(range(2017, 2026), [1, 2, 3, 4, 5, 6, 7, 8, 9])],
        {"day": "2020-09-25", "province": "P", "district": "D", "weight": 100.0},   # after the day: ignored
        {"day": "2026-09-03", "province": "P", "district": "D", "weight": 10.0},
    ])
    dt = pd.to_datetime(d["day"])
    d = d.assign(year=dt.dt.year, month=dt.dt.month, dom=dt.dt.day)
    an = alerts.anomalies(d, date(2026, 9, 21))
    assert an["district"][("P", "D")] == (10.0, [1, 2, 3, 4, 5, 6, 7, 8, 9])
    # district median 5 < floor 10 -> province baseline, also raised to the floor of 10 cells
    pct, status, basis = alerts.event_anomaly(an, "P", "D")
    assert pct == 0 and status == "Normal" and basis == "province"


def test_event_anomaly_district_when_median_reaches_floor():
    d = pd.DataFrame([
        *[{"day": f"{y}-09-05", "province": "P", "district": "D", "weight": 20.0} for y in range(2017, 2026)],
        {"day": "2026-09-03", "province": "P", "district": "D", "weight": 50.0},
    ])
    dt = pd.to_datetime(d["day"])
    d = d.assign(year=dt.dt.year, month=dt.dt.month, dom=dt.dt.day)
    pct, status, basis = alerts.event_anomaly(alerts.anomalies(d, date(2026, 9, 21)), "P", "D")
    assert pct == 150 and status == "Unusual" and basis == "district"


def test_base_state_same_day_rerun():
    prev = {"as_of": "2026-09-20", "events": [1]}
    today = {"as_of": "2026-09-21", "events": [2], "base": prev}
    assert alerts.base_state(today, date(2026, 9, 21)) == prev
    assert alerts.base_state(today, date(2026, 9, 22)) is today
    assert alerts.base_state({}, date(2026, 9, 22)) == {}


def test_area_risk_with_and_without_events(day1):
    res = day1[1]
    doc = res["doc"]
    ck = alerts.area_risk(doc["alerts"], {"province": "Central Kalimantan", "district": None}, res["area_cells"],
                          doc["mode"])
    assert ck["level"] == 4 and ck["score"] == doc["alerts"][0]["score"] and ck["events"] == 1
    assert ck["chance"]["pct"] == 80 and ck["people_nearby"]["value"] == "1"
    assert ck["fuel_type"]["value"] == config.bands()["fuel_words"]["deep"]
    sw = alerts.area_risk(doc["alerts"], {"province": "Sarawak", "district": None}, res["area_cells"], doc["mode"])
    assert sw["level"] == 1 and sw["score"] is None and sw["events"] == 0
    assert sw["note"] == config.bands()["rescue_risk_texts"]["no_events"]


def test_model_doc_without_model_is_fallback():
    m = alerts.model_doc(None, {"days": 30}, True)
    assert m["mode"] == forecast.FALLBACK and not m["is_stub"] and "pipeline.train" in m["note"]


def test_model_doc_reports_model_and_baselines():
    met = lambda a: {"auc": a, "hit_rate": 0.5, "false_alarm_rate": 0.4, "brier": 0.01, "n": 10, "positives": 2}
    h = {"model": met(0.9), "burned_yesterday": met(0.7), "usual_for_month": met(0.6), "beats_baselines": True,
         "rows": {"test": 10}}
    card = {"mode": "model", "mode_reason": "x", "version": "v1", "trained_at": "t", "is_sample": True,
            "split": {"test_year": 2025}, "features": [], "not_used": "", "model2": {}, "model1": {"3": h, "1": h}}
    m = alerts.model_doc(card, {"days": 30}, True)
    assert m["mode"] == "model" and m["model"]["auc"] == 0.9
    assert m["baselines"]["burned_yesterday"]["auc"] == 0.7 and m["baselines"]["usual_for_month"]["auc"] == 0.6
    assert set(m["horizons"]) == {"24h", "72h"} and "SAMPLE" in m["note"]


# --------------------------------------------------------------------------- situation report
def kapuas_alert(**kw):
    a = {"hotspots_24h": 41, "growth_pct": 48, "is_new": False, "peat": "deep",
         "town": {"name": "Kuala Kapuas", "km": 12}, "road_km": 3, "weather": {"dry_days": 19},
         "anomaly_pct": 280, "month": 9, "chance_72h_pct": 83, "score": 85, "level": 4, "level_name": "Critical",
         "priority": {"rank": 1, "share_pct": 20}, "chance_source": "model"}
    a.update(kw)
    return a


def test_report_kapuas():
    r = reports.build(kapuas_alert())
    assert r["situation"] == ("41 hotspots detected in the last 24 h (+48% vs yesterday), on deep peat. "
                              "Nearest town Kuala Kapuas 12 km; nearest road 3 km. No rain for 19 days.")
    assert r["assessment"] == ("Compared with a normal September, activity is 3.8× vs usual. The System gives a 83% chance "
                               "of further spreading within 72 hours (Very likely). Risk score 85/100 → Level 4 Critical.")
    assert r["recommendation"] == ("Immediate response required. Deploy within 2 hours. Rescue priority P1: assign "
                                   "about 20% of available rescue teams.")


def test_report_new_event_no_road_rain_today_not_critical():
    r = reports.build(kapuas_alert(is_new=True, road_km=None, weather={"dry_days": 0}, level=3, level_name="High",
                                   priority=None))
    assert "(new vs yesterday)" in r["situation"] and "no road data" in r["situation"]
    assert r["situation"].endswith("Rain in the last 24 h.")
    assert "Rescue priority" not in r["recommendation"]


# --------------------------------------------------------------------------- weather / haze
def test_weather_summary_dry_days_and_forecast():
    daily = {"precipitation_sum": [5, 0, 0.5, 0, 3, 4, 0, 1],      # 4 past days + today + 3 forecast
             "cloud_cover_mean": [0, 0, 0, 0, 60, 0, 0, 0]}
    w = weather.summarize(daily, today_index=4)
    assert w["dry_days"] == 0                                       # 3 mm today
    w = weather.summarize({"precipitation_sum": [5, 0, 0.5, 0, 0.2, 4, 0, 1]}, today_index=4)
    assert w["dry_days"] == 4 and w["rain_next_mm"] == 5.0


def test_fetch_failure_returns_none():
    class Boom:
        def get(self, *a, **k):
            raise OSError("down")
    assert weather.fetch([1.0, 2.0], [110.0, 111.0], session=Boom()) == [None, None]


def test_drift_goes_downwind():
    pts = weather.drift_points(0.0, 110.0, 10, 270)                 # wind from the west -> smoke drifts east
    assert pts[-1][1] > 110.0 and abs(pts[-1][0]) < 1e-6
    assert len(pts) == 18                                           # 10 km/h x 6 = 60 km/day x 3 days, every 10 km


def test_haze_needs_size_and_weather(squares):
    countries = squares.dissolve(by="country", as_index=False)[["country", "geometry"]]
    assert weather.haze_crosses(-2.5, 113.9, "Indonesia", 40, WIND_EAST, countries) == "Malaysia"
    assert weather.haze_crosses(-2.5, 113.9, "Indonesia", 5, WIND_EAST, countries) is None
    assert weather.haze_crosses(-2.5, 113.9, "Indonesia", 40, None, countries) is None
    west = dict(WIND_EAST, wind_from_deg=90)
    assert weather.haze_crosses(-2.5, 113.9, "Indonesia", 40, west, countries) is None
