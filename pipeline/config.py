"""Loads config/*.yaml|json and .env. Every threshold and word comes from here."""
from __future__ import annotations

import json
import os
from functools import lru_cache

import yaml

from . import paths

try:  # .env is optional (GitHub Actions passes secrets as env vars)
    from dotenv import load_dotenv

    load_dotenv(paths.ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


@lru_cache(maxsize=None)
def load(name: str):
    """Load config/<name> (.yaml or .json)."""
    path = paths.CONFIG / name
    with open(path, encoding="utf-8") as f:
        if path.suffix == ".json":
            return json.load(f)
        return yaml.safe_load(f)


def data_cfg() -> dict:
    return load("data.yaml")


def bands() -> dict:
    return load("bands.yaml")


def first_year() -> int:
    return int(bands()["data_window"]["first_year"])


def get_map_key() -> str | None:
    """FIRMS key from the environment only. Never log the value."""
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key or key.startswith("your_"):
        return None
    return key


def redact(text: object) -> str:
    """Remove the FIRMS key from any text before it is logged or raised."""
    s = str(text)
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if key:
        s = s.replace(key, "***")
    return s
