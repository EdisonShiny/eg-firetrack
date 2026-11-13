"""Forecast inputs (docs/logic-explained.md section 2, Model 1).

One example = one 0.1 deg cell (~11 km) on one MYT day. Inputs use hotspots up to and including
that day; targets are "at least one hotspot in the cell in the next 1 / 2 / 3 days".
A cell-day is scored only when its 25 km block (5 x 5 cells) had fire in the last 7 days: that is
where fire events and alerts can be, and it keeps the table small.

Inputs available in this build (all from the harmonized history, so the daily Action needs nothing else):
  recent fire in the cell and within ~25 km (1, 3, 7 days), days since the last fire in the cell,
  burned in the last 2 years, the usual (climatology) rate for this month in the cell and the block,
  peat class (approximate district list, config/forecast.yaml) and month.
Weather is NOT a model input: there is no archived weather in this build. The daily run still reads
Open-Meteo for the situation report, actions and haze (pipeline/weather.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from . import config, geo

FEATURES = ["cell_1d", "cell_3d", "cell_7d", "near_1d", "near_3d", "near_7d", "days_since_fire",
            "burned_2y", "usual_cell", "usual_near", "peat", "month"]
PEAT_CODE = {"none": 0, "shallow": 1, "deep": 2}


def gcfg() -> dict:
    return config.load("forecast.yaml")["grid"]


def grid_index(values, deg: float | None = None) -> np.ndarray:
    deg = deg or float(gcfg()["cell_deg"])
    return np.floor(np.round(np.asarray(values, dtype="float64") / deg, 6)).astype("int64")


def _key(gy, gx) -> np.ndarray:
    return (np.asarray(gy, dtype="int64") + 10_000) * 100_000 + (np.asarray(gx, dtype="int64") + 10_000)


def peat_of(district: str | None) -> str:
    p = config.load("forecast.yaml")["peat"]
    if district in p["deep"]:
        return "deep"
    if district in p["shallow"]:
        return "shallow"
    return "none"


def _rolling(S: np.ndarray, k: int) -> np.ndarray:
    """S = cumulative sums with a leading 0 column; -> sum of the last k days (incl. today)."""
    D = S.shape[1] - 1
    hi = np.arange(1, D + 1)
    lo = np.maximum(0, hi - k)
    return S[:, hi] - S[:, lo]


@dataclass
class Panel:
    start: date
    days: int
    keys: np.ndarray            # (n,) sorted cell keys
    gy: np.ndarray
    gx: np.ndarray
    C: np.ndarray               # (n, days) harmonized cells per 0.1 deg cell per day
    N: np.ndarray               # (n, days) same, summed over the 5 x 5 block
    district: np.ndarray        # (n,) district of the cell centre ("" if none)
    province: np.ndarray

    def day_index(self, d) -> int:
        return (pd.Timestamp(d).date() - self.start).days

    def date_of(self, i: int) -> date:
        return self.start + pd.Timedelta(days=int(i))

    def lookup(self, lat, lon) -> np.ndarray:
        """Row index of the 0.1 deg cells holding (lat, lon); -1 if not in the panel."""
        k = _key(grid_index(lat), grid_index(lon))
        pos = np.searchsorted(self.keys, k)
        pos = np.clip(pos, 0, len(self.keys) - 1)
        return np.where(self.keys[pos] == k, pos, -1)


def _offsets(r: int):
    return [(dy, dx) for dy in range(-r, r + 1) for dx in range(-r, r + 1)]


def _block_sum(keys, gy, gx, A: np.ndarray, r: int) -> np.ndarray:
    out = np.zeros_like(A)
    for dy, dx in _offsets(r):
        k = _key(gy + dy, gx + dx)
        pos = np.clip(np.searchsorted(keys, k), 0, len(keys) - 1)
        ok = keys[pos] == k
        out[ok] += A[pos[ok]]
    return out


def build_panel(cells: pd.DataFrame, start, end, boundaries=None) -> Panel:
    """cells: harmonized cells with lat, lon, day ('YYYY-MM-DD' MYT), weight."""
    deg = float(gcfg()["cell_deg"])
    r = int(gcfg()["neighbour_cells"])
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    D = (end - start).days + 1
    day = pd.to_datetime(cells["day"].astype(str))
    m = (day.dt.date >= start) & (day.dt.date <= end)
    c = cells[m.to_numpy()]
    d = (pd.to_datetime(c["day"].astype(str)).dt.date - start).map(lambda x: x.days).to_numpy(int) \
        if len(c) else np.zeros(0, int)
    gy, gx = grid_index(c["lat"], deg), grid_index(c["lon"], deg)
    fire = np.unique(_key(gy, gx))
    fgy, fgx = fire // 100_000 - 10_000, fire % 100_000 - 10_000
    allk = np.unique(np.concatenate([_key(fgy + dy, fgx + dx) for dy, dx in _offsets(r)])) if len(fire) \
        else np.zeros(0, "int64")
    kgy, kgx = allk // 100_000 - 10_000, allk % 100_000 - 10_000
    C = np.zeros((len(allk), D), dtype="float32")
    if len(c):
        idx = np.searchsorted(allk, _key(gy, gx))
        np.add.at(C, (idx, d), c["weight"].to_numpy("float32"))
    N = _block_sum(allk, kgy, kgx, C, r)
    dist = np.full(len(allk), "", dtype=object)
    prov = np.full(len(allk), "", dtype=object)
    if len(allk):
        boundaries = boundaries if boundaries is not None else geo.load_boundaries()
        pts = pd.DataFrame({"lat": (kgy + 0.5) * deg, "lon": (kgx + 0.5) * deg, "i": np.arange(len(allk))})
        t = geo.tag(pts, boundaries)
        dist[t["i"].to_numpy(int)] = t["district"].astype(str).to_numpy()
        prov[t["i"].to_numpy(int)] = t["province"].astype(str).to_numpy()
    return Panel(start, D, allk, kgy, kgx, C, N, dist, prov)


# --------------------------------------------------------------------------- climatology
def climatology(cells: pd.DataFrame, panel: Panel, years: list[int]) -> dict:
    """Usual daily rate per panel cell and month over `years`, plus per-year parts for leave-one-year-out."""
    deg = float(gcfg()["cell_deg"])
    c = cells[cells["year"].astype(int).isin(years)]
    idx = panel.lookup(c["lat"], c["lon"])
    ok = idx >= 0
    yi = np.searchsorted(years, c["year"].astype(int).to_numpy())
    mi = c["month"].astype(int).to_numpy() - 1
    per = np.zeros((len(panel.keys), len(years), 12), dtype="float64")
    np.add.at(per, (idx[ok], yi[ok], mi[ok]), c["weight"].to_numpy("float64")[ok])
    ndays = np.array([[pd.Period(f"{y}-{m:02d}").days_in_month for m in range(1, 13)] for y in years], float)
    return {"years": list(years), "per": per, "ndays": ndays, "deg": deg}


def usual_rate(clim: dict, rows_i: np.ndarray, rows_year: np.ndarray, rows_month: np.ndarray,
               loyo: bool) -> np.ndarray:
    per, nd, years = clim["per"], clim["ndays"], clim["years"]
    tot = per.sum(axis=1)                       # (n, 12)
    ndt = nd.sum(axis=0)                        # (12,)
    m = rows_month - 1
    num = tot[rows_i, m]
    den = ndt[m].copy()
    if loyo:
        yi = np.searchsorted(years, rows_year)
        inside = (yi < len(years)) & (np.asarray(years)[np.clip(yi, 0, len(years) - 1)] == rows_year)
        yc = np.clip(yi, 0, len(years) - 1)
        num = num - np.where(inside, per[rows_i, yc, m], 0.0)
        den = den - np.where(inside, nd[yc, m], 0.0)
    return np.where(den > 0, num / np.maximum(den, 1), 0.0)


def block_climatology(clim: dict, panel: Panel) -> dict:
    r = int(gcfg()["neighbour_cells"])
    n, Y, M = clim["per"].shape
    flat = clim["per"].reshape(n, Y * M)
    blk = _block_sum(panel.keys, panel.gy, panel.gx, flat, r).reshape(n, Y, M)
    return {**clim, "per": blk}


# --------------------------------------------------------------------------- rows
def rows(panel: Panel, clim: dict, day_from=None, day_to=None, loyo: bool = False,
         horizons=(1, 2, 3), only_candidates: bool = True) -> pd.DataFrame:
    """Feature table for panel days [day_from, day_to] (default: all). Target columns y1/y2/y3
    are NaN where the future days are not in the panel yet."""
    g = gcfg()
    C, N = panel.C, panel.N
    zero = np.zeros((C.shape[0], 1), dtype="float64")
    SC = np.concatenate([zero, np.cumsum(C, axis=1, dtype="float64")], axis=1)
    SN = np.concatenate([zero, np.cumsum(N, axis=1, dtype="float64")], axis=1)
    near7 = _rolling(SN, int(g["candidate_days"]))
    d0 = 0 if day_from is None else max(0, panel.day_index(day_from))
    d1 = panel.days - 1 if day_to is None else min(panel.days - 1, panel.day_index(day_to))
    mask = np.zeros_like(near7, dtype=bool)
    mask[:, d0:d1 + 1] = (near7[:, d0:d1 + 1] > 0) if only_candidates else True
    ii, dd = np.nonzero(mask)
    if len(ii) == 0:
        return pd.DataFrame(columns=["i", "d", "year", *FEATURES, *[f"y{h}" for h in horizons]])
    def roll(S, k):
        return S[ii, dd + 1] - S[ii, np.maximum(0, dd + 1 - k)]
    fire = C > 0
    ar = np.where(fire, np.arange(panel.days)[None, :], -10**6)
    last = np.maximum.accumulate(ar, axis=1)
    since = np.minimum(dd - last[ii, dd], 365).astype("float32")
    SF = np.concatenate([zero, np.cumsum(fire, axis=1, dtype="float64")], axis=1)
    dates = pd.to_datetime(pd.Timestamp(panel.start) + pd.to_timedelta(dd, unit="D"))
    year = dates.year.to_numpy()
    month = dates.month.to_numpy()
    blk = block_climatology(clim, panel)
    out = pd.DataFrame({
        "i": ii, "d": dd, "year": year,
        "cell_1d": roll(SC, 1), "cell_3d": roll(SC, 3), "cell_7d": roll(SC, 7),
        "near_1d": roll(SN, 1), "near_3d": roll(SN, 3), "near_7d": roll(SN, 7),
        "days_since_fire": since,
        "burned_2y": roll(SF, int(g["burned_days"])),
        "usual_cell": usual_rate(clim, ii, year, month, loyo),
        "usual_near": usual_rate(blk, ii, year, month, loyo),
        "peat": np.array([PEAT_CODE[peat_of(x)] for x in panel.district])[ii],
        "month": month,
    })
    for h in horizons:
        ok = dd + h <= panel.days - 1
        fut = SC[ii, np.minimum(dd + 1 + h, panel.days)] - SC[ii, dd + 1]
        out[f"y{h}"] = np.where(ok, (fut > 0).astype(float), np.nan)
    return out
