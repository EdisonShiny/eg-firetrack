"""Repo-relative paths used by the pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
DATA = ROOT / "data"
RAW = DATA / "raw"
RAW_FIRMS = RAW / "firms"
RAW_API = RAW_FIRMS / "api"
RAW_GADM = RAW / "gadm"
PROCESSED = DATA / "processed"
HOTSPOTS_DIR = PROCESSED / "hotspots"
BOUNDARIES = PROCESSED / "boundaries.geojson"
INGEST_META = PROCESSED / "ingest_meta.json"
API_STATUS = PROCESSED / "api_status.json"  # last FIRMS API fetch: times, ok flag, rows per source (never the key)
SAMPLE = DATA / "sample"
SAMPLE_FIRMS = SAMPLE / "firms"
HARMONIZED_CELLS = PROCESSED / "harmonized_cells.parquet"
MONTHLY_COUNTS = PROCESSED / "monthly_counts.parquet"
CALIBRATION_K = PROCESSED / "calibration_k.json"
STATIC_CELLS = PROCESSED / "static_cells.json"
MODELS = PROCESSED / "models"
ALERTS_STATE = PROCESSED / "alerts_state.json"
