"""Harmonize MODIS and VIIRS into one fire record (docs/technical.md "Data" D-E).

    python -m pipeline.harmonize

Steps (settings in config/data.yaml -> harmonize):
1. Grid: snap every detection to a 0.01 deg (~1 km) fire cell; a cell counts once per sensor per day.
   "VIIRS" = S-NPP + NOAA-20 (+ NOAA-21) together, so two VIIRS satellites on one cell-day count once.
2. Match: a MODIS and a VIIRS detection within +-0.01 deg and +-1 h are the same fire.
3. Merge: harmonized = all VIIRS fire cells + MODIS-only fire cells (weight 1 each).
4. Calibrate: k = VIIRS cells / MODIS cells on matching overpasses only (Aqua vs VIIRS within +-1 h
   of that day's Aqua pass), per province x season, full years only. k = sum VIIRS / sum MODIS.
5. Gap fill: on a day with no VIIRS data, each MODIS cell gets weight k (40 cells x 2.6 = 104).
6. Check: leave one year out, refit k, predict that year's VIIRS cells from MODIS, report R^2 and error.

Writes data/processed/harmonized_cells.parquet, monthly_counts.parquet, calibration_k.json
(and static_cells.json, the static-source mask used for NRT rows that have no FIRMS type).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config, ingest, paths

log = logging.getLogger(__name__)

CELL_KEYS = ["day", "cell_lat", "cell_lon"]


def settings() -> dict:
    return config.data_cfg()["harmonize"]


def full_years() -> list[int]:
    a, b = config.bands()["data_window"]["median_years"]
    return list(range(int(a), int(b) + 1))


def season_of(month: int) -> str:
    for name, months in settings()["calibration"]["seasons"].items():
        if int(month) in months:
            return name
    raise ValueError(f"month {month} is in no season (config/data.yaml harmonize.calibration.seasons)")


# --------------------------------------------------------------------------- 1. grid
def cell_index(values) -> np.ndarray:
    """floor(value / 0.01) as int; rounded first so 0.29 / 0.01 lands in cell 29, not 28."""
    deg = float(settings()["cell_deg"])
    return np.floor(np.round(np.asarray(values, dtype="float64") / deg, 6)).astype("int64")


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Detections -> plain columns + day, year, month, cell_lat, cell_lon."""
    d = pd.DataFrame({
        "lat": df["lat"].astype("float64"),
        "lon": df["lon"].astype("float64"),
        "t": pd.to_datetime(df["datetime_utc"]),
        "day": df[settings()["day_column"]].astype(str),
        "sensor": df["sensor"].astype(str),
        "satellite": df["satellite"].astype(str),
        "daynight": df["daynight"].astype(str) if "daynight" in df else "D",
        "frp": pd.to_numeric(df["frp"], errors="coerce").astype("float64"),
        "type": df["type"].astype(int) if "type" in df else 0,
        "country": df["country"].astype(str) if "country" in df else "",
        "province": df["province"].astype(str),
        "district": df["district"].astype(str),
    })
    d["cell_lat"] = cell_index(d["lat"])
    d["cell_lon"] = cell_index(d["lon"])
    day = pd.to_datetime(d["day"])
    d["year"] = day.dt.year.astype(int)
    d["month"] = day.dt.month.astype(int)
    return d.reset_index(drop=True)


# --------------------------------------------------------------------------- static-source mask
def static_cells_from_files(files) -> list[list[int]]:
    """0.01 deg cells of FIRMS type 1/2/3 detections (volcano, static land source, offshore)."""
    types = settings()["static"]["types"]
    frames = [ingest.read_firms_file(f) for f in files]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return []
    raw = pd.concat(frames, ignore_index=True)
    raw = raw[raw["type"].isin(types)].dropna(subset=["lat", "lon"])
    cells = pd.DataFrame({"a": cell_index(raw["lat"]), "b": cell_index(raw["lon"])}).drop_duplicates()
    return sorted(cells.values.tolist())


def load_static_cells() -> list[list[int]]:
    """Static-source cells: rebuilt from the FIRMS archive when it is on this machine, otherwise the
    committed static_cells.json (the daily Action has no data/raw), otherwise built from data/sample."""
    archive = ingest.find_firms_files(paths.RAW_FIRMS, exclude=paths.RAW_API)
    if not archive and paths.STATIC_CELLS.exists():
        return json.loads(paths.STATIC_CELLS.read_text(encoding="utf-8"))["cells"]
    files = archive or ingest.find_firms_files(paths.SAMPLE_FIRMS)
    if not files:
        return []
    cells = static_cells_from_files(files)
    paths.STATIC_CELLS.write_text(json.dumps(
        {"source": "archive" if archive else "sample", "types": settings()["static"]["types"],
         "cell_deg": settings()["cell_deg"], "cells": cells}), encoding="utf-8")
    return cells


def mask_static(d: pd.DataFrame, static_cells) -> pd.DataFrame:
    """Drop rows of unknown type (NRT, -1) within buffer_cells of a static-source cell."""
    unknown = config.data_cfg()["unknown_type"]
    if not len(static_cells) or not (d["type"] == unknown).any():
        return d
    buf = int(settings()["static"]["buffer_cells"])
    near = {(a + i, b + j) for a, b in static_cells
            for i in range(-buf, buf + 1) for j in range(-buf, buf + 1)}
    hit = pd.Series([(a, b) in near for a, b in zip(d["cell_lat"], d["cell_lon"])], index=d.index)
    return d[~((d["type"] == unknown) & hit)].reset_index(drop=True)


# --------------------------------------------------------------------------- 2. match
def matched_modis_cells(d: pd.DataFrame) -> pd.DataFrame:
    """MODIS (day, cell) pairs that have a VIIRS detection within +-max_deg and +-max_hours."""
    m_cfg = settings()["match"]
    max_deg, max_dt = float(m_cfg["max_deg"]), pd.Timedelta(hours=float(m_cfg["max_hours"]))
    m = d.loc[d["sensor"] == "MODIS", ["day", "cell_lat", "cell_lon", "lat", "lon", "t"]]
    v = d.loc[d["sensor"] == "VIIRS", ["day", "cell_lat", "cell_lon", "lat", "lon", "t"]]
    if m.empty or v.empty:
        return pd.DataFrame(columns=CELL_KEYS)
    reach = int(np.ceil(max_deg / float(settings()["cell_deg"])))
    v = v.rename(columns={"lat": "lat_v", "lon": "lon_v", "t": "t_v"})
    hits = []
    for i in range(-reach, reach + 1):            # VIIRS within +-max_deg sits in a neighbouring cell
        for j in range(-reach, reach + 1):
            probe = m.assign(cell_lat=m["cell_lat"] + i, cell_lon=m["cell_lon"] + j,
                             m_lat=m["cell_lat"], m_lon=m["cell_lon"])
            pair = probe.merge(v, on=CELL_KEYS)
            near = ((pair["lat"] - pair["lat_v"]).abs() <= max_deg + 1e-9) \
                & ((pair["lon"] - pair["lon_v"]).abs() <= max_deg + 1e-9) \
                & ((pair["t"] - pair["t_v"]).abs() <= max_dt)
            hits.append(pair.loc[near, ["day", "m_lat", "m_lon"]])
    out = pd.concat(hits).drop_duplicates()
    return out.rename(columns={"m_lat": "cell_lat", "m_lon": "cell_lon"}).reset_index(drop=True)


# --------------------------------------------------------------------------- 1+3. fire cells, merge
def fire_cells(d: pd.DataFrame) -> pd.DataFrame:
    """One row per sensor per day per cell (first detection sets place/time; FRP = max)."""
    keys = ["sensor"] + CELL_KEYS
    s = d.sort_values("t", kind="stable")
    out = s.groupby(keys, sort=False).agg(
        year=("year", "first"), month=("month", "first"), t=("t", "first"),
        country=("country", "first"), province=("province", "first"),
        district=("district", "first"), n=("t", "size"), frp=("frp", "max")).reset_index()
    # satellites that saw the cell, e.g. "NOAA-20,S-NPP" (bit sum per cell avoids a slow lambda)
    names = sorted(s["satellite"].unique())
    bit = {n: 1 << i for i, n in enumerate(names)}
    sats = s.drop_duplicates(keys + ["satellite"])
    mask = sats.assign(b=sats["satellite"].map(bit)).groupby(keys, sort=False)["b"].sum()
    label = {v: ",".join(n for n in names if v & bit[n]) for v in mask.unique()}
    out["satellites"] = out.set_index(keys).index.map(mask.map(label)).values
    return out


def merge(d: pd.DataFrame) -> pd.DataFrame:
    """All VIIRS cells + MODIS-only cells. One row per fire cell per day, no double count.

    A MODIS cell is the same fire as VIIRS (not MODIS-only) when
    - a VIIRS detection is within +-1 km and +-1 h (works across cell borders), or
    - VIIRS already has that same cell on that same day, at any hour (a cell counts once per day,
      e.g. a Terra 10:30 pass and a VIIRS 13:30 pass over one fire are one record, exactly like
      two VIIRS satellites hours apart)."""
    cells = fire_cells(d)
    v = cells[cells["sensor"] == "VIIRS"]
    m = cells[cells["sensor"] == "MODIS"]
    matched = matched_modis_cells(d).assign(_matched=True)
    v_keys = v[CELL_KEYS].drop_duplicates().assign(_same_cell=True)
    m = m.merge(matched, on=CELL_KEYS, how="left").merge(v_keys, on=CELL_KEYS, how="left")
    m["_matched"] = m["_matched"].notna() | m["_same_cell"].notna()
    m = m.drop(columns="_same_cell")
    m_only = m[~m["_matched"]].drop(columns="_matched")
    # a VIIRS cell is "seen by both" when some MODIS cell matched onto it or the same cell has MODIS
    m_seen = m.loc[m["_matched"], CELL_KEYS].drop_duplicates().assign(_both=True)
    v = v.merge(m_seen, on=CELL_KEYS, how="left")
    v["seen_by"] = np.where(v["_both"].notna(), "both", "VIIRS")
    v = v.drop(columns="_both")
    m_only = m_only.assign(seen_by="MODIS")
    h = pd.concat([v, m_only], ignore_index=True).rename(columns={"sensor": "base_sensor"})
    h["weight"] = 1.0
    h["filled"] = False
    return h


# --------------------------------------------------------------------------- 4. calibrate
def calibration_counts(d: pd.DataFrame) -> pd.DataFrame:
    """Aqua cells and VIIRS cells on matching overpasses, per province x year x month.

    For each day and day/night half, the pass window is the Aqua detection time span +-pass_window_hours.
    Only VIIRS detections inside that window count, so both sensors look at the same moment.
    """
    c = settings()["calibration"]
    win = pd.Timedelta(hours=float(c["pass_window_hours"]))
    aqua = d[(d["sensor"] == "MODIS") & (d["satellite"] == c["modis_satellite"])]
    viirs = d[d["sensor"] == "VIIRS"]
    if aqua.empty or viirs.empty:
        return pd.DataFrame(columns=["province", "year", "month", "modis", "viirs"])
    span = aqua.groupby(["day", "daynight"])["t"].agg(t0="min", t1="max").reset_index()
    v = viirs.merge(span, on=["day", "daynight"])
    v = v[(v["t"] >= v["t0"] - win) & (v["t"] <= v["t1"] + win)]
    # only pass halves where both sensors delivered fires count (VIIRS present at the Aqua time)
    both = v[["day", "daynight"]].drop_duplicates()
    a = aqua.merge(both, on=["day", "daynight"])

    def cells(x, name):
        x = x.sort_values("t", kind="stable").drop_duplicates(CELL_KEYS)   # once per sensor per day
        return x.groupby(["province", "year", "month"]).size().rename(name)

    out = pd.concat([cells(a, "modis"), cells(v, "viirs")], axis=1).fillna(0).astype(int)
    return out.reset_index()


def fit_k(counts: pd.DataFrame, years=None) -> dict:
    """k per province x season (sum VIIRS / sum MODIS) with fallbacks for thin data."""
    c = settings()["calibration"]
    min_m = int(c["min_modis_cells"])
    x = counts if years is None else counts[counts["year"].isin(list(years))]
    x = x.assign(season=x["month"].map(season_of))
    seasons = list(c["seasons"])

    def ratio(sub):
        m, v = int(sub["modis"].sum()), int(sub["viirs"].sum())
        return (v / m if m >= min_m else None), m, v

    borneo_all, bm, bv = ratio(x)
    if borneo_all is None:
        borneo_all = (bv / bm) if bm else 1.0
    borneo = {}
    for s in seasons:
        k, m, v = ratio(x[x["season"] == s])
        borneo[s] = {"k": round(k if k is not None else borneo_all, 4), "modis_cells": m,
                     "viirs_cells": v, "source": "Borneo season" if k is not None else "Borneo all"}
    table = {}
    for prov in sorted(set(config.data_cfg()["areas"]) | set(x["province"].unique())):
        px = x[x["province"] == prov]
        k_all, _, _ = ratio(px)
        table[prov] = {}
        for s in seasons:
            k, m, v = ratio(px[px["season"] == s])
            if k is not None:
                src = "province season"
            elif k_all is not None:
                k, src = k_all, "province all seasons"
            else:
                k, src = borneo[s]["k"], borneo[s]["source"]
            table[prov][s] = {"k": round(k, 4), "modis_cells": m, "viirs_cells": v, "source": src}
    return {"provinces": table, "borneo": borneo, "borneo_all": round(borneo_all, 4)}


def k_for(kt: dict, province: str, month: int) -> float:
    s = season_of(month)
    p = kt["provinces"].get(province)
    return float(p[s]["k"] if p else kt["borneo"][s]["k"])


# --------------------------------------------------------------------------- 5. gap fill
def viirs_gap_days(d: pd.DataFrame) -> set[str]:
    """Days with no VIIRS detection anywhere while MODIS saw >= min_modis_cells (+ listed outages)."""
    g = settings()["gap_fill"]
    cells = d.drop_duplicates(["sensor"] + CELL_KEYS)
    per = cells.groupby(["day", "sensor"]).size().unstack(fill_value=0)
    for s in ("MODIS", "VIIRS"):
        if s not in per:
            per[s] = 0
    gaps = set(per.index[(per["VIIRS"] == 0) & (per["MODIS"] >= int(g["min_modis_cells"]))])
    return gaps | {str(x) for x in g.get("viirs_outage_days") or []}


def apply_gap_fill(h: pd.DataFrame, gap_days, kt: dict) -> pd.DataFrame:
    """MODIS cells on VIIRS-gap days count k VIIRS-equivalent cells each (40 x 2.6 = 104)."""
    h = h.copy()
    sel = h["day"].isin(set(gap_days)) & (h["base_sensor"] == "MODIS")
    if sel.any():
        h.loc[sel, "weight"] = [k_for(kt, p, m) for p, m in zip(h.loc[sel, "province"], h.loc[sel, "month"])]
        h.loc[sel, "filled"] = True
    return h


# --------------------------------------------------------------------------- 6. check
def r2(actual, pred) -> float | None:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    if len(a) < 2:
        return None
    ss_tot = ((a - a.mean()) ** 2).sum()
    if ss_tot == 0:
        return None
    return float(1 - ((a - p) ** 2).sum() / ss_tot)


def leave_one_year_out(counts: pd.DataFrame, years=None) -> dict:
    """Hide each full year, fit k on the rest, predict its VIIRS cells = MODIS cells x k.

    R^2 over province-months; average error = mean |predicted - actual| / actual of yearly totals.
    """
    years = list(years or full_years())
    rows = []
    for y in years:
        test = counts[counts["year"] == y]
        if test.empty:
            continue
        kt = fit_k(counts, [x for x in years if x != y])
        pred = [r.modis * k_for(kt, r.province, r.month) for r in test.itertuples()]
        rows.append(test.assign(pred=pred, k_used=[p / m if m else np.nan for p, m in zip(pred, test["modis"])]))
    if not rows:
        return {"years": years, "provinces": {}, "borneo": {}}
    res = pd.concat(rows, ignore_index=True)

    def summary(x: pd.DataFrame) -> dict:
        monthly = x.groupby(["year", "month"])[["viirs", "pred"]].sum()
        yearly = x.groupby("year")[["modis", "viirs", "pred"]].sum()
        ok = yearly[yearly["viirs"] > 0]
        err = ((ok["pred"] - ok["viirs"]).abs() / ok["viirs"] * 100).mean() if len(ok) else None
        val = r2(monthly["viirs"], monthly["pred"])
        return {
            "r2": None if val is None else round(val, 3),
            "avg_error_pct": None if err is None or pd.isna(err) else round(float(err), 1),
            "per_year": {str(int(y)): {"modis_cells": int(r.modis), "viirs_cells": int(r.viirs),
                                       "predicted_viirs": round(float(r.pred), 1)}
                         for y, r in yearly.iterrows()},
        }

    return {"years": years,
            "provinces": {p: summary(x) for p, x in res.groupby("province")},
            "borneo": summary(res)}


# --------------------------------------------------------------------------- outputs
def monthly_counts(d: pd.DataFrame, h: pd.DataFrame) -> pd.DataFrame:
    """province, district, year, month, sensor (MODIS raw | VIIRS raw | harmonized), count, frp_mean,
    frp_high_count. Raw = detections; harmonized = sum of cell weights (k on gap days)."""
    high = float(config.bands()["very_intense_frp_mw"])
    keys = ["country", "province", "district", "year", "month"]
    raw = d.assign(w=1.0, hi=(d["frp"] >= high).astype(int))
    hh = h.rename(columns={"base_sensor": "_b"}).assign(sensor="harmonized", w=h["weight"],
                                                       hi=(h["frp"] >= high).astype(int))
    parts = []
    for x in (raw, hh):
        g = x.groupby(keys + ["sensor"], observed=True)
        parts.append(g.agg(count=("w", "sum"), frp_mean=("frp", "mean"), frp_high_count=("hi", "sum")).reset_index())
    out = pd.concat(parts, ignore_index=True)
    out["count"] = out["count"].round(2)
    out["frp_mean"] = out["frp_mean"].round(2).astype("float32")
    out["frp_high_count"] = out["frp_high_count"].astype("int32")
    for c in ("year", "month"):
        out[c] = out[c].astype("int16")
    for c in ("country", "province", "district", "sensor"):
        out[c] = out[c].astype("category")
    return out.sort_values(keys + ["sensor"]).reset_index(drop=True)


def cells_table(h: pd.DataFrame) -> pd.DataFrame:
    deg = float(settings()["cell_deg"])
    out = pd.DataFrame({
        "day": h["day"].astype(str), "year": h["year"].astype("int16"), "month": h["month"].astype("int8"),
        "cell_lat": h["cell_lat"].astype("int32"), "cell_lon": h["cell_lon"].astype("int32"),
        "lat": ((h["cell_lat"] + 0.5) * deg).astype("float32"),
        "lon": ((h["cell_lon"] + 0.5) * deg).astype("float32"),
        "first_time_utc": h["t"], "base_sensor": h["base_sensor"], "seen_by": h["seen_by"],
        "satellites": h["satellites"], "detections": h["n"].astype("int16"),
        "frp": h["frp"].astype("float32"), "weight": h["weight"].astype("float32"), "filled": h["filled"],
        "country": h["country"], "province": h["province"], "district": h["district"],
    })
    for c in ("day", "base_sensor", "seen_by", "satellites", "country", "province", "district"):
        out[c] = out[c].astype("category")
    return out.sort_values(["day", "cell_lat", "cell_lon"]).reset_index(drop=True)


def harmonize(df: pd.DataFrame, static_cells=()) -> dict:
    """Full Phase 2 run in memory: returns cells, monthly, k table, check, gap days."""
    d = mask_static(prepare(df), static_cells)
    counts = calibration_counts(d)
    kt = fit_k(counts, full_years())
    gaps = viirs_gap_days(d)
    h = apply_gap_fill(merge(d), gaps, kt)
    return {"detections": d, "cells": h, "monthly": monthly_counts(d, h), "k": kt,
            "check": leave_one_year_out(counts), "counts": counts, "gap_days": sorted(gaps)}


def _write_parquet(df: pd.DataFrame, path) -> float:
    limit = config.data_cfg()["processed"]["max_file_mb"]
    df.to_parquet(path, compression="zstd", index=False)
    mb = path.stat().st_size / 1e6
    if mb >= limit:
        raise RuntimeError(f"{path.name} is {mb:.1f} MB (limit {limit} MB): split it by year")
    return round(mb, 2)


def write(res: dict, is_sample: bool) -> dict:
    sizes = {paths.HARMONIZED_CELLS.name: _write_parquet(cells_table(res["cells"]), paths.HARMONIZED_CELLS),
             paths.MONTHLY_COUNTS.name: _write_parquet(res["monthly"], paths.MONTHLY_COUNTS)}
    c = settings()["calibration"]
    doc = {
        "is_sample": bool(is_sample),
        "note": ("SAMPLE DATA: R^2 and error are a pipeline check only, not a real result."
                 if is_sample else "FIRMS archive data."),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": {
            "k": "sum of VIIRS fire cells / sum of Aqua MODIS fire cells on matching overpasses "
                 f"(VIIRS within +-{c['pass_window_hours']} h of the Aqua pass), per province x season",
            "fit_years": full_years(),
            "seasons": c["seasons"],
            "check": "leave one year out; R^2 over province-months, average error over yearly totals",
        },
        "k": res["k"],
        "check": res["check"],
        "gap_days": {"count": len(res["gap_days"]), "days": res["gap_days"]},
    }
    paths.CALIBRATION_K.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return sizes


def print_report(res: dict, is_sample: bool, sizes: dict | None = None) -> None:
    if is_sample:
        print("\n" + "!" * 72 + "\n  SAMPLE DATA: R^2 / error below only check that the pipeline runs.\n"
              "  They say nothing about real MODIS-VIIRS agreement.\n" + "!" * 72)
    h, d = res["cells"], res["detections"]
    print(f"\nDetections {len(d):,} (MODIS {int((d.sensor == 'MODIS').sum()):,}, "
          f"VIIRS {int((d.sensor == 'VIIRS').sum()):,}) -> harmonized fire cells {len(h):,} "
          f"(VIIRS {int((h.seen_by == 'VIIRS').sum()):,}, both {int((h.seen_by == 'both').sum()):,}, "
          f"MODIS-only {int((h.seen_by == 'MODIS').sum()):,}); VIIRS gap days {len(res['gap_days'])}")
    kt, chk = res["k"], res["check"]
    seasons = list(settings()["calibration"]["seasons"])
    print(f"\nk = VIIRS cells / MODIS cells (matching Aqua passes, fit {full_years()[0]}-{full_years()[-1]}), "
          "leave-one-year-out check:")
    head = f"  {'province':<20}" + "".join(f"{'k ' + s:>9}" for s in seasons) + f"{'R2':>8}{'avg err %':>11}"
    print(head)
    for prov in sorted(kt["provinces"]):
        ks = "".join(f"{kt['provinces'][prov][s]['k']:>9.2f}" for s in seasons)
        c = chk["provinces"].get(prov, {})
        r = "-" if c.get("r2") is None else f"{c['r2']:.3f}"
        e = "-" if c.get("avg_error_pct") is None else f"{c['avg_error_pct']:.1f}"
        print(f"  {prov:<20}{ks}{r:>8}{e:>11}")
    b = chk.get("borneo", {})
    ks = "".join(f"{kt['borneo'][s]['k']:>9.2f}" for s in seasons)
    print(f"  {'Borneo':<20}{ks}{str(b.get('r2', '-')):>8}{str(b.get('avg_error_pct', '-')):>11}")
    if sizes:
        print("\nFiles:")
        for name, mb in sizes.items():
            print(f"  data/processed/{name}  {mb:.2f} MB")
        print(f"  data/processed/{paths.CALIBRATION_K.name}")
    print(f"\nsample data: {'YES' if is_sample else 'no'}")


def run(write_files: bool = True) -> dict:
    df = ingest.load_processed()
    if df.empty:
        raise FileNotFoundError("data/processed/hotspots is empty: run python -m pipeline.ingest --rebuild")
    is_sample = bool(ingest.read_meta().get("is_sample", True))
    res = harmonize(df, load_static_cells())
    sizes = write(res, is_sample) if write_files else None
    print_report(res, is_sample, sizes)
    return res


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
