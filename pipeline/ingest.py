"""Load, clean and standardize FIRMS hotspots (docs/technical.md "Data" A-C).

    python -m pipeline.ingest --rebuild     # full history from data/raw/firms (or data/sample if empty)
    python -m pipeline.ingest --update      # append the last days from the FIRMS area API
    python -m pipeline.ingest --check-api   # 1-day test call per API source, prints row counts only

The FIRMS key is read from the environment (FIRMS_MAP_KEY) and is never printed or logged.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from . import config, geo, paths

log = logging.getLogger(__name__)

SCHEMA = [
    "lat", "lon", "date", "time_utc", "datetime_utc", "time_myt", "date_myt",
    "sensor", "satellite", "confidence", "frp", "brightness", "daynight", "type",
    "source", "country", "province", "district",
]
DEDUPE_KEYS = ["sensor", "satellite", "_lat4", "_lon4", "date", "time_utc"]
SOURCE_PRIORITY = {"archive": 0, "sample": 0, "nrt": 1}
CATEGORIES = ["date", "date_myt", "time_utc", "sensor", "satellite", "confidence",
              "daynight", "source", "country", "province", "district"]
SAMPLE_WARNING = (
    "\n" + "!" * 72 + "\n"
    "  SAMPLE DATA: no FIRMS archive CSVs found in data/raw/firms/.\n"
    "  Built from data/sample/ (synthetic, illustrative). The site will show 'sample data'.\n"
    "  Add the archive to data/raw/firms/ and run: python -m pipeline.ingest --rebuild\n"
    + "!" * 72
)


class FirmsError(RuntimeError):
    """A FIRMS download problem. Its message never contains the key.
    `reason` is a short, key-free cause for the Data status popover (e.g. "HTTP 403", "timeout")."""

    def __init__(self, message: str, reason: str = "unreachable"):
        super().__init__(message)
        self.reason = reason


def short_reason(err: Exception) -> str:
    """A few key-free words for a failed request: the HTTP status, "timeout" or "connection error"."""
    resp = getattr(err, "response", None)
    status = getattr(resp, "status_code", None)
    if status is None:  # requests.HTTPError raised without a response object: read "403 ..." from the text
        m = re.match(r"\s*(\d{3})(?!\d)", str(err)) if isinstance(err, requests.HTTPError) else None
        status = int(m.group(1)) if m else None
    if status is not None:
        return f"HTTP {status}"
    if isinstance(err, requests.Timeout):
        return "timeout"
    if isinstance(err, requests.ConnectionError):
        return "connection error"
    return type(err).__name__


# --------------------------------------------------------------------------- reading
def _csv_members(path: Path):
    """Yield (name, text-or-bytes buffer) for every CSV in a .csv, .csv.gz or .zip file."""
    name = path.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for m in z.namelist():
                if m.lower().endswith(".csv"):
                    yield m, io.BytesIO(z.read(m))
    elif name.endswith(".csv") or name.endswith(".csv.gz"):
        yield path.name, path


def source_of(name: str, version: object = None) -> str:
    n = name.lower()
    if "sample" in n:
        return "sample"
    if "nrt" in n or str(version or "").upper().endswith("NRT"):
        return "nrt"
    return "archive"


def read_firms_file(path: Path) -> pd.DataFrame:
    """Read one FIRMS file (archive or NRT, MODIS or VIIRS) into the normalized raw form."""
    frames = []
    for name, buf in _csv_members(Path(path)):
        raw = pd.read_csv(buf, dtype={"acq_time": str, "satellite": str, "confidence": str,
                                      "version": str, "daynight": str})
        if raw.empty:
            continue
        version = raw["version"].iloc[0] if "version" in raw.columns else None
        frames.append(normalize_raw(raw, source_of(name, version)))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def find_firms_files(folder: Path, exclude: Path | None = None) -> list[Path]:
    folder = Path(folder)
    if not folder.exists():
        return []
    files = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file():
            continue
        if exclude is not None and Path(exclude) in p.parents:
            continue
        n = p.name.lower()
        if n.endswith((".csv", ".csv.gz", ".zip")):
            files.append(p)
    return files


# --------------------------------------------------------------------------- cleaning
def modis_confidence(values: pd.Series) -> pd.Series:
    bands = config.data_cfg()["confidence"]["modis"]
    num = pd.to_numeric(values, errors="coerce")
    out = pd.Series(pd.NA, index=values.index, dtype="object")
    lower = -np.inf
    for b in bands:
        out[(num > lower) & (num <= b["max"])] = b["level"]
        lower = b["max"]
    return out


def viirs_confidence(values: pd.Series) -> pd.Series:
    mapping = config.data_cfg()["confidence"]["viirs"]
    return values.astype(str).str.strip().str.lower().map(mapping)


def satellite_name(values: pd.Series) -> pd.Series:
    mapping = {str(k): v for k, v in config.data_cfg()["satellites"].items()}
    s = values.astype(str).str.strip()
    s = s.str.replace(r"\.0$", "", regex=True)   # "1.0" if read as float
    return s.map(mapping).fillna(s)


def normalize_raw(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    """FIRMS columns -> lat, lon, date, time_utc, sensor, satellite, confidence, frp, ... ."""
    cols = set(raw.columns)
    cfg = config.data_cfg()
    instrument = str(raw["instrument"].iloc[0]).strip() if "instrument" in cols else ""
    satellite = satellite_name(raw["satellite"].iloc[:1]).iloc[0] if "satellite" in cols else ""
    # Real archive downloads: S-NPP files say instrument "SNPP" (not "VIIRS") and VIIRS brightness
    # can be in a column named "brightness" instead of "bright_ti4".
    is_viirs = ("bright_ti4" in cols or instrument.upper() in {i.upper() for i in cfg["viirs_instruments"]}
                or satellite in cfg["viirs_satellites"])
    sensor = "VIIRS" if is_viirs else "MODIS"
    bright_col = "bright_ti4" if is_viirs and "bright_ti4" in cols else "brightness"
    t = raw["acq_time"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    t = t.str.replace(":", "", regex=False).str.zfill(4)
    out = pd.DataFrame({
        "lat": pd.to_numeric(raw["latitude"], errors="coerce"),
        "lon": pd.to_numeric(raw["longitude"], errors="coerce"),
        "date": pd.to_datetime(raw["acq_date"], errors="coerce").dt.strftime("%Y-%m-%d"),
        "time_utc": t.str[:2] + ":" + t.str[2:4],
        "sensor": sensor,
        "satellite": satellite_name(raw["satellite"]) if "satellite" in cols else sensor,
        "confidence": (viirs_confidence if is_viirs else modis_confidence)(raw["confidence"]),
        "frp": pd.to_numeric(raw.get("frp"), errors="coerce"),
        "brightness": pd.to_numeric(raw[bright_col], errors="coerce") if bright_col in cols else np.nan,
        "daynight": raw["daynight"].astype(str).str.strip() if "daynight" in cols else "",
        "type": (pd.to_numeric(raw["type"], errors="coerce").fillna(cfg["unknown_type"])
                 if "type" in cols else cfg["unknown_type"]),
        "source": source,
    })
    out["type"] = out["type"].astype(int)
    return out.dropna(subset=["lat", "lon", "date"])


def standardize(df: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Filter (type, confidence, window), add UTC/MYT times. Does not tag or dedupe."""
    cfg = config.data_cfg()
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    df = df.copy()
    keep = df["type"].isin(cfg["keep_types"]) | (df["type"] == cfg["unknown_type"])
    keep &= df["confidence"].notna() & ~df["confidence"].isin(cfg["confidence"]["drop"])
    df = df[keep]
    df["datetime_utc"] = pd.to_datetime(df["date"] + " " + df["time_utc"], errors="coerce")
    df = df.dropna(subset=["datetime_utc"])
    df = df[(df["datetime_utc"].dt.year >= config.first_year()) & (df["datetime_utc"] <= now)]
    df["time_myt"] = df["datetime_utc"] + pd.Timedelta(hours=cfg["local_utc_offset_h"])
    df["date_myt"] = df["time_myt"].dt.strftime("%Y-%m-%d")
    return df.reset_index(drop=True)


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Same sensor, satellite, location, date and time -> one row; archive beats NRT."""
    if df.empty:
        return df
    # Round the stored float32 value, so a reloaded file dedupes exactly like the fresh rows did.
    d = df.assign(_lat4=df["lat"].astype("float32").astype(float).round(4),
                  _lon4=df["lon"].astype("float32").astype(float).round(4),
                  _prio=df["source"].astype(str).map(SOURCE_PRIORITY).fillna(9))
    d = d.sort_values("_prio", kind="stable").drop_duplicates(DEDUPE_KEYS, keep="first")
    return d.drop(columns=["_lat4", "_lon4", "_prio"]).sort_values("datetime_utc").reset_index(drop=True)


def finalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in SCHEMA:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[SCHEMA]
    for c in ("lat", "lon", "frp", "brightness"):
        df[c] = df[c].astype("float32")
    df["type"] = df["type"].astype("int8")
    for c in CATEGORIES:
        df[c] = df[c].astype(str).astype("category")
    return df


def clean(raw: pd.DataFrame, boundaries, now: datetime | None = None) -> pd.DataFrame:
    """normalize_raw output -> stored schema (filter, times, Borneo clip + tag, dedupe)."""
    west, south, east, north = config.data_cfg()["firms"]["bbox"]
    raw = raw[raw["lat"].between(south, north) & raw["lon"].between(west, east)]
    df = standardize(raw, now)
    df = geo.tag(df, boundaries)
    return finalize(dedupe(df))


# --------------------------------------------------------------------------- FIRMS API
def api_url(source: str, days: int, key: str) -> str:
    f = config.data_cfg()["firms"]
    bbox = ",".join(str(v) for v in f["bbox"])
    return f["api_url"].format(key=key, source=source, bbox=bbox, days=int(days))


def fetch_api(source: str, days: int, key: str, session=None) -> pd.DataFrame:
    """Download the last `days` days for one source. Empty frame if FIRMS has no data."""
    f = config.data_cfg()["firms"]
    session = session or requests
    days = max(1, min(int(days), int(f["api_max_days"])))
    last_err, reason = None, "unreachable"
    for attempt in range(int(f["retries"]) + 1):
        try:
            resp = session.get(api_url(source, days, key), timeout=f["timeout_s"])
            resp.raise_for_status()
            text = resp.text
            break
        except requests.RequestException as e:  # message contains the URL -> redact
            last_err = config.redact(f"{type(e).__name__}: {e}")
            reason = config.redact(short_reason(e))
            log.warning("FIRMS %s attempt %d failed: %s", source, attempt + 1, last_err)
            if attempt < int(f["retries"]):
                time.sleep(2 * (attempt + 1))
    else:
        raise FirmsError(f"FIRMS {source} unreachable: {last_err}", reason)

    head = text.lstrip()[:200].lower()
    if "invalid map_key" in head or "invalid api" in head:
        raise FirmsError(f"FIRMS {source}: key rejected", "FIRMS_MAP_KEY rejected by FIRMS")
    if not head.startswith("latitude"):
        log.warning("FIRMS %s returned no CSV (%s)", source, config.redact(text.strip()[:80]))
        return pd.DataFrame()
    raw = pd.read_csv(io.StringIO(text), dtype={"acq_time": str, "satellite": str,
                                               "confidence": str, "version": str, "daynight": str})
    if raw.empty:
        return pd.DataFrame()
    try:  # cache for a later --rebuild (data/raw is gitignored)
        paths.RAW_API.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
        (paths.RAW_API / f"fire_nrt_{source}_{stamp}.csv").write_text(text, encoding="utf-8")
    except OSError:
        pass
    return normalize_raw(raw, "nrt")


def fetch_all(days: int, key: str | None, session=None) -> tuple[pd.DataFrame, dict]:
    """All configured API sources. Returns (rows, {source: count or error})."""
    report: dict[str, object] = {}
    if not key:
        log.warning("FIRMS_MAP_KEY is not set: skipping the FIRMS download.")
        return pd.DataFrame(), {"error": "no key"}
    frames = []
    for source in config.data_cfg()["firms"]["api_sources"]:
        try:
            df = fetch_api(source, days, key, session)
            report[source] = len(df)
            if len(df):
                frames.append(df)
        except FirmsError as e:
            report[source] = f"error: {e.reason}"
    rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return rows, report


def api_fetch_ok(report: dict) -> bool:
    """A fetch is good when the key was set and every source answered (an empty answer is fine)."""
    return bool(report) and "error" not in report and all(isinstance(v, int) for v in report.values())


def failure_reason(report: dict) -> str | None:
    """Short, key-free reason a fetch failed, for meta.json / the Data status popover. None if it worked."""
    if api_fetch_ok(report):
        return None
    if not report or report.get("error") == "no key":
        return "FIRMS_MAP_KEY missing"
    bad = {s: str(v).removeprefix("error: ") for s, v in report.items() if not isinstance(v, int)}
    if len(set(bad.values())) == 1:
        text = next(iter(bad.values()))
        if len(bad) < len(report):  # only some sources failed: say which
            text += f" ({', '.join(bad)})"
    else:
        text = "; ".join(f"{s}: {r}" for s, r in bad.items())
    return config.redact(text)[:120]


def read_api_status(path: Path | None = None) -> dict:
    p = Path(path or paths.API_STATUS)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def record_api_status(report: dict, now: datetime | None = None, path: Path | None = None) -> dict:
    """Save the result of the last FIRMS API fetch for the website's Data status button.
    Only timestamps, an ok flag, row counts and a short failure reason (e.g. "FIRMS_MAP_KEY missing",
    "HTTP 403") are stored: never the key, URLs or raw error text.
    A failed fetch keeps the previous last success and its row counts."""
    p = Path(path or paths.API_STATUS)
    prev = read_api_status(p)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ok = api_fetch_ok(report)
    status = {
        "api_last_attempt": stamp,
        "api_ok": ok,
        "api_last_success": stamp if ok else prev.get("api_last_success"),
        "api_rows_by_source": {str(s): int(n) for s, n in report.items()} if ok else prev.get("api_rows_by_source", {}),
        "api_error": failure_reason(report),
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


# --------------------------------------------------------------------------- storage
def load_processed(folder: Path = paths.HOTSPOTS_DIR) -> pd.DataFrame:
    files = sorted(Path(folder).glob("year=*.parquet"))
    if not files:
        return pd.DataFrame(columns=SCHEMA)
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def read_meta() -> dict:
    if paths.INGEST_META.exists():
        return json.loads(paths.INGEST_META.read_text(encoding="utf-8"))
    return {}


def write_processed(df: pd.DataFrame, *, is_sample: bool, inputs: list[str],
                    years: set[int] | None = None, folder: Path = paths.HOTSPOTS_DIR) -> dict:
    """Write one Parquet per year (only `years` if given) and ingest_meta.json."""
    limit_mb = config.data_cfg()["processed"]["max_file_mb"]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    year_of = pd.to_datetime(df["date"].astype(str)).dt.year
    present = set(int(y) for y in year_of.unique())
    if years is None:  # full rewrite: remove stale year files
        for f in folder.glob("year=*.parquet"):
            if int(f.stem.split("=")[1]) not in present:
                f.unlink()
    sizes = {}
    for y in sorted(present if years is None else (present & set(years))):
        part = finalize(df[year_of == y]).reset_index(drop=True)
        path = folder / f"year={y}.parquet"
        part.to_parquet(path, compression="zstd", index=False)
        mb = path.stat().st_size / 1e6
        if mb >= limit_mb:
            raise RuntimeError(f"{path.name} is {mb:.1f} MB (limit {limit_mb} MB): split or aggregate it")
        sizes[y] = round(mb, 2)

    counts = (df.groupby([year_of.rename("year"), df["sensor"].astype(str)]).size()
              .unstack(fill_value=0))
    meta = {
        "is_sample": bool(is_sample),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through_utc": str(df["datetime_utc"].max()) if len(df) else None,
        "rows": int(len(df)),
        "rows_per_year_sensor": {str(y): {k: int(v) for k, v in r.items()} for y, r in counts.iterrows()},
        "satellites": sorted(df["satellite"].astype(str).unique().tolist()),
        "sources": sorted(df["source"].astype(str).unique().tolist()),
        "inputs": inputs,
    }
    paths.INGEST_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    meta["written_mb"] = sizes
    return meta


def print_summary(df: pd.DataFrame, is_sample: bool) -> None:
    if is_sample:
        print(SAMPLE_WARNING)
    year = pd.to_datetime(df["date"].astype(str)).dt.year
    table = df.groupby([year.rename("year"), df["satellite"].astype(str)]).size().unstack(fill_value=0)
    table["total"] = table.sum(axis=1)
    print("\nRows per year x satellite (after cleaning):")
    print(table.to_string())
    print("\nFiles:")
    for f in sorted(paths.HOTSPOTS_DIR.glob("year=*.parquet")):
        print(f"  {f.relative_to(paths.ROOT)}  {f.stat().st_size / 1e6:.2f} MB")
    print(f"\nTotal rows {len(df):,}; data through {df['datetime_utc'].max()} UTC; "
          f"sample data: {'YES' if is_sample else 'no'}")


# --------------------------------------------------------------------------- commands
def rebuild(now: datetime | None = None) -> pd.DataFrame:
    if not paths.BOUNDARIES.exists() and paths.RAW_GADM.exists():
        geo.simplify_and_save(geo.build_boundaries())
    boundaries = geo.load_boundaries()
    archive = find_firms_files(paths.RAW_FIRMS, exclude=paths.RAW_API)
    is_sample = not archive
    files = find_firms_files(paths.SAMPLE_FIRMS) if is_sample else archive + find_firms_files(paths.RAW_API)
    if not files:
        raise FileNotFoundError("No FIRMS files in data/raw/firms and no sample in data/sample/firms.")
    if is_sample:
        log.warning("No FIRMS archive in data/raw/firms: using data/sample (sample data).")
    raw = pd.concat([read_firms_file(f) for f in files], ignore_index=True)
    df = clean(raw, boundaries, now)
    write_processed(df, is_sample=is_sample, inputs=[str(f.relative_to(paths.ROOT)) for f in files])
    print_summary(df, is_sample)
    return df


def update(now: datetime | None = None, session=None) -> dict:
    """Append the latest FIRMS NRT rows to data/processed. Never fails the daily run."""
    meta = read_meta()
    if not meta or not any(paths.HOTSPOTS_DIR.glob("year=*.parquet")):
        log.warning("data/processed is empty: building from data/sample (sample data).")
        rebuild(now)
        meta = read_meta()
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    through = pd.to_datetime(meta.get("data_through_utc")) if meta.get("data_through_utc") else None
    gap_days = (now - through).days + 1 if through is not None else 10
    days = max(1, min(gap_days, int(config.data_cfg()["firms"]["api_max_days"])))

    raw, report = fetch_all(days, config.get_map_key(), session)
    record_api_status(report)
    result = {"days": days, "api": report, "added": 0, "is_sample": meta.get("is_sample", True)}
    if raw.empty:
        log.warning("No new FIRMS rows; keeping existing data.")
        return result
    new = clean(raw, geo.load_boundaries(), now)
    if meta.get("is_sample"):
        log.warning("History is sample data: %d live rows seen but not merged "
                    "(add the archive and run --rebuild).", len(new))
        result["live_rows_seen"] = int(len(new))
        return result

    old = load_processed()
    merged, years = merge_new(old, new)
    write_processed(merged, is_sample=False, inputs=meta.get("inputs", []) + ["FIRMS API"], years=years)
    result["added"] = int(len(merged) - len(old))
    log.info("Added %d new rows (%s).", result["added"], report)
    return result


def merge_new(old: pd.DataFrame, new: pd.DataFrame) -> tuple[pd.DataFrame, set[int]]:
    """Append new rows. Only the years the new rows touch are deduped (and later rewritten);
    other years stay exactly as stored, so ingest_meta row counts always match the files."""
    years = set(pd.to_datetime(new["date"].astype(str)).dt.year.astype(int))
    years = {y for y in years if y >= config.first_year()}
    old = old.astype({c: str for c in CATEGORIES})
    old_year = pd.to_datetime(old["date"]).dt.year
    touched = pd.concat([old[old_year.isin(years)], new.astype({c: str for c in CATEGORIES})],
                        ignore_index=True)
    touched = dedupe(touched)
    touched = touched[pd.to_datetime(touched["date"]).dt.year.isin(years)]
    merged = pd.concat([old[~old_year.isin(years)], touched], ignore_index=True)
    return merged.sort_values("datetime_utc").reset_index(drop=True), years


def check_api(session=None) -> dict:
    key = config.get_map_key()
    if not key:
        print("FIRMS_MAP_KEY is not set in .env / environment.")
        return {"error": "no key"}
    _, report = fetch_all(1, key, session)
    print("FIRMS area API, last 1 day, Borneo box (rows before cleaning):")
    for source, n in report.items():
        print(f"  {source:<18} {n}")
    return report


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--rebuild", action="store_true")
    g.add_argument("--update", action="store_true")
    g.add_argument("--check-api", action="store_true")
    a = p.parse_args(argv)
    if a.rebuild:
        rebuild()
    elif a.update:
        print(json.dumps(update(), indent=2, default=str))
    else:
        check_api()


if __name__ == "__main__":
    main()
