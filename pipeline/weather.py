"""Weather for fire-event centres (Open-Meteo, free, no key) and the haze-across-a-border estimate.

Used by the daily run for the situation report ("No rain for N days"), the cloud-seeding action and
the haze part of the risk score. Not a model input (no archived weather in this build).
If Open-Meteo is unreachable, every event gets weather = None: the report says "Rain data not
available" and haze counts as "no" (never invented).
"""
from __future__ import annotations

import logging
import math

import numpy as np

from . import config

log = logging.getLogger(__name__)


def wcfg() -> dict:
    return config.load("forecast.yaml")["weather"]


def summarize(daily: dict, today_index: int) -> dict:
    """One location's Open-Meteo daily block -> the numbers the rules use.
    today_index = position of today in the daily arrays (past days come first)."""
    c = wcfg()
    rain = [x if x is not None else 0.0 for x in daily.get("precipitation_sum", [])]
    dry = 0
    for v in reversed(rain[:today_index + 1]):
        if v >= c["dry_day_mm"]:
            break
        dry += 1
    nxt = rain[today_index + 1: today_index + 1 + c["forecast_days"]]

    def at(name):
        v = daily.get(name, [])
        return v[today_index] if len(v) > today_index else None
    return {"dry_days": dry, "rain_next_mm": round(float(sum(nxt)), 1) if nxt else None,
            "cloud_pct": at("cloud_cover_mean"), "wind_kmh": at("wind_speed_10m_max"),
            "wind_from_deg": at("wind_direction_10m_dominant"),
            "humidity_pct": at("relative_humidity_2m_mean"), "temp_max_c": at("temperature_2m_max")}


def fetch(lats, lons, session=None) -> list[dict | None]:
    """One request for all event centres. Returns one summary (or None) per location."""
    if not len(lats):
        return []
    import requests

    c = wcfg()
    params = {
        "latitude": ",".join(f"{x:.3f}" for x in lats), "longitude": ",".join(f"{x:.3f}" for x in lons),
        "daily": "precipitation_sum,cloud_cover_mean,wind_speed_10m_max,wind_direction_10m_dominant,"
                 "relative_humidity_2m_mean,temperature_2m_max",
        "past_days": c["past_days"], "forecast_days": c["forecast_days"] + 1, "timezone": "Asia/Kuching",
    }
    try:
        r = (session or requests).get(c["url"], params=params, timeout=c["timeout_s"])
        r.raise_for_status()
        js = r.json()
    except Exception as exc:  # network down, rate limit, bad answer -> no weather, never invented
        log.warning("Open-Meteo unavailable (%s): weather left empty", type(exc).__name__)
        return [None] * len(lats)
    js = js if isinstance(js, list) else [js]
    return [summarize(j.get("daily", {}), int(c["past_days"])) for j in js]


def drift_points(lat: float, lon: float, wind_kmh: float, wind_from_deg: float) -> list[tuple[float, float]]:
    """Points along the smoke drift (downwind) for haze.days days, every 10 km."""
    h = config.load("forecast.yaml")["haze"]
    per_day = min(float(wind_kmh) * h["km_per_day_per_kmh"], h["max_km_per_day"])
    total = per_day * h["days"]
    to = math.radians((float(wind_from_deg) + 180.0) % 360.0)
    pts = []
    for d in np.arange(10.0, total + 1e-9, 10.0):
        dlat = d * math.cos(to) / 111.32
        dlon = d * math.sin(to) / (111.32 * max(math.cos(math.radians(lat)), 1e-6))
        pts.append((lat + dlat, lon + dlon))
    return pts


def haze_crosses(lat: float, lon: float, country: str, hotspots_24h: float, w: dict | None,
                 countries) -> str | None:
    """Name of the other country the smoke reaches within 3 days, else None.
    countries: GeoDataFrame with columns country, geometry (dissolved per country)."""
    h = config.load("forecast.yaml")["haze"]
    if w is None or hotspots_24h < h["min_hotspots_24h"] or w.get("wind_kmh") is None \
            or w.get("wind_from_deg") is None:
        return None
    from shapely.geometry import Point

    for la, lo in drift_points(lat, lon, w["wind_kmh"], w["wind_from_deg"]):
        p = Point(lo, la)
        for name, geom in zip(countries["country"], countries.geometry):
            if name != country and geom.contains(p):
                return str(name)
    return None
