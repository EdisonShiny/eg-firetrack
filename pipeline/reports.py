"""Situation report, the three lines of System text on each alert (docs/technical.md "The logic" 7).
Sentences live in config/bands.yaml -> report; this module only fills in the numbers."""
from __future__ import annotations

from . import config
from . import stats as st


def _fmt_num(x) -> str:
    v = float(x)
    return f"{int(round(v)):,}" if abs(v - round(v)) < 0.05 else f"{v:,.1f}"


def growth_label(growth_pct: float | None, is_new: bool) -> str:
    t = config.bands()["report"]
    if is_new:
        return t["growth_new"]
    return st.signed_pct(growth_pct)


def situation(a: dict) -> str:
    t = config.bands()["report"]
    w = a.get("weather")
    if not w or w.get("dry_days") is None:
        rain = t["rain_unknown"]
    elif w["dry_days"] == 0:
        rain = t["rain_recent"]
    else:
        rain = t["rain_days"].format(days=w["dry_days"])
    road = t["road_unknown"] if a.get("road_km") is None else f"{a['road_km']:.0f} km"
    return t["situation"].format(
        hotspots=_fmt_num(a["hotspots_24h"]), growth=growth_label(a["growth_pct"], a["is_new"]),
        peat=config.bands()["fuel_on"][a["peat"]], town=a["town"]["name"], town_km=f"{a['town']['km']:.0f}",
        road=road, rain=rain)


def assessment(a: dict) -> str:
    t = config.bands()["report"]
    s = t["assessment"].format(
        anomaly=st.vs_normal_label(a["anomaly_pct"]), month=st.MONTH_NAME[a["month"] - 1],
        chance=st.round_half_up(a["chance_72h_pct"]), words=st.chance_word(a["chance_72h_pct"]),
        score=a["score"], level=a["level"], name=a["level_name"])
    if a.get("chance_source") == "fallback":
        s += t["assessment_fallback_note"]
    return s


def recommendation(a: dict) -> str:
    t = config.bands()["report"]
    row = next(r for r in config.bands()["levels"] if int(r["level"]) == int(a["level"]))
    s = row["directive"]
    if a.get("priority"):
        s += t["critical_add"].format(rank=a["priority"]["rank"], share=a["priority"]["share_pct"])
    return s


def build(a: dict) -> dict:
    return {"situation": situation(a), "assessment": assessment(a), "recommendation": recommendation(a)}
