"""Statistics and predefined display values (docs/technical.md "Predefined display values",
docs/logic-explained.md sections 3 and 5).

Pure functions only: every band, threshold and word is read from config/bands.yaml.
export.py feeds them the harmonized data and writes the website JSON.

Conventions
- "Usual" = median of the same month over the full years in bands.yaml data_window.median_years
  (2017-2025). A year with no fires in a month counts as 0, not as missing.
- The current year (2026) is partial: it is never used in a median or yearly average, and it is
  compared with past years only over the same months.
- Band lookups round half-up to a whole number first, then take the first band whose max >= value.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from . import config

MONTHS = list(range(1, 13))
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_NAME = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
              "October", "November", "December"]


def B() -> dict:
    return config.bands()


# --------------------------------------------------------------------------- years
def median_years() -> list[int]:
    a, b = B()["data_window"]["median_years"]
    return list(range(int(a), int(b) + 1))


def all_years() -> list[int]:
    w = B()["data_window"]
    return list(range(int(w["first_year"]), int(w["current_year"]) + 1))


def current_year() -> int:
    return int(B()["data_window"]["current_year"])


# --------------------------------------------------------------------------- generic bands
def round_half_up(x: float) -> int:
    return int(math.floor(float(x) + 0.5))


def band(value: float | None, table: Sequence[dict]) -> dict | None:
    """First entry of a bands.yaml list whose max (inclusive) holds the rounded value."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    v = round_half_up(value)
    for row in table:
        if row.get("max") is None or v <= row["max"]:
            return row
    return table[-1]


def chance_word(pct: float | None) -> str | None:
    """72-hour chance of spreading in % -> Unlikely / Possible / Likely / Very likely."""
    row = band(pct, B()["chance_words"])
    return row["word"] if row else None


def anomaly_status(pct: float | None) -> str | None:
    """Compared-to-normal % -> Normal / Above average / Unusual."""
    row = band(pct, B()["compared_to_normal"])
    return row["status"] if row else None


def level_for_score(score: float | None) -> dict | None:
    """Risk score 0-100 -> level row (level, name, directive, deploy_within_h, colour)."""
    return band(score, B()["levels"])


def trend_word(pct: float | None) -> str | None:
    """Week-on-week change % -> Falling / Stable / Rising."""
    row = band(pct, B()["trend_direction"])
    return row["word"] if row else None


def frp_size(frp_mw: float) -> str:
    """Hotspot dot size: < small_below small, small_below..large_above medium, > large_above large."""
    s = B()["frp_dot_sizes_mw"]
    if frp_mw < s["small_below"]:
        return "small"
    if frp_mw > s["large_above"]:
        return "large"
    return "medium"


def is_very_intense(frp_mw: float) -> bool:
    return float(frp_mw) >= float(B()["very_intense_frp_mw"])


# --------------------------------------------------------------------------- anomaly / unusual
def anomaly_pct(current: float, usual: float) -> float | None:
    """(current - usual) / usual x 100. None when the usual count is 0 (no meaningful %)."""
    if usual is None or usual <= 0:
        return None
    return (float(current) - float(usual)) / float(usual) * 100.0


def cmp_rule() -> dict:
    return B()["compared_to_normal_rule"]


def vs_normal_label(pct: float | None) -> str:
    """Short big value for every "Compared to normal" tile (Map, Alerts, Analysis, PDF):
    up to +show_pct_up_to % -> "+18%" / "−12%"; above -> "3.2×"; above cap_ratio -> ">10×".
    ratio = current / baseline = 1 + pct / 100. The tile's small line says "vs usual · <status>"."""
    if pct is None:
        return "–"
    r = cmp_rule()
    v = round_half_up(pct)
    if v <= int(r["show_pct_up_to"]):
        return f"+{v}%" if v > 0 else (f"−{abs(v)}%" if v < 0 else "0%")
    ratio = 1.0 + float(pct) / 100.0
    cap = float(r["cap_ratio"])
    if round(ratio, 1) > cap:
        return f">{cap:g}×"
    return f"{ratio:.1f}×"


def compare_to_normal(current: float, past: Sequence[float], floor: float | None = None) -> dict:
    """THE compared-to-normal rule, used everywhere (Map summaries, Analysis risk band, Alerts,
    situation reports). `past` = harmonized fire cells in the same calendar window of each full
    year. Baseline = max(median(past), floor_cells)."""
    floor = float(cmp_rule()["floor_cells"]) if floor is None else float(floor)
    vals = [float(x) for x in past]
    median = float(np.median(vals)) if vals else 0.0
    base = max(median, floor)
    pct = (float(current) - base) / base * 100.0 if base > 0 else None
    return {"current": float(current), "median": median, "baseline": base, "floored": median < floor,
            "years_used": len(vals), "pct": pct, "ratio": None if pct is None else float(current) / base,
            "status": anomaly_status(pct), "label": vs_normal_label(pct)}


def _in_year(ts: pd.Timestamp, year: int) -> pd.Timestamp:
    """Same month/day/time in another year (Feb 29 -> Feb 28)."""
    try:
        return ts.replace(year=year)
    except ValueError:
        return ts.replace(year=year, day=28)


def window_bounds(kind: str, end: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp, float]:
    """(start, end, divisor) in local time; counts are taken over start < t <= end and divided by
    divisor. `end` is the latest data time shifted into the year being measured."""
    day = pd.Timedelta(days=1)
    if kind == "current":
        return end - day, end, 1.0
    if kind == "current_baseline":              # the 24 h window on the same day +-k days, averaged
        k = int(cmp_rule()["current_day_spread_days"])
        return end - day * (k + 1), end + day * k, float(2 * k + 1)
    if kind in ("7d", "30d"):
        return end - day * int(kind[:-1]), end, 1.0
    if kind == "month":
        return pd.Timestamp(end.year, end.month, 1) - pd.Timedelta(microseconds=1), end, 1.0
    if kind == "year":
        return pd.Timestamp(end.year, 1, 1) - pd.Timedelta(microseconds=1), end, 1.0
    raise ValueError(kind)


class WindowCounter:
    """Fast sums of weights over (start, end] time windows (times sorted once)."""

    def __init__(self, times, weights):
        t = pd.to_datetime(pd.Series(times)).to_numpy(dtype="datetime64[ns]")
        w = np.asarray(weights, dtype=float)
        o = np.argsort(t, kind="stable")
        self.t = t[o]
        self.cum = np.concatenate([[0.0], np.cumsum(w[o])])

    def sum(self, start: pd.Timestamp, end: pd.Timestamp) -> float:
        i = np.searchsorted(self.t, np.datetime64(start, "ns"), side="right")
        j = np.searchsorted(self.t, np.datetime64(end, "ns"), side="right")
        return float(self.cum[j] - self.cum[i])


def same_window(counter: WindowCounter, kind: str, end: pd.Timestamp, years: Iterable[int] | None = None,
                data_start: pd.Timestamp | None = None) -> tuple[float, list[float], dict]:
    """Current count for window `kind` ending at `end`, plus the count in the same calendar window
    of each full year (only years whose window starts on or after data_start)."""
    years = list(years if years is not None else median_years())
    data_start = data_start if data_start is not None else pd.Timestamp(int(B()["data_window"]["first_year"]), 1, 1)
    s, e, _ = window_bounds(kind, end)
    current = counter.sum(s, e)
    bkind = "current_baseline" if kind == "current" else kind
    past, used = [], []
    for y in years:
        if y >= end.year:
            continue
        bs, be, div = window_bounds(bkind, _in_year(end, y))
        if bs < data_start - pd.Timedelta(microseconds=1):
            continue
        past.append(counter.sum(bs, be) / div)
        used.append(y)
    info = {"start": str(s + pd.Timedelta(microseconds=1))[:16] if kind in ("month", "year") else str(s)[:16],
            "end": str(e)[:16], "years": [used[0], used[-1]] if used else None}
    return current, past, info


WINDOW_WORDS = {"current": "last 24 h", "7d": "last 7 days", "30d": "last 30 days",
                "month": "this month so far", "year": "this year so far"}


def window_basis(kind: str, info: dict, res: dict) -> str:
    yrs = f"{info['years'][0]}-{info['years'][1]}" if info["years"] else "no full years"
    same = ("the same 24 h window on the same day ±%d days" % int(cmp_rule()["current_day_spread_days"])
            if kind == "current" else "the same calendar window")
    floor = f"; median {res['median']:.1f} raised to the minimum of {res['baseline']:g} cells" if res["floored"] else ""
    return (f"{WINDOW_WORDS[kind].capitalize()} ({info['start']} to {info['end']} MYT): {res['current']:.0f} fire cells "
            f"vs a usual {res['baseline']:.1f} = median of {same} in {yrs}{floor}.")


def pct_change(new: float, old: float) -> float | None:
    if old is None or old <= 0:
        return None
    return (float(new) - float(old)) / float(old) * 100.0


def is_unusual(count: float, usual: float) -> bool:
    """Calendar outline: count >= unusual_month_ratio x usual (only when the usual is > 0)."""
    if usual is None or usual <= 0:
        return False
    return float(count) >= float(B()["unusual_month_ratio"]) * float(usual) - 1e-9


def ratio_to_usual(count: float, usual: float) -> float | None:
    if usual is None or usual <= 0:
        return None
    return round(float(count) / float(usual), 2)


def sudden_increase(last7: float, prev7: float) -> bool:
    """Last 7 days >= ratio x previous 7 days and >= min_hotspots."""
    s = B()["sudden_increase"]
    return float(last7) >= float(s["min_hotspots"]) and float(last7) >= float(s["ratio"]) * float(prev7)


# --------------------------------------------------------------------------- monthly grid
def month_grid(monthly: pd.DataFrame, value: str = "count", years: Iterable[int] | None = None) -> pd.DataFrame:
    """year x month (1-12) table of `value`, missing = 0. `monthly` has year, month, value."""
    years = list(years or all_years())
    g = monthly.groupby(["year", "month"])[value].sum() if len(monthly) else pd.Series(dtype=float)
    out = pd.DataFrame(0.0, index=years, columns=MONTHS)
    for (y, m), v in g.items():
        if int(y) in out.index:
            out.loc[int(y), int(m)] = float(v)
    return out


def usual_months(grid: pd.DataFrame, years: Iterable[int] | None = None) -> pd.Series:
    """Median per month over the full years (zeros included)."""
    years = [y for y in (years or median_years()) if y in grid.index]
    return grid.loc[years].median(axis=0)


def yearly_average(grid: pd.DataFrame, years: Iterable[int] | None = None) -> float:
    years = [y for y in (years or median_years()) if y in grid.index]
    return float(grid.loc[years].sum(axis=1).mean()) if years else 0.0


def fire_season(usual: pd.Series, grid: pd.DataFrame | None = None) -> dict:
    """Months whose usual count >= fire_season_ratio x the average month (mean of the 12 medians).

    Label = the longest run of consecutive season months (wrapping Dec -> Jan) that holds the peak.
    Share = hotspots in the season months / all hotspots, over the full years.
    """
    ratio = float(B()["fire_season_ratio"])
    avg = float(usual.mean())
    if avg <= 0:
        return {"months": [], "label": None, "share_pct": None, "average_month": 0.0, "ratio": ratio}
    months = [m for m in MONTHS if float(usual[m]) >= ratio * avg - 1e-9]
    peak = int(usual.idxmax())
    run = [peak]
    m = peak
    while (m % 12) + 1 in months and (m % 12) + 1 not in run:
        m = (m % 12) + 1
        run.append(m)
    m = peak
    while ((m - 2) % 12) + 1 in months and ((m - 2) % 12) + 1 not in run:
        m = ((m - 2) % 12) + 1
        run.insert(0, m)
    label = MONTH_ABBR[run[0] - 1] if len(run) == 1 else f"{MONTH_ABBR[run[0] - 1]} – {MONTH_ABBR[run[-1] - 1]}"
    share = None
    if grid is not None:
        yrs = [y for y in median_years() if y in grid.index]
        total = float(grid.loc[yrs].values.sum())
        if total > 0:
            share = round(float(grid.loc[yrs, months].values.sum()) / total * 100, 1)
    return {"months": months, "run": run, "label": label, "share_pct": share,
            "average_month": round(avg, 1), "ratio": ratio}


def season_strength(usual: pd.Series) -> float | None:
    """Usual count of the peak month / the quietest month (None when the quietest is 0)."""
    lo = float(usual.min())
    return None if lo <= 0 else round(float(usual.max()) / lo, 1)


def quantile_edges(values: Iterable[float], bins: int | None = None) -> list[float]:
    """bins + 1 edges (min, the bins-1 inner quantiles, max) for the calendar colour ramp."""
    bins = bins or len(B().get("calendar_ramp", [])) or 7
    v = np.asarray([float(x) for x in values], dtype=float)
    if v.size == 0:
        return [0.0] * (bins + 1)
    qs = np.quantile(v, np.linspace(0, 1, bins + 1))
    return [round(float(q), 2) for q in qs]


def bin_index(value: float, edges: Sequence[float]) -> int:
    """0 .. len(edges)-2: which colour bin a value falls in (inner edges are upper-inclusive)."""
    inner = list(edges[1:-1])
    for i, e in enumerate(inner):
        if value <= e:
            return i
    return len(inner)


# --------------------------------------------------------------------------- trend direction
def week_on_week(weekly: Sequence[float]) -> dict:
    """Recent direction from the last 4 weekly totals (oldest first): mean of the 3 week-on-week
    changes in %, worded with trend_direction. Weeks with a 0 before them are skipped."""
    w = [float(x) for x in weekly][-4:]
    changes = [pct_change(w[i], w[i - 1]) for i in range(1, len(w))]
    valid = [c for c in changes if c is not None]
    if not valid:
        pct = 0.0 if not any(w) else None
    else:
        pct = float(np.mean(valid))
    top = B()["trend_direction"][-1]["word"]          # the "rising" word
    rising_weeks = sum(1 for c in changes if c is not None and trend_word(c) == top)
    return {"weekly": [round(x, 1) for x in w],
            "changes_pct": [None if c is None else round(c, 1) for c in changes],
            "pct": None if pct is None else round(pct, 1),
            "word": trend_word(pct), "rising_weeks": rising_weeks}


# --------------------------------------------------------------------------- prediction band
def prediction_band(values: Sequence[float]) -> list[dict]:
    """+-15 / 25 / 35 % range for months 1-3 (bands.yaml prediction_range_pct)."""
    out = []
    for v, p in zip(values, B()["prediction_range_pct"]):
        v = float(v)
        out.append({"value": round(v, 1), "low": round(v * (1 - p / 100), 1),
                    "high": round(v * (1 + p / 100), 1), "range_pct": p})
    return out


def signed_pct(pct: float | None) -> str:
    if pct is None:
        return "–"
    v = round_half_up(pct)
    return f"+{v}%" if v > 0 else f"{v}%"
