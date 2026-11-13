"""Phase 6 fire events: DBSCAN 2 km / 3 hotspots / 48 h, 2-days-in-a-row rule, Watch, stable IDs."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pipeline import events

THROUGH = pd.Timestamp("2026-09-21 06:00")
KM = 1 / 111.32                                   # ~1 km in degrees of latitude


def cells(points):
    """points: (lat, lon, hours_before_THROUGH[, weight, frp])"""
    rows = []
    for p in points:
        lat, lon, h = p[:3]
        w = p[3] if len(p) > 3 else 1.0
        frp = p[4] if len(p) > 4 else 10.0
        t = THROUGH - pd.Timedelta(hours=h)
        rows.append({"lat": lat, "lon": lon, "t": t, "day": str((t + pd.Timedelta(hours=8)).date()),
                     "weight": w, "frp": frp, "province": "Central Kalimantan", "district": "Kapuas",
                     "country": "Indonesia"})
    return pd.DataFrame(rows)


def test_haversine_one_degree_latitude():
    assert events.haversine_km(0, 0, 1, 0) == pytest.approx(111.2, abs=0.2)


def test_three_hotspots_within_2km_make_one_event():
    c = cells([(-2.5, 113.5, 2), (-2.5 + 1.5 * KM, 113.5, 3), (-2.5 + 3 * KM, 113.5, 4)])
    evs, watch = events.build(c, THROUGH)
    assert len(evs) == 1 and len(watch) == 0
    assert evs[0]["hotspots_24h"] == 3


def test_one_or_two_isolated_hotspots_are_watch():
    c = cells([(-2.5, 113.5, 2), (-2.5 + 1 * KM, 113.5, 3), (-1.0, 113.0, 1)])
    evs, watch = events.build(c, THROUGH)
    assert evs == [] and len(watch) == 3


def test_points_further_than_2km_do_not_join():
    c = cells([(-2.5, 113.5, 2), (-2.5 + 2.5 * KM, 113.5, 3), (-2.5 + 5 * KM, 113.5, 4)])
    evs, _ = events.build(c, THROUGH)
    assert evs == []


def test_two_days_in_a_row_make_an_event():
    # two hotspots ~1 km apart, one yesterday (MYT) and one today
    c = cells([(-2.5, 113.5, 30), (-2.5 + 1 * KM, 113.5, 2)])
    assert c["day"].nunique() == 2
    evs, watch = events.build(c, THROUGH)
    assert len(evs) == 1 and len(watch) == 0
    assert evs[0]["prev_24h"] == 1 and evs[0]["hotspots_24h"] == 1


def test_only_last_48h_count():
    c = cells([(-2.5, 113.5, 2), (-2.5 + KM, 113.5, 3), (-2.5 + 2 * KM, 113.5, 50)])
    evs, watch = events.build(c, THROUGH)
    assert evs == [] and len(watch) == 2


def test_event_numbers_weighted():
    c = cells([(-2.5, 113.5, 2, 2.6, 100), (-2.5 + KM, 113.5, 3, 1, 50), (-2.5 + 2 * KM, 113.5, 30, 1, 20)])
    ev = events.build(c, THROUGH)[0][0]
    assert ev["hotspots_24h"] == pytest.approx(3.6) and ev["prev_24h"] == 1
    assert ev["frp_sum_24h"] == 150 and ev["frp_max"] == 100
    assert ev["district"] == "Kapuas" and ev["province"] == "Central Kalimantan"


def test_two_separate_fires_two_events():
    a = [(-2.5 + i * KM, 113.5, 2) for i in range(3)]
    b = [(-1.5 + i * KM, 114.0, 2) for i in range(4)]
    evs, _ = events.build(cells(a + b), THROUGH)
    assert sorted(e["hotspots_24h"] for e in evs) == [3, 4]


def test_ids_kept_when_centre_moves_less_than_5km():
    prev = [{"id": "EV-20260920-001", "lat": -2.5, "lon": 113.5}]
    evs = [{"lat": -2.5 + 4 * KM, "lon": 113.5, "hotspots_24h": 5}]
    out = events.assign_ids(evs, prev, date(2026, 9, 21))
    assert out[0]["id"] == "EV-20260920-001" and out[0]["matched"] is prev[0]


def test_new_id_when_centre_moves_5km_or_more():
    prev = [{"id": "EV-20260920-001", "lat": -2.5, "lon": 113.5}]
    evs = [{"lat": -2.5 + 6 * KM, "lon": 113.5, "hotspots_24h": 5}]
    out = events.assign_ids(evs, prev, date(2026, 9, 21))
    assert out[0]["id"] == "EV-20260921-001" and out[0]["matched"] is None


def test_each_previous_id_used_once_closest_wins():
    prev = [{"id": "OLD", "lat": -2.5, "lon": 113.5}]
    evs = [{"lat": -2.5 + 3 * KM, "lon": 113.5, "hotspots_24h": 9},
           {"lat": -2.5 + 1 * KM, "lon": 113.5, "hotspots_24h": 2}]
    out = events.assign_ids(evs, prev, date(2026, 9, 21))
    assert out[1]["id"] == "OLD" and out[0]["id"].startswith("EV-20260921-")


def test_consecutive_days():
    assert events.consecutive_days(["2026-09-20", "2026-09-21"])
    assert not events.consecutive_days(["2026-09-19", "2026-09-21"])
    assert not events.consecutive_days(["2026-09-21"])
