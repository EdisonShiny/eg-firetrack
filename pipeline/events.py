"""Fire events (docs/technical.md "The logic" 1).

Harmonized fire cells of the last 48 h within ~2 km form one fire event (DBSCAN, haversine,
eps = 2 km, min_samples = 3), so one fire gives one alert. Points DBSCAN leaves alone still form
an event when a ~2 km group of them has hotspots on 2 days in a row; the rest are Watch (map only).
An event keeps its ID when its centre moved < 5 km since the last run. Settings: config/forecast.yaml.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

from . import config

EARTH_KM = 6371.0088


def cfg() -> dict:
    return config.load("forecast.yaml")["events"]


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _dbscan(lat, lon, eps_km: float, min_samples: int) -> np.ndarray:
    if len(lat) == 0:
        return np.zeros(0, dtype=int)
    X = np.radians(np.column_stack([lat, lon]))
    return DBSCAN(eps=eps_km / EARTH_KM, min_samples=min_samples, metric="haversine",
                  algorithm="ball_tree").fit_predict(X)


def consecutive_days(days) -> bool:
    ds = sorted({pd.Timestamp(d).date() for d in days})
    return any((b - a).days == 1 for a, b in zip(ds, ds[1:]))


def cluster(cells: pd.DataFrame) -> np.ndarray:
    """Label per cell: event number 0..n-1, or -1 = Watch. `cells` has lat, lon, day."""
    c = cfg()
    if cells.empty:
        return np.zeros(0, dtype=int)
    lat, lon = cells["lat"].to_numpy(float), cells["lon"].to_numpy(float)
    lab = _dbscan(lat, lon, c["eps_km"], c["min_samples"])
    nxt = lab.max() + 1 if (lab >= 0).any() else 0
    noise = np.flatnonzero(lab < 0)
    if len(noise):
        sub = _dbscan(lat[noise], lon[noise], c["eps_km"], 1)
        days = cells["day"].to_numpy()[noise]
        for g in np.unique(sub):
            idx = noise[sub == g]
            if consecutive_days(days[sub == g]):
                lab[idx] = nxt
                nxt += 1
    # renumber 0..n-1 in order of first appearance
    out = np.full(len(lab), -1)
    for i, g in enumerate([g for g in pd.unique(lab) if g >= 0]):
        out[lab == g] = i
    return out


def _mode(s: pd.Series, w: pd.Series):
    return w.groupby(s.astype(str)).sum().idxmax()


def build(cells: pd.DataFrame, through: pd.Timestamp) -> tuple[list[dict], pd.DataFrame]:
    """Events from harmonized cells (columns: lat, lon, day, t (UTC), weight, frp, province,
    district, country). Returns (events, watch cells). Counts are harmonized (weighted) cells."""
    c = cfg()
    w = cells[cells["t"] > through - pd.Timedelta(hours=c["window_h"])].reset_index(drop=True)
    lab = cluster(w)
    w = w.assign(event=lab)
    last24 = w["t"] > through - pd.Timedelta(hours=24)
    events = []
    for g, e in w[w["event"] >= 0].groupby("event"):
        now = e[last24[e.index]]
        prev = e[~last24[e.index]]
        wt = e["weight"].astype(float)
        events.append({
            "lat": float(np.average(e["lat"], weights=wt)), "lon": float(np.average(e["lon"], weights=wt)),
            "hotspots_48h": float(wt.sum()),
            "hotspots_24h": float(now["weight"].sum()), "prev_24h": float(prev["weight"].sum()),
            "frp_sum_24h": float(now["frp"].fillna(0).sum()), "frp_max": float(e["frp"].max()),
            "province": _mode(e["province"], wt), "district": _mode(e["district"], wt),
            "country": _mode(e["country"], wt),
            "first_utc": e["t"].min(), "last_utc": e["t"].max(),
            "days": sorted(e["day"].astype(str).unique().tolist()),
            "cells": e[["lat", "lon"]].to_numpy(float).tolist(),
        })
    return events, w[w["event"] < 0]


def assign_ids(events: list[dict], previous: list[dict], day: date) -> list[dict]:
    """Keep an old ID when the nearest unclaimed previous centre is < keep_id_within_km away
    (closest pairs first); otherwise a new ID EV-YYYYMMDD-NNN."""
    lim = float(cfg()["keep_id_within_km"])
    pairs = []
    for i, e in enumerate(events):
        for j, p in enumerate(previous):
            d = float(haversine_km(e["lat"], e["lon"], p["lat"], p["lon"]))
            if d < lim:
                pairs.append((d, i, j))
    taken_e, taken_p = set(), set()
    for d, i, j in sorted(pairs):
        if i in taken_e or j in taken_p:
            continue
        events[i]["id"] = previous[j]["id"]
        events[i]["matched"] = previous[j]
        taken_e.add(i)
        taken_p.add(j)
    used = {p["id"] for p in previous} | {e["id"] for e in events if "id" in e}
    n = 1
    for e in sorted((e for e in events if "id" not in e), key=lambda e: (-e["hotspots_24h"], e["lat"])):
        while (eid := f"EV-{day:%Y%m%d}-{n:03d}") in used:
            n += 1
        e["id"] = eid
        e["matched"] = None
        used.add(eid)
    return events
