"""Write every JSON file the website reads (docs/progress.md section 2) into --export DIR.

    python -m pipeline.export --out web/public/data

Reads only data/processed (harmonized_cells.parquet, hotspots/, calibration_k.json,
boundaries.geojson, static_cells.json) and config/, so the daily Action needs no data/raw.
All counts are harmonized fire cells unless a field says modis_raw / viirs_raw.
alerts.json / model.json come from pipeline/alerts.py (events, 72-hour forecast, rules) and the
committed models in data/processed/models (pipeline/train.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import alerts as al
from . import config, forecast, geo, harmonize, ingest, paths
from . import stats as st

log = logging.getLogger(__name__)

MYT = pd.Timedelta(hours=int(config.data_cfg()["local_utc_offset_h"]))


def ecfg() -> dict:
    return config.data_cfg()["export"]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def _i(x) -> int:
    return int(round(float(x)))


def _num(x, nd=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x), nd)


def _fmt(n) -> str:
    return f"{_i(n):,}"


def dump(path: Path, obj) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False),
                    encoding="utf-8")
    return path.stat().st_size / 1024


# --------------------------------------------------------------------------- inputs
def archive_summary(hot: pd.DataFrame, is_sample: bool) -> dict:
    """The full history behind the site: rows from the FIRMS archive download (science-quality
    "archive" CSVs plus the "nrt" CSVs in the same zips) and the daily API appends.
    `range` covers all of them; `archive_through` is the last day of science-quality data."""
    if hot.empty:
        return {"range": None, "rows": 0, "is_real": False, "archive_through": None}
    dates = hot["date"].astype(str)
    sci = dates[hot["source"].astype(str) == "archive"]
    return {"range": [dates.min(), dates.max()], "rows": int(len(hot)), "is_real": not is_sample,
            "archive_through": sci.max() if len(sci) else None}


def data_status_fields(data: "Data", api: dict) -> dict:
    """meta.json fields for the top-bar Data status button (API status from data/processed/api_status.json)."""
    f = config.data_cfg()["firms"]
    newest = data.newest_detection
    return {
        "archive_range": data.archive["range"],
        "archive_rows": data.archive["rows"],
        "archive_is_real": data.archive["is_real"],
        "archive_through": data.archive["archive_through"],
        "api_last_attempt": api.get("api_last_attempt"),
        "api_last_success": api.get("api_last_success"),
        "api_ok": api.get("api_ok"),
        "api_rows_by_source": api.get("api_rows_by_source", {}),
        "api_error": api.get("api_error"),
        "api_fresh_hours": int(f["status_fresh_hours"]),
        "api_note": f.get("status_note"),
        "newest_detection": None if pd.isna(newest) else newest.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


class Data:
    """Everything export needs, loaded once."""

    def __init__(self):
        hot = ingest.load_processed()
        if hot.empty:
            raise FileNotFoundError("data/processed/hotspots is empty: run python -m pipeline.ingest --rebuild")
        self.is_sample = bool(ingest.read_meta().get("is_sample", True))
        self.archive = archive_summary(hot, self.is_sample)
        self.newest_detection = pd.to_datetime(hot["datetime_utc"]).max()
        static = harmonize.load_static_cells()
        d = harmonize.mask_static(harmonize.prepare(hot), static)
        self.sensor_cells = harmonize.fire_cells(d)                 # raw fire cells per sensor per day
        self.cells = pd.read_parquet(paths.HARMONIZED_CELLS)
        for c in ("day", "province", "district", "base_sensor", "country"):
            self.cells[c] = self.cells[c].astype(str)
        self.cells["t"] = pd.to_datetime(self.cells["first_time_utc"])
        self.cells["dom"] = self.cells["day"].str[8:10].astype(int)
        self.hot = hot
        self.static = static
        self.through = pd.Timestamp(d["t"].max())                   # latest detection, UTC
        self.through_myt = self.through + MYT
        self.calib = json.loads(paths.CALIBRATION_K.read_text(encoding="utf-8")) \
            if paths.CALIBRATION_K.exists() else {}
        self.boundaries = geo.load_boundaries()
        self.areas = config.data_cfg()["areas"]


# --------------------------------------------------------------------------- scopes
def scopes(data: Data, places: list[dict]) -> list[dict]:
    """Borneo + 8 areas + preset places (each place = the district that contains the town)."""
    out = [{"id": "borneo", "name": "Whole Borneo", "kind": "borneo", "province": None, "district": None}]
    out += [{"id": slug(a), "name": a, "kind": "area", "province": a, "district": None} for a in data.areas]
    out += [{"id": p["id"], "name": p["name"], "kind": "place", "province": p["province"],
             "district": p["district_name"]} for p in places]
    return out


def select(df: pd.DataFrame, scope: dict) -> pd.DataFrame:
    if scope["province"] is None:
        return df
    m = df["province"].astype(str) == scope["province"]
    if scope["district"] is not None:
        m &= df["district"].astype(str) == scope["district"]
    return df[m]


# --------------------------------------------------------------------------- time helpers
class Clock:
    def __init__(self, through: pd.Timestamp):
        self.through = through
        myt = through + MYT
        self.year, self.month, self.dom = myt.year, myt.month, myt.day
        if self.month == 1:
            self.last_full = (self.year - 1, 12)
        else:
            self.last_full = (self.year, self.month - 1)

    def since(self, days: float) -> pd.Timestamp:
        return self.through - pd.Timedelta(days=days)

    def is_future(self, y: int, m: int) -> bool:
        return (y, m) > (self.year, self.month)

    def months_series(self) -> list[tuple[int, int]]:
        return [(y, m) for y in st.all_years() for m in st.MONTHS if not self.is_future(y, m)]


def window(df: pd.DataFrame, clock: Clock, days: float | None, col: str = "t") -> pd.DataFrame:
    if days is None:
        return df
    return df[df[col] > clock.since(days)]


# --------------------------------------------------------------------------- one scope
def compare_windows(hc: pd.DataFrame, clock: Clock) -> dict:
    """Compared to normal for every window in bands.yaml compared_to_normal_rule.windows, with
    harmonized fire cells on both sides (st.compare_to_normal + st.same_window)."""
    counter = st.WindowCounter(hc["t"] + MYT, hc["weight"])
    end = clock.through + MYT
    out = {}
    for kind in st.cmp_rule()["windows"]:
        cur, past, info = st.same_window(counter, kind, end)
        r = st.compare_to_normal(cur, past)
        out[kind] = {"pct": None if r["pct"] is None else st.round_half_up(r["pct"]),
                     "ratio": None if r["ratio"] is None else round(r["ratio"], 2),
                     "status": r["status"], "label": r["label"],
                     "current": _i(r["current"]), "usual": _num(r["baseline"]), "median": _num(r["median"]),
                     "floored": r["floored"], "years": info["years"], "window": kind,
                     "basis": st.window_basis(kind, info, r)}
    return out


def summary(hc: pd.DataFrame, clock: Clock, grid: pd.DataFrame) -> dict:
    periods = dict(ecfg()["periods_days"])
    by_period, frp_by_period = {}, {}
    for name, days in list(periods.items()) + [("all", None)]:
        w = window(hc, clock, days)
        by_period[name] = _i(w["weight"].sum())
        frp_by_period[name] = _num(w["frp"].mean()) if len(w) else None
    this_month = hc[(hc["year"] == clock.year) & (hc["month"] == clock.month)]
    mtd = float(this_month["weight"].sum())
    cmp = compare_windows(hc, clock)
    last7 = float(window(hc, clock, 7)["weight"].sum())
    prev7 = float(hc[(hc["t"] > clock.since(14)) & (hc["t"] <= clock.since(7))]["weight"].sum())
    weekly = [float(hc[(hc["t"] > clock.since(7 * (k + 1))) & (hc["t"] <= clock.since(7 * k))]["weight"].sum())
              for k in (3, 2, 1, 0)]
    return {
        "now": by_period["current"],
        "month": _i(mtd),
        "year": _i(hc[hc["year"] == clock.year]["weight"].sum()),
        "yearly_avg": _i(st.yearly_average(grid)),
        "avg_frp": frp_by_period["30d"],
        "avg_frp_by_period": frp_by_period,
        "count_by_period": by_period,
        # default = this month so far (Analysis risk band, alerts); the Map picks by period
        "compared_to_normal": cmp["month"],
        "compared_to_normal_by_window": cmp,
        "sudden_increase": {"flag": st.sudden_increase(last7, prev7), "last7": _i(last7), "prev7": _i(prev7)},
        "recent_direction": st.week_on_week(weekly),
    }


def calendar(grid: pd.DataFrame, clock: Clock) -> dict:
    usual = st.usual_months(grid)
    years = list(grid.index)
    shown = [grid.loc[y, m] for y in years for m in st.MONTHS if not clock.is_future(y, m)]
    edges = st.quantile_edges(shown)
    rows = []
    for y in years:
        cells = []
        for m in st.MONTHS:
            if clock.is_future(y, m):
                cells.append(None)
                continue
            v = float(grid.loc[y, m])
            cells.append({"count": _i(v), "bin": st.bin_index(v, edges),
                          "ratio": st.ratio_to_usual(v, usual[m]), "unusual": st.is_unusual(v, usual[m]),
                          "partial": (y, m) == (clock.year, clock.month)})
        rows.append({"year": y, "cells": cells, "total": _i(grid.loc[y].sum()),
                     "so_far": y == clock.year})
    full = st.median_years()
    totals = {y: float(grid.loc[y].sum()) for y in years}
    avg = st.yearly_average(grid)
    season = st.fire_season(usual, grid)
    unusual = [(y, m) for y in years for m in st.MONTHS
               if not clock.is_future(y, m) and st.is_unusual(grid.loc[y, m], usual[m])]
    ly, lm = clock.last_full
    span = list(range(1, lm + 1)) if ly == clock.year else []
    cur_sofar = float(grid.loc[clock.year, span].sum()) if span else None
    prev_sofar = float(grid.loc[clock.year - 1, span].sum()) if span and clock.year - 1 in grid.index else None
    full_tot = {y: totals[y] for y in full if y in totals}
    record = max(full_tot, key=full_tot.get) if full_tot else None
    quiet = min(full_tot, key=full_tot.get) if full_tot else None
    peak_m, quiet_m = int(usual.idxmax()), int(usual.idxmin())

    def per_year(y):
        vals = [None if clock.is_future(y, m) else float(grid.loc[y, m]) for m in st.MONTHS]
        known = [(m, v) for m, v in zip(st.MONTHS, vals) if v is not None]
        pk = max(known, key=lambda t: t[1])[0] if known and max(v for _, v in known) > 0 else None
        return {"year": y, "total": _i(totals[y]), "so_far": y == clock.year,
                "vs_avg_pct": None if y == clock.year else
                (None if st.anomaly_pct(totals[y], avg) is None else st.round_half_up(st.anomaly_pct(totals[y], avg))),
                "peak_month": pk, "unusual_months": sum(1 for (yy, _) in unusual if yy == y)}

    return {
        "years": years, "months": st.MONTH_ABBR, "rows": rows,
        "usual": [{"count": _num(usual[m]), "bin": st.bin_index(float(usual[m]), edges)} for m in st.MONTHS],
        "usual_years": [full[0], full[-1]],
        "bin_edges": edges,
        "yearly_totals": [{"year": y, "total": _i(totals[y]), "so_far": y == clock.year,
                           "record": y == record} for y in years],
        "fire_season": season,
        "season_strength": st.season_strength(usual),
        "facts": {
            "record_year": None if record is None else {"year": record, "total": _i(full_tot[record])},
            "quietest_year": None if quiet is None else {"year": quiet, "total": _i(full_tot[quiet])},
            "peak_month": {"month": peak_m, "usual": _num(usual[peak_m])},
            "quietest_month": {"month": quiet_m, "usual": _num(usual[quiet_m])},
            "average_per_year": _i(avg),
            "so_far_vs_prev": {
                "year": clock.year, "prev": clock.year - 1,
                "span": f"Jan–{st.MONTH_ABBR[lm - 1]}" if span else None,
                "current": None if cur_sofar is None else _i(cur_sofar),
                "previous": None if prev_sofar is None else _i(prev_sofar),
                "pct": None if cur_sofar is None or st.pct_change(cur_sofar, prev_sofar or 0) is None
                else st.round_half_up(st.pct_change(cur_sofar, prev_sofar))},
            "unusual_months": {"count": len(unusual),
                               "latest": None if not unusual else f"{st.MONTH_ABBR[unusual[-1][1] - 1]} {unusual[-1][0]}"},
            "season_strength": st.season_strength(usual),
        },
        "per_year": [per_year(y) for y in years],
        "last_data_month": f"{clock.year}-{clock.month:02d}",
        "partial_month": f"{clock.year}-{clock.month:02d}",
    }


def monthly_series(df: pd.DataFrame, weight: str | None, clock: Clock) -> tuple[list, list]:
    if len(df):
        g = df.assign(_w=df[weight] if weight else 1.0).groupby(["year", "month"])
        cnt, frp = g["_w"].sum(), g["frp"].mean()
    else:
        cnt, frp = pd.Series(dtype=float), pd.Series(dtype=float)
    counts, frps = [], []
    for y, m in clock.months_series():
        counts.append(_i(cnt.get((y, m), 0.0)))
        frps.append(_num(frp.get((y, m), np.nan)))
    return counts, frps


def k_overall(calib: dict, province: str | None) -> float | None:
    k = calib.get("k", {})
    if province is None:
        return k.get("borneo_all")
    p = k.get("provinces", {}).get(province)
    if not p:
        return None
    m = sum(s["modis_cells"] for s in p.values())
    v = sum(s["viirs_cells"] for s in p.values())
    return round(v / m, 2) if m else round(float(np.mean([s["k"] for s in p.values()])), 2)


def analysis(hc: pd.DataFrame, sc: pd.DataFrame, grid: pd.DataFrame, clock: Clock, scope: dict,
             calib: dict, summ: dict, monthly=None, risk: dict | None = None) -> dict:
    months = [f"{y}-{m:02d}" for y, m in clock.months_series()]
    h_cnt, h_frp = monthly_series(hc, "weight", clock)
    m_cnt, m_frp = monthly_series(sc[sc["sensor"] == "MODIS"], None, clock)
    v_cnt, v_frp = monthly_series(sc[sc["sensor"] == "VIIRS"], None, clock)
    usual = st.usual_months(grid)
    # usual FRP: median over the full years that had fires in that month (no fires = no FRP, not 0)
    full = hc[hc["year"].isin(st.median_years())]
    frp_ym = full.groupby(["year", "month"])["frp"].mean()
    usual_frp = frp_ym.groupby(level="month").median().reindex(st.MONTHS).fillna(0.0)
    nxt = []
    y, m = clock.year, clock.month
    for _ in range(3):
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        nxt.append((y, m))
    mp = None
    if monthly is not None and len(hc):
        mp = monthly.predict(hc, clock.last_full)
        if [tuple(x) for x in mp["months"]] != nxt:
            mp = None
    pred_cnt = st.prediction_band(mp["count"] if mp else [usual[mm] for _, mm in nxt])
    pred_frp = st.prediction_band(mp["frp"] if mp else [usual_frp[mm] for _, mm in nxt])
    uses_model = bool(mp and mp["count_method"] == "model")
    for p, (yy, mm) in zip(pred_cnt, nxt):
        p["month"] = f"{yy}-{mm:02d}"
    for p, (yy, mm) in zip(pred_frp, nxt):
        p["month"] = f"{yy}-{mm:02d}"

    # harmonization check: Jan .. last full month of every year, 3 series
    ly, lm = clock.last_full
    span = list(range(1, lm + 1))
    def span_totals(df, weight):
        x = df[df["month"].isin(span)]
        w = x[weight] if weight else pd.Series(1.0, index=x.index)
        g = w.groupby(x["year"]).sum()
        return [_i(g.get(yy, 0.0)) for yy in st.all_years()]
    chk_src = calib.get("check", {})
    chk = chk_src.get("borneo", {}) if scope["province"] is None else chk_src.get("provinces", {}).get(scope["province"], {})
    k = k_overall(calib, scope["province"])

    texts = st.B()["texts"]
    tags = texts["tags"]
    trend = []
    if len(hc) and max(h_cnt) > 0:
        i = int(np.argmax(h_cnt))
        py, pm = clock.months_series()[i]
        full_tot = {yy: float(grid.loc[yy].sum()) for yy in st.median_years()}
        top = sorted(full_tot, key=full_tot.get, reverse=True)[:2]
        trend.append({"tag": tags["past"], **_t(texts["peak_in_view"], month=st.MONTH_ABBR[pm - 1], year=py,
                                                 count=_fmt(h_cnt[i]), top_years=" and ".join(map(str, sorted(top))))})
    # last 12 full months vs average year
    series = dict(zip(clock.months_series(), h_cnt))
    idx = clock.months_series().index(clock.last_full) if clock.last_full in series else None
    avg = st.yearly_average(grid)
    if idx is not None and idx >= 11:
        last12 = sum(h_cnt[idx - 11: idx + 1])
        trend.append({"tag": tags["past"], **_t(texts["last_12_months"], pct=st.signed_pct(st.anomaly_pct(last12, avg)),
                                                 count=_fmt(last12), avg=_fmt(avg), first=st.median_years()[0],
                                                 last=st.median_years()[-1])})
    if idx is not None:
        cur = h_cnt[idx]
        u = float(usual[lm])
        a = st.anomaly_pct(cur, u)
        trend.append({"tag": tags["now"], **_t(texts["month_vs_normal"], month_name=st.MONTH_NAME[lm - 1], year=ly,
                                                pct=st.signed_pct(a), count=_fmt(cur), usual=_fmt(u),
                                                status=st.anomaly_status(a) or texts["no_data"])})
    sofar = calendar_sofar(grid, clock)
    if sofar:
        trend.append({"tag": tags["now"], **_t(texts["year_so_far"], **sofar)})
    trend.append({"tag": tags["next"], **_t(texts["next_months_model" if uses_model else "next_months"], m1=_fmt(pred_cnt[0]["value"]),
                                             m2=_fmt(pred_cnt[1]["value"]), m3=_fmt(pred_cnt[2]["value"]),
                                             names=", ".join(st.MONTH_ABBR[mm - 1] for _, mm in nxt))})
    if k:
        trend.append({"tag": tags["data"], **_t(texts["data_note"], k=f"{k:.1f}")})

    cn = summ["compared_to_normal"]
    rd = summ["recent_direction"]
    return {
        "months": months,
        "now_index": len(months) - 1,
        "series": {
            "modis_raw": {"count": m_cnt, "frp": m_frp},
            "viirs_raw": {"count": v_cnt, "frp": v_frp},
            "harmonized": {"count": h_cnt, "frp": h_frp},
        },
        "series_note": "MODIS raw / VIIRS raw = each sensor's own 1 km fire cells per day before merging; "
                       "harmonized = VIIRS + MODIS-only cells, VIIRS gap days filled with MODIS x k.",
        "prediction": {
            "is_stub": False,
            "count_method": "model" if uses_model else "usual",
            "frp_method": "model" if (mp and mp["frp_method"] == "model") else "usual",
            "method": texts["prediction_model"] if uses_model else texts["prediction_usual"],
            "count": pred_cnt, "frp": pred_frp,
        },
        "trend_summary": trend,
        "harmonization_check": {
            "span": f"Jan–{st.MONTH_ABBR[lm - 1]}", "span_months": span, "years": st.all_years(),
            "modis_raw": span_totals(sc[sc["sensor"] == "MODIS"], None),
            "viirs_raw": span_totals(sc[sc["sensor"] == "VIIRS"], None),
            "harmonized": span_totals(hc, "weight"),
            "r2": chk.get("r2"), "avg_error_pct": chk.get("avg_error_pct"), "k": k,
            "check_scope": "Whole Borneo" if scope["province"] is None else scope["province"],
        },
        "rescue_risk": rescue_risk(cn, rd, risk),
    }


def rescue_risk(cn: dict, rd: dict, risk: dict | None) -> dict:
    tiles = {"compared_to_normal": {"pct": cn["pct"], "status": cn["status"], "label": cn["label"],
                                    "basis": cn["basis"]},
             "recent_direction": {"pct": rd["pct"], "word": rd["word"], "rising_weeks": rd["rising_weeks"]}}
    if risk is None:
        return {"is_stub": True, "note": "No alert run.", "level": None, "level_name": None, "score": None,
                "directive": None, "tiles": {**tiles, "chance_of_spreading": {"pct": None, "word": None},
                                             "fuel_type": None, "people_nearby": None}}
    return {"is_stub": False, "mode": risk["mode"], "note": risk["note"], "level": risk["level"],
            "level_name": risk["level_name"], "score": risk["score"], "directive": risk["directive"],
            "events": risk["events"],
            "tiles": {**tiles, "chance_of_spreading": risk["chance"], "fuel_type": risk["fuel_type"],
                      "people_nearby": risk["people_nearby"]}}


def calendar_sofar(grid: pd.DataFrame, clock: Clock) -> dict | None:
    ly, lm = clock.last_full
    if ly != clock.year or clock.year - 1 not in grid.index:
        return None
    span = list(range(1, lm + 1))
    cur, prev = float(grid.loc[clock.year, span].sum()), float(grid.loc[clock.year - 1, span].sum())
    return {"year": clock.year, "prev": clock.year - 1, "pct": st.signed_pct(st.pct_change(cur, prev)),
            "span": f"Jan–{st.MONTH_ABBR[lm - 1]}", "count": _fmt(cur), "prev_count": _fmt(prev)}


def _t(tpl: dict, **kw) -> dict:
    return {"title": tpl["title"].format(**kw), "text": tpl["text"].format(**kw)}


def area_file(data: Data, scope: dict, clock: Clock, monthly=None, alert_run: dict | None = None) -> dict:
    hc = select(data.cells, scope)
    sc = select(data.sensor_cells, scope)
    grid = st.month_grid(hc.rename(columns={"weight": "count"}), "count")
    summ = summary(hc, clock, grid)
    return {
        "id": scope["id"], "name": scope["name"], "kind": scope["kind"],
        "province": scope["province"], "district": scope["district"],
        "is_sample": data.is_sample,
        "data_through_myt": (clock.through + MYT).strftime("%Y-%m-%d %H:%M"),
        "summary": summ,
        "calendar": calendar(grid, clock),
        "analysis": analysis(hc, sc, grid, clock, scope, data.calib, summ, monthly,
                             None if alert_run is None else
                             al.area_risk(alert_run["doc"]["alerts"], scope, alert_run["area_cells"],
                                          alert_run["doc"]["mode"])),
    }


# --------------------------------------------------------------------------- shared files
def districts_table(data: Data) -> list[dict]:
    b = data.boundaries.sort_values(["province", "district"])
    names = list(zip(b["province"], b["district"]))
    dup = {d for _, d in names if sum(1 for _, x in names if x == d) > 1}
    out = []
    for (prov, dist), geom in zip(names, b.geometry):
        did = f"{slug(prov)}-{slug(dist)}" if dist in dup else slug(dist)
        minx, miny, maxx, maxy = geom.bounds
        out.append({"id": did, "name": dist, "province": slug(prov), "province_name": prov,
                    "bbox": [round(minx, 3), round(miny, 3), round(maxx, 3), round(maxy, 3)]})
    return out


def build_places(data: Data) -> tuple[dict, list[dict]]:
    pcfg = config.load("places.yaml")
    cfg = pcfg["places"]
    pts = pd.DataFrame(cfg)
    tagged = geo.tag(pts, data.boundaries)
    if len(tagged) != len(pts):
        missing = set(pts["name"]) - set(tagged["name"])
        raise ValueError(f"places outside every district: {sorted(missing)} (config/places.yaml)")
    districts = districts_table(data)
    did = {(d["province_name"], d["name"]): d["id"] for d in districts}
    places = []
    for r in tagged.itertuples():
        if r.province != r.area:
            raise ValueError(f"{r.name}: lies in {r.province}, but config/places.yaml says {r.area}")
        places.append({"id": slug(r.name), "name": r.name, "area": slug(r.area), "province": r.province,
                       "district": did[(r.province, r.district)], "district_name": r.district,
                       "lat": float(r.lat), "lon": float(r.lon)})
    b = data.boundaries
    areas = [{"id": "borneo", "name": "Whole Borneo", "country": None,
              "bbox": [round(float(v), 3) for v in b.total_bounds]}]
    for a in data.areas:
        sub = b[b["province"] == a]
        areas.append({"id": slug(a), "name": a, "country": str(sub["country"].iloc[0]) if len(sub) else None,
                      "bbox": [round(float(v), 3) for v in sub.total_bounds]})
    doc = {"areas": areas,
           "places": [{k: p[k] for k in ("id", "name", "area", "district", "lat", "lon")} for p in places],
           "districts": [{k: d[k] for k in ("id", "name", "province", "bbox")} for d in districts],
           "custom_point_radius_km": float(pcfg["custom_point_radius_km"])}
    return doc, places


def build_boundaries(data: Data, districts: list[dict]) -> dict:
    import geopandas as gpd

    tol = float(ecfg()["boundaries_simplify_deg"])
    nd = int(ecfg()["boundaries_decimals"])
    b = data.boundaries[["country", "province", "district", "geometry"]].copy()
    did = {(d["province_name"], d["name"]): d["id"] for d in districts}
    b["level"] = "district"
    b["id"] = [did[(p, d)] for p, d in zip(b["province"], b["district"])]
    b["name"] = b["district"]
    b["area"] = b["province"].map(slug)
    prov = b.dissolve(by="province", as_index=False)[["province", "country", "geometry"]]
    prov = gpd.GeoDataFrame({"level": "province", "id": prov["province"].map(slug), "name": prov["province"],
                             "area": prov["province"].map(slug), "country": prov["country"]},
                            geometry=prov.geometry, crs=b.crs)
    dist = b[["level", "id", "name", "area", "country", "geometry"]]
    feats = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, g in (("p", prov), ("d", dist)):
            g = g.copy()
            g["geometry"] = g.geometry.simplify(tol, preserve_topology=True).make_valid()
            f = Path(tmp) / f"{name}.geojson"
            g.to_file(f, driver="GeoJSON", COORDINATE_PRECISION=nd)
            feats += json.loads(f.read_text(encoding="utf-8"))["features"]
    return {"type": "FeatureCollection", "features": feats}


def build_hotspots_30d(data: Data, clock: Clock, area_ids: list[str], district_ids: dict) -> dict:
    """Detections in the harmonized set (all VIIRS + MODIS-only) for the last points_max_days days."""
    days = float(ecfg()["points_max_days"])
    h = data.hot[pd.to_datetime(data.hot["datetime_utc"]) > clock.since(days)].copy()
    h["cell_lat"] = harmonize.cell_index(h["lat"])
    h["cell_lon"] = harmonize.cell_index(h["lon"])
    h = harmonize.mask_static(h.reset_index(drop=True), data.static)
    mo = data.cells[data.cells["base_sensor"] == "MODIS"][["day", "cell_lat", "cell_lon"]].drop_duplicates()
    mo = mo.assign(_keep=True, day=mo["day"].astype(str))
    h["day"] = h["date_myt"].astype(str)
    h = h.merge(mo, on=["day", "cell_lat", "cell_lon"], how="left")
    h = h[(h["sensor"].astype(str) == "VIIRS") | h["_keep"].fillna(False).astype(bool)]
    h = h.sort_values("datetime_utc").reset_index(drop=True)
    sats = sorted(h["satellite"].astype(str).unique())
    confs = ["nominal", "high"]
    base = clock.since(days).floor("D")
    t = ((pd.to_datetime(h["datetime_utc"]) - base).dt.total_seconds() // 60).astype(int)
    aidx = {a: i for i, a in enumerate(area_ids)}
    didx = {k: i for i, k in enumerate(district_ids)}
    sensor_of = {s: ("MODIS" if s in ("Terra", "Aqua") else "VIIRS") for s in sats}
    return {
        "is_sample": data.is_sample,
        "days": int(days),
        "count": int(len(h)),
        "note": "Detections in the harmonized set: all VIIRS + MODIS-only. t = minutes after base_time_utc.",
        "base_time_utc": base.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "satellites": sats, "sensor_of_satellite": sensor_of, "confidence": confs,
        "areas": area_ids, "districts": list(district_ids.values()),
        "lat": [round(float(x), 4) for x in h["lat"]],
        "lon": [round(float(x), 4) for x in h["lon"]],
        "t": t.tolist(),
        "sat": [sats.index(s) for s in h["satellite"].astype(str)],
        "frp": [_num(x) for x in h["frp"]],
        "conf": [confs.index(c) if c in confs else 0 for c in h["confidence"].astype(str)],
        "bright": [_num(x) for x in h["brightness"]],
        "area": [aidx[slug(p)] for p in h["province"].astype(str)],
        "district": [didx.get((p, d), -1) for p, d in zip(h["province"].astype(str), h["district"].astype(str))],
    }


def build_grid(data: Data, clock: Clock, days, area_ids: list[str], district_ids: dict) -> dict:
    deg = float(ecfg()["grid_deg"])
    c = window(data.cells, clock, days)
    if c.empty:
        cols = {k: [] for k in ("lat", "lon", "count", "frp", "area", "district")}
    else:
        g = c.assign(gy=np.floor(np.round(c["lat"].astype(float) / deg, 6)).astype(int),
                     gx=np.floor(np.round(c["lon"].astype(float) / deg, 6)).astype(int))
        agg = g.groupby(["gy", "gx"]).agg(count=("weight", "sum"), frp=("frp", "mean")).reset_index()
        mode = (g.groupby(["gy", "gx", "province", "district"])["weight"].sum().reset_index()
                .sort_values("weight", ascending=False).drop_duplicates(["gy", "gx"]))
        agg = agg.merge(mode[["gy", "gx", "province", "district"]], on=["gy", "gx"])
        didx = {k: i for i, k in enumerate(district_ids)}
        aidx = {a: i for i, a in enumerate(area_ids)}
        cols = {
            "lat": [round((y + 0.5) * deg, 2) for y in agg["gy"]],
            "lon": [round((x + 0.5) * deg, 2) for x in agg["gx"]],
            "count": [_num(v) for v in agg["count"]],
            "frp": [_num(v) for v in agg["frp"]],
            "area": [aidx[slug(p)] for p in agg["province"]],
            "district": [didx.get((p, d), -1) for p, d in zip(agg["province"], agg["district"])],
        }
    return {"is_sample": data.is_sample, "cell_deg": deg, "days": days, "from_utc":
            None if days is None else clock.since(days).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "note": "Harmonized fire cells summed per 0.1 deg cell; lat/lon = cell centre; frp = mean FRP.",
            "areas": area_ids, "districts": list(district_ids.values()), **cols}


def build_ranking(data: Data, clock: Clock, districts: list[dict]) -> dict:
    c = data.cells
    parts = {
        "now": window(c, clock, ecfg()["periods_days"]["current"]),
        "month": c[(c["year"] == clock.year) & (c["month"] == clock.month)],
        "year": c[c["year"] == clock.year],
    }
    sums = {k: v.groupby(["province", "district"])["weight"].sum() for k, v in parts.items()}
    rows = []
    for d in districts:
        key = (d["province_name"], d["name"])
        rows.append({"district": d["id"], "name": d["name"], "province": d["province"],
                     "province_name": d["province_name"],
                     **{k: _i(s.get(key, 0.0)) for k, s in sums.items()}})
    return {"is_sample": data.is_sample, "periods": {"now": "last 24 h", "month": f"{st.MONTH_ABBR[clock.month - 1]} {clock.year}",
                                                     "year": f"{clock.year} so far"},
            "districts": rows}


def build_meta(data: Data, clock: Clock, files: dict, model_version: str | None = None,
               mode: str | None = None) -> dict:
    sc = data.sensor_cells
    n = int(ecfg()["partial_check_days"])
    last_day = (clock.through + MYT).normalize()
    days = [(last_day - pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n - 1, -1, -1)]
    per = sc[sc["day"].isin(days)].groupby(["day", "sensor"]).size()
    sensors = {}
    for s in ("MODIS", "VIIRS"):
        counts = {dd: int(per.get((dd, s), 0)) for dd in days}
        sensors[s] = {"cells": counts, "no_detection_days": [dd for dd, v in counts.items() if v == 0]}
    gap_days = data.calib.get("gap_days", {}).get("days", [])
    rule_files = ["bands.yaml", "data.yaml", "places.yaml", "resources.yaml", "actions.yaml", "jurisdictions.json",
                  "forecast.yaml"]
    h = hashlib.sha256()
    for f in rule_files:
        p = paths.CONFIG / f
        if p.exists():
            h.update(p.read_bytes())
    w = st.B()["data_window"]
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through_utc": clock.through.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through_myt": (clock.through + MYT).strftime("%Y-%m-%d %H:%M"),
        "is_sample": data.is_sample,
        "sample_note": "SAMPLE DATA: synthetic detections, not real fires." if data.is_sample else None,
        "partial": {"note": "no_detection_days = a sensor delivered no fire cell in Borneo that day "
                            "(missing pass or simply no fires); VIIRS gap days are filled with MODIS x k.",
                    "days_checked": days, "sensors": sensors,
                    "viirs_gap_days_filled": [g for g in gap_days if g in days]},
        "data_window": {"first_year": w["first_year"], "current_year": w["current_year"],
                        "median_years": w["median_years"]},
        "periods_days": {k: int(v) for k, v in ecfg()["periods_days"].items()},
        "versions": {"model": model_version, "rules": h.hexdigest()[:12]},
        "mode": mode,
        "stubs": [],
        "sources": ["NASA FIRMS MODIS C6.1 (Terra, Aqua)", "NASA FIRMS VIIRS 375 m (S-NPP, NOAA-20)",
                    "GADM 4.1 boundaries"] + (["synthetic sample (data/sample)"] if data.is_sample else []),
        **data_status_fields(data, ingest.read_api_status()),
    }


def monthly_csv(data: Data, clock: Clock, scope_list: list[dict]) -> str:
    rows = ["area,place,year,month,modis_raw,viirs_raw,harmonized,harmonized_frp_mean"]
    for s in scope_list:
        hc, sc = select(data.cells, s), select(data.sensor_cells, s)
        h, f = monthly_series(hc, "weight", clock)
        m, _ = monthly_series(sc[sc["sensor"] == "MODIS"], None, clock)
        v, _ = monthly_series(sc[sc["sensor"] == "VIIRS"], None, clock)
        area = "Whole Borneo" if s["province"] is None else s["province"]
        place = s["name"] if s["kind"] == "place" else ""
        for (y, mm), a, b, c, fr in zip(clock.months_series(), m, v, h, f):
            rows.append(f"{area},{place},{y},{mm},{a},{b},{c},{'' if fr is None else fr}")
    return "\n".join(rows) + "\n"


# --------------------------------------------------------------------------- run
def run(out_dir, data: Data | None = None, weather_fn=None, save_state: bool = False) -> dict:
    """weather_fn: pipeline.weather.fetch in the daily run; None = offline (no weather, tests).
    save_state: write data/processed/alerts_state.json (only the daily run does)."""
    out = Path(out_dir)
    data = data or Data()
    clock = Clock(data.through)
    fcst = forecast.load()
    monthly = forecast.load_monthly()
    alert_run = al.build(data.cells, data.through, data.boundaries, [slug(a) for a in data.areas],
                         forecaster=fcst, weather_fn=weather_fn or (lambda la, lo: [None] * len(la)),
                         is_sample=data.is_sample)
    if save_state:
        al.save_state(alert_run["state"])
    places_doc, places = build_places(data)
    districts = districts_table(data)
    area_ids = [slug(a) for a in data.areas]
    district_ids = {(d["province_name"], d["name"]): d["id"] for d in districts}
    scope_list = scopes(data, places)

    if (out / "area").exists():
        shutil.rmtree(out / "area")
    sizes = {}
    sizes["bands.json"] = dump(out / "bands.json", st.B())
    sizes["places.json"] = dump(out / "places.json", places_doc)
    sizes["boundaries.json"] = dump(out / "boundaries.json", build_boundaries(data, districts))
    sizes["hotspots_30d.json"] = dump(out / "hotspots_30d.json",
                                      build_hotspots_30d(data, clock, area_ids, district_ids))
    for name, days in ecfg()["grid_periods"].items():
        sizes[f"grid_{name}.json"] = dump(out / f"grid_{name}.json",
                                          build_grid(data, clock, days, area_ids, district_ids))
    sizes["ranking.json"] = dump(out / "ranking.json", build_ranking(data, clock, districts))
    for s in scope_list:
        sizes[f"area/{s['id']}.json"] = dump(out / "area" / f"{s['id']}.json",
                                             area_file(data, s, clock, monthly, alert_run))
    sizes["alerts.json"] = dump(out / "alerts.json", alert_run["doc"])
    sizes["model.json"] = dump(out / "model.json",
                               al.model_doc(None if fcst is None else fcst.card, alert_run["check"], data.is_sample))
    csv = out / "export" / "monthly.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    csv.write_text(monthly_csv(data, clock, scope_list), encoding="utf-8")
    sizes["export/monthly.csv"] = csv.stat().st_size / 1024
    sizes["meta.json"] = dump(out / "meta.json", build_meta(data, clock, sizes, None if fcst is None else fcst.version,
                                                            alert_run["doc"]["mode"]))
    report(sizes, data.is_sample, out)
    d = alert_run["doc"]
    print(f"  alerts: {len(d['alerts'])} active ({', '.join(f'{k} {v}' for k, v in d['counts']['borneo'].items())}), "
          f"watch {d['watch']}, mode: {d['mode']}")
    return sizes


def over_budget(sizes: dict) -> list[str]:
    lim = ecfg()["max_kb"]
    bad = []
    for name, kb in sizes.items():
        cap = lim["area"] if name.startswith("area/") else lim.get(name)
        if cap is not None and kb > cap:
            bad.append(f"{name} {kb:.0f} KB > {cap} KB")
    return bad


def report(sizes: dict, is_sample: bool, out: Path) -> None:
    print(f"\nExported to {out}:")
    area = {k: v for k, v in sizes.items() if k.startswith("area/")}
    for k, v in sizes.items():
        if not k.startswith("area/"):
            print(f"  {k:<22} {v:8.1f} KB")
    if area:
        print(f"  area/*.json ({len(area)} files) {min(area.values()):.1f}-{max(area.values()):.1f} KB each")
    for msg in over_budget(sizes):
        print("  WARNING size budget:", msg)
    if is_sample:
        print("  NOTE: SAMPLE DATA (meta.json is_sample = true).")


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(paths.ROOT / "web" / "public" / "data"))
    p.add_argument("--no-weather", action="store_true", help="do not call Open-Meteo")
    a = p.parse_args(argv)
    from . import weather
    run(a.out, weather_fn=None if a.no_weather else weather.fetch)


if __name__ == "__main__":
    main()
