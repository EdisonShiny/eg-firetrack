"""Generate the synthetic sample set in data/sample/firms/ (FIRMS archive CSV format).

    python -m pipeline.make_sample

Used only when no FIRMS archive is in data/raw/firms. The numbers are illustrative,
not real detections; every page that uses them shows "sample data".

Realism built in (fixed seed, reproducible):
- fires cluster in peat districts (Kapuas, Pulang Pisau, Ketapang, ...), season peaks Aug-Oct,
  El Nino years 2019 and 2023 are much larger, 2026 is high through September;
- a fire lights several VIIRS 375 m pixels and usually 0-1 MODIS 1 km pixels; some fires
  last several days; some are seen by MODIS only (cloud edge);
- S-NPP stops after 2 Nov 2026, NOAA-20 starts April 2018;
- a few static sources (type 2/3) and low-confidence rows to exercise the filters.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from shapely import contains_xy, prepare

from . import geo, paths

SEED = 20260921
START, END = date(2017, 1, 1), date(2026, 11, 8)
SNPP_END = date(2026, 11, 2)
NOAA20_START = date(2018, 4, 1)

SEASON = [0.25, 0.2, 0.3, 0.3, 0.45, 0.6, 1.0, 2.0, 2.6, 1.7, 0.5, 0.3]   # Jan..Dec
YEAR = {2017: 0.9, 2018: 1.0, 2019: 2.6, 2020: 0.95, 2021: 0.85, 2022: 1.05,
        2023: 2.2, 2024: 0.9, 2025: 0.95, 2026: 1.0}
YEAR_2026_TO_SEP = 1.9          # 2026 is unusually active Jan-Sep (matches the prototype story)
EVENTS_PER_DAY = 2.8            # x SEASON x YEAR, before multi-day persistence
DISTRICT_WEIGHT = {
    "Kapuas": 6, "Pulang Pisau": 6, "Katingan": 4, "Kotawaringin Timur": 4, "Seruyan": 3,
    "Kotawaringin Barat": 2, "Barito Selatan": 2, "Palangka Raya": 2,
    "Ketapang": 5, "Kubu Raya": 3, "Sambas": 1.5, "Sanggau": 1.5, "Sintang": 1.5, "Kapuas Hulu": 1,
    "Banjar": 2, "Barito Kuala": 2, "Tanah Laut": 1.5, "Hulu Sungai Selatan": 1,
    "Kutai Kartanegara": 2.5, "Kutai Timur": 2, "Paser": 1.5, "Berau": 1,
    "Nunukan": 0.8, "Bulungan": 0.8,
    "Miri": 1.2, "Mukah": 1.2, "Bintulu": 0.8, "Sibu": 0.6, "Betong": 0.6, "Samarahan": 0.5, "Kuching": 0.4,
    "Kinabatangan": 0.8, "Beluran": 0.6, "Lahad Datu": 0.6, "Sandakan": 0.4, "Tawau": 0.4,
    "Belait": 0.3, "Tutong": 0.2,
}
OTHER_WEIGHT = 0.15
ZONES_PER_DISTRICT = 8

VIIRS_COLS = ["latitude", "longitude", "bright_ti4", "scan", "track", "acq_date", "acq_time",
              "satellite", "instrument", "confidence", "version", "bright_ti5", "frp", "daynight", "type"]
MODIS_COLS = ["latitude", "longitude", "brightness", "scan", "track", "acq_date", "acq_time",
              "satellite", "instrument", "confidence", "version", "bright_t31", "frp", "daynight", "type"]


def _random_points_in(poly, n, rng):
    prepare(poly)
    minx, miny, maxx, maxy = poly.bounds
    out = []
    while len(out) < n:
        xs = rng.uniform(minx, maxx, 200)
        ys = rng.uniform(miny, maxy, 200)
        ok = contains_xy(poly, xs, ys)
        out.extend(zip(xs[ok], ys[ok]))
    return np.array(out[:n])


def _zones(boundaries, rng):
    """Fire zones (lon, lat) per district plus the district's weight."""
    zones, weights = [], []
    for _, row in boundaries.iterrows():
        w = DISTRICT_WEIGHT.get(row["district"], OTHER_WEIGHT)
        pts = _random_points_in(row.geometry, ZONES_PER_DISTRICT, rng)
        zones.extend(pts)
        weights.extend([w / ZONES_PER_DISTRICT] * len(pts))
    weights = np.array(weights)
    return np.array(zones), weights / weights.sum()


def _hhmm(base_minutes, rng, spread=20):
    m = int(np.clip(base_minutes + rng.normal(0, spread / 2), 0, 23 * 60 + 59))
    return f"{m // 60:02d}{m % 60:02d}"


def _viirs_rows(lon, lat, d, sat, rng, n_pixels, day=True):
    rows = []
    t = _hhmm((5 * 60 + 30) if sat == "N" else (6 * 60 + 20), rng) if day else \
        _hhmm((17 * 60 + 30) if sat == "N" else (18 * 60 + 20), rng)
    for _ in range(n_pixels):
        conf = rng.choice(["n", "h", "l"], p=[0.8, 0.12, 0.08])
        frp = float(np.round(rng.lognormal(1.9, 1.0), 2))
        rows.append([round(lat + rng.normal(0, 0.004), 5), round(lon + rng.normal(0, 0.004), 5),
                     round(float(rng.uniform(305, 367)), 2), 0.39, 0.36, d.isoformat(), t,
                     sat, "VIIRS", conf, "2", round(float(rng.uniform(285, 300)), 2), frp,
                     "D" if day else "N", 0])
    return rows


def _modis_rows(lon, lat, d, sat, rng, n_pixels):
    rows = []
    t = _hhmm(5 * 60 + 35 if sat == "Aqua" else 2 * 60 + 40, rng)
    for _ in range(n_pixels):
        rows.append([round(lat + rng.normal(0, 0.003), 4), round(lon + rng.normal(0, 0.003), 4),
                     round(float(rng.uniform(312, 380)), 1), 1.1, 1.0, d.isoformat(), t,
                     sat, "MODIS", int(rng.integers(20, 101)), "6.1",
                     round(float(rng.uniform(290, 305)), 1),
                     float(np.round(rng.lognormal(2.8, 0.9), 1)), "D", 0])
    return rows


def generate(seed: int = SEED):
    rng = np.random.default_rng(seed)
    boundaries = geo.load_boundaries()
    zones, zw = _zones(boundaries, rng)
    viirs_snpp, viirs_n20, modis = [], [], []

    d = START
    while d <= END:
        yf = YEAR[d.year] * (YEAR_2026_TO_SEP if d.year == 2026 and d.month <= 9 else 1.0)
        n_events = rng.poisson(EVENTS_PER_DAY * SEASON[d.month - 1] * yf)
        for _ in range(n_events):
            z = zones[rng.choice(len(zones), p=zw)]
            lon, lat = z[0] + rng.normal(0, 0.05), z[1] + rng.normal(0, 0.05)
            duration = 1 + rng.geometric(0.6) - 1
            modis_only = rng.random() < 0.08
            for k in range(duration):
                day = d + timedelta(days=k)
                if day > END:
                    break
                size = 1 + rng.poisson(1.0 + 0.6 * k)
                if not modis_only:
                    if day <= SNPP_END:
                        viirs_snpp += _viirs_rows(lon, lat, day, "N", rng, min(size, 9))
                        if rng.random() < 0.25:
                            viirs_snpp += _viirs_rows(lon, lat, day, "N", rng, 1, day=False)
                    if day >= NOAA20_START and rng.random() < (0.45 if day <= SNPP_END else 0.95):
                        viirs_n20 += _viirs_rows(lon, lat, day, "N20", rng, max(1, min(size - 1, 9)))
                if modis_only or rng.random() < 0.55:
                    modis += _modis_rows(lon, lat, day, "Aqua", rng, 1 + (rng.random() < 0.2))
                if rng.random() < 0.3:
                    modis += _modis_rows(lon, lat, day, "Terra", rng, 1)
        d += timedelta(days=1)

    snpp = pd.DataFrame(viirs_snpp, columns=VIIRS_COLS)
    n20 = pd.DataFrame(viirs_n20, columns=VIIRS_COLS)
    mod = pd.DataFrame(modis, columns=MODIS_COLS)

    # a few static sources and offshore flares that cleaning must remove
    for frame in (snpp, mod):
        idx = rng.choice(len(frame), size=max(1, len(frame) // 100), replace=False)
        frame.loc[idx, "type"] = rng.choice([2, 3], size=len(idx))
    return {"fire_archive_M-C61_sample.csv.gz": mod,
            "fire_archive_SV-C2_sample.csv.gz": snpp,
            "fire_archive_J1V-C2_sample.csv.gz": n20}


def main() -> None:
    paths.SAMPLE_FIRMS.mkdir(parents=True, exist_ok=True)
    for name, df in generate().items():
        path = paths.SAMPLE_FIRMS / name
        df.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})
        print(f"{path.relative_to(paths.ROOT)}: {len(df):,} rows, {path.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
