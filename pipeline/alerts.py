"""Daily alerts: fire events -> chance of spreading -> rules -> situation reports (docs/technical.md
"The logic" 1-9), plus the next-day check, the per-area rescue risk status and the 2019/2023 backtest.

State between daily runs (event IDs, level stability, closing) is kept in
data/processed/alerts_state.json. Re-running on the same day starts again from the state of the
previous day, so a second run gives the same answer.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from . import config, events, features, forecast, paths, reports, rules, weather
from . import stats as st

log = logging.getLogger(__name__)

MYT = pd.Timedelta(hours=int(config.data_cfg()["local_utc_offset_h"]))


def fc() -> dict:
    return config.load("forecast.yaml")


def myt_day(ts) -> date:
    return (pd.Timestamp(ts) + MYT).date()


def slug(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


# --------------------------------------------------------------------------- compared to normal
def daily_counts(cells: pd.DataFrame) -> pd.DataFrame:
    d = cells.groupby(["day", "province", "district"], observed=True)["weight"].sum().reset_index()
    dt = pd.to_datetime(d["day"].astype(str))
    return d.assign(year=dt.dt.year, month=dt.dt.month, dom=dt.dt.day)


def anomalies(daily: pd.DataFrame, day: date, exclude_year: int | None = None) -> dict:
    """Month so far (day 1..day) in harmonized fire cells vs the same days in each full year, per
    district and province. Values are (current, [same window in each full year]) for
    st.compare_to_normal, the same rule as the Summary "Compared to normal" (month window)."""
    yrs = [y for y in st.median_years() if y != exclude_year and y != day.year]
    sub = daily[(daily["month"] == day.month) & (daily["dom"] <= day.day) & daily["year"].isin(yrs + [day.year])]
    out = {}
    for level, keys in (("district", ["province", "district"]), ("province", ["province"])):
        pv = sub.pivot_table(index=keys, columns="year", values="weight", aggfunc="sum", fill_value=0.0)
        pv = pv.reindex(columns=yrs + [day.year], fill_value=0.0)
        out[level] = {k: (float(pv.at[k, day.year]), [float(pv.at[k, y]) for y in yrs]) for k in pv.index}
    out["years"] = yrs
    return out


def event_anomaly(an: dict, province: str, district: str) -> tuple[float | None, str | None, str]:
    """District baseline when the district's own median reaches the floor (bands.yaml
    compared_to_normal_rule.floor_cells), else the province's, floored the same way."""
    floor = float(st.cmp_rule()["floor_cells"])
    empty = (0.0, [0.0] * len(an.get("years", [])))
    for basis, key in (("district", (province, district)), ("province", province)):
        cur, past = an[basis].get(key, empty)
        r = st.compare_to_normal(cur, past)
        if basis == "province" or r["median"] >= floor:
            return r["pct"], r["status"], basis
    return None, None, "none"


# --------------------------------------------------------------------------- towns
def towns() -> list[dict]:
    return [{"name": p["name"], "lat": float(p["lat"]), "lon": float(p["lon"]), "area": p["area"]}
            for p in config.load("places.yaml")["places"]]


def nearest_town(lat: float, lon: float, tw: list[dict]) -> dict:
    d = events.haversine_km(lat, lon, np.array([t["lat"] for t in tw]), np.array([t["lon"] for t in tw]))
    i = int(np.argmin(d))
    return {"name": tw[i]["name"], "km": round(float(d[i]), 1)}


def nearby_teams(lat: float, lon: float, lead: str, tw: list[dict]) -> list[dict]:
    lim = float(fc()["people"]["teams_within_km"])
    out = []
    for t in tw:
        km = float(events.haversine_km(lat, lon, t["lat"], t["lon"]))
        if km <= lim:
            out.append({"town": t["name"], "km": round(km, 1), "team": f"Response team based in {t['name']}"})
    return sorted(out, key=lambda x: x["km"])


# --------------------------------------------------------------------------- chance of spreading
class Chance:
    """72-hour chance per 0.1 deg cell: the model, or compared-to-normal fallback."""

    def __init__(self, cells: pd.DataFrame, day: date, boundaries, forecaster=None, daily=None):
        self.fc = forecaster
        self.mode = forecaster.mode if forecaster is not None else forecast.FALLBACK
        self.day = day
        self.daily = daily if daily is not None else daily_counts(cells)
        start = day - pd.Timedelta(days=int(fc()["grid"]["scoring_history_days"]))
        self.panel = features.build_panel(cells, start, day, boundaries)
        years = forecaster.card["climatology_years"] if forecaster is not None else \
            list(range(st.median_years()[0], st.median_years()[-1]))
        self.clim = features.climatology(cells, self.panel, years)
        self._rows = {}

    def rows(self, d: date) -> pd.DataFrame:
        if d not in self._rows:
            self._rows[d] = features.rows(self.panel, self.clim, day_from=d, day_to=d, only_candidates=False)
        return self._rows[d]

    def uses_model(self) -> bool:
        return self.fc is not None and self.mode == "model"

    def for_cells(self, lat, lon, d: date, province: str, district: str, an: dict | None = None) -> dict:
        """Chance for a group of cells (an event) on day d: the highest cell chance."""
        if not self.uses_model():
            an = an if an is not None else anomalies(self.daily, d)
            _, status, _ = event_anomaly(an, province, district)
            p = rules.fallback_chance(status)
            return {"p24": p, "p48": p, "p72": p, "reasons": [], "source": "fallback"}
        r = self.rows(d)
        idx = np.unique(self.panel.lookup(lat, lon))
        sub = r[r["i"].isin(idx[idx >= 0])]
        if sub.empty:
            return {"p24": 0.0, "p48": 0.0, "p72": 0.0, "reasons": [], "source": "model"}
        p = {h: self.fc.predict(sub, h) for h in (1, 2, 3)}
        j = int(np.argmax(p[3]))
        return {"p24": float(p[1].max()), "p48": float(p[2].max()), "p72": float(p[3][j]),
                "reasons": self.fc.reasons(sub.iloc[[j]], 3)[0], "source": "model"}

    def area_cells(self) -> pd.DataFrame:
        """Today's chance for every scored cell, with its province / district (Rescue risk tile)."""
        r = features.rows(self.panel, self.clim, day_from=self.day, day_to=self.day)
        if r.empty:
            return pd.DataFrame(columns=["province", "district", "p72"])
        if self.uses_model():
            p = self.fc.predict(r, 3)
        else:
            an = anomalies(self.daily, self.day)
            p = np.array([rules.fallback_chance(event_anomaly(an, self.panel.province[i], self.panel.district[i])[1])
                          for i in r["i"]])
        return pd.DataFrame({"province": self.panel.province[r["i"]], "district": self.panel.district[r["i"]],
                             "p72": p})

    def next_day_check(self, days: int) -> dict:
        """Each of the last `days` days: the 24 h part of the outlook (>= cut-off = warning) vs whether
        the cell then had a new hotspot. Counted over the scored cell-days."""
        cut = float(forecast.mcfg()["cutoff"])
        d0 = self.day - pd.Timedelta(days=days)
        d1 = self.day - pd.Timedelta(days=1)
        r = features.rows(self.panel, self.clim, day_from=d0, day_to=d1)
        r = r[r["y1"].notna()]
        if r.empty:
            return {"days": days, "cell_days": 0, "correct": 0, "missed": 0, "false_alarm": 0,
                    "hit_rate": None, "false_alarm_rate": None}
        if self.uses_model():
            p = self.fc.predict(r, 1)
        else:
            p = np.zeros(len(r))
            for d, g in r.groupby("d"):
                an = anomalies(self.daily, self.panel.date_of(d))
                p[r.index.get_indexer(g.index)] = [
                    rules.fallback_chance(event_anomaly(an, self.panel.province[i], self.panel.district[i])[1])
                    for i in g["i"]]
        y = r["y1"].to_numpy() > 0
        warn = p >= cut
        tp, fp, fn = int((warn & y).sum()), int((warn & ~y).sum()), int((~warn & y).sum())
        return {"days": days, "from": str(d0), "to": str(d1), "cell_days": int(len(r)),
                "correct": int(len(r) - fp - fn), "missed": fn, "false_alarm": fp,
                "hit_rate": None if tp + fn == 0 else round(tp / (tp + fn), 3),
                "false_alarm_rate": None if tp + fp == 0 else round(fp / (tp + fp), 3)}


def check_word(said: float, saw_new: bool) -> str:
    cut = float(forecast.mcfg()["cutoff"])
    if said >= cut:
        return "correct" if saw_new else "false_alarm"
    return "missed" if saw_new else "correct"


# --------------------------------------------------------------------------- state
def load_state(path=paths.ALERTS_STATE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def base_state(state: dict, day: date) -> dict:
    """The state of the last day before `day` (re-runs on the same day reuse the same base)."""
    if not state:
        return {}
    if state.get("as_of") and state["as_of"] < str(day):
        return state
    return state.get("base") or {}


# --------------------------------------------------------------------------- scoring one event
def inputs_for(ev: dict, chance: dict, an: dict, w: dict | None, haze_country: str | None,
               tw: list[dict]) -> tuple[rules.EventInputs, dict]:
    is_new = ev["prev_24h"] <= 0
    growth = float(config.bands()["new_event_growth_pct"]) if is_new else st.pct_change(ev["hotspots_24h"], ev["prev_24h"])
    pct, status, basis = event_anomaly(an, ev["province"], ev["district"])
    town = nearest_town(ev["lat"], ev["lon"], tw)
    e = rules.EventInputs(
        chance_72h=chance["p72"], anomaly_pct=pct, frp_sum=ev["frp_sum_24h"], growth_pct=float(growth),
        peat=features.peat_of(ev["district"]), km_to_town=town["km"], haze_to_border=haze_country is not None,
        hotspots_24h=ev["hotspots_24h"], prev_24h=ev["prev_24h"], road_km=None,
        cloud_pct=None if w is None else w.get("cloud_pct"),
        rain_next_mm=None if w is None else w.get("rain_next_mm"))
    extra = {"is_new": is_new, "anomaly_status": status, "anomaly_basis": basis, "town": town}
    return e, extra


def _countries(boundaries):
    return boundaries.dissolve(by="country", as_index=False)[["country", "geometry"]]


# --------------------------------------------------------------------------- daily build
def build(cells: pd.DataFrame, through: pd.Timestamp, boundaries, area_ids: list[str], *,
          forecaster="auto", weather_fn=weather.fetch, state: dict | None = None,
          is_sample: bool = True) -> dict:
    day = myt_day(through)
    forecaster = forecast.load() if forecaster == "auto" else forecaster
    state = load_state() if state is None else state
    base = base_state(state, day)
    base_events = base.get("events", [])
    tw = towns()
    cells = cells[cells["t"] <= through]
    daily = daily_counts(cells)
    an = anomalies(daily, day)
    an_y = anomalies(daily, day - pd.Timedelta(days=1))
    ch = Chance(cells, day, boundaries, forecaster, daily)

    evs, watch = events.build(cells, through)
    evs = events.assign_ids(evs, base_events, day)
    wx = weather_fn([e["lat"] for e in evs], [e["lon"] for e in evs]) if evs else []
    countries = None
    jur = config.load("jurisdictions.json")
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    recs = []
    for ev, w in zip(evs, wx or [None] * len(evs)):
        lat, lon = np.array(ev["cells"])[:, 0], np.array(ev["cells"])[:, 1]
        c = ch.for_cells(lat, lon, day, ev["province"], ev["district"], an)
        haze = None
        if w is not None and ev["hotspots_24h"] >= fc()["haze"]["min_hotspots_24h"]:
            countries = countries if countries is not None else _countries(boundaries)
            haze = weather.haze_crosses(ev["lat"], ev["lon"], ev["country"], ev["hotspots_24h"], w, countries)
        e, extra = inputs_for(ev, c, an, w, haze, tw)
        score, lv_new, why = rules.level_for(e)
        prev = ev.get("matched")
        lv, below = rules.stable_level(lv_new, prev["level"] if prev else None, prev["days_below"] if prev else 0)
        held = lv != lv_new
        dw = rules.days_without(prev["days_without_hotspots"] if prev else 0, ev["hotspots_24h"])
        # next-day check: yesterday's 24 h outlook for these cells vs new hotspots today
        cy = ch.for_cells(lat, lon, day - pd.Timedelta(days=1), ev["province"], ev["district"], an_y)
        hist = list(prev["history"]) if prev else []
        if not hist or hist[-1]["level"] != lv:
            hist.append({"day": str(day), "level": lv, "score": score,
                         "why": "; ".join(why) or ("held: down only after 2 days below" if held else "score band")})
        rec = {
            "id": ev["id"], "level": lv, "level_computed": lv_new, "days_below": below,
            "days_without_hotspots": dw, "score": score, "overrides": why, "outlier_review": rules.is_outlier(e),
            "province": ev["province"], "district": ev["district"], "country": ev["country"],
            "place": f"{ev['district']}, {ev['province']}", "area": slug(ev["province"]),
            "lat": round(ev["lat"], 4), "lon": round(ev["lon"], 4),
            "issued_utc": prev["issued_utc"] if prev else pd.Timestamp(ev["first_utc"]).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_utc": gen, "utc_offset_h": jur[ev["province"]]["utc_offset_h"],
            "hotspots_24h": round(ev["hotspots_24h"], 1), "prev_24h": round(ev["prev_24h"], 1),
            "hotspots_48h": round(ev["hotspots_48h"], 1), "growth_pct": round(e.growth_pct, 1),
            "is_new": extra["is_new"], "frp_sum_24h": round(ev["frp_sum_24h"], 1), "frp_max": round(ev["frp_max"], 1),
            "chance_24h_pct": round(c["p24"] * 100, 1), "chance_48h_pct": round(c["p48"] * 100, 1),
            "chance_72h_pct": round(c["p72"] * 100, 1), "chance_word": st.chance_word(c["p72"] * 100),
            "chance_source": c["source"], "reasons": c["reasons"],
            "anomaly_pct": None if e.anomaly_pct is None else round(e.anomaly_pct, 1),
            "anomaly_status": extra["anomaly_status"], "anomaly_basis": extra["anomaly_basis"],
            "month": day.month, "peat": e.peat, "fuel": config.bands()["fuel_words"][e.peat],
            "town": extra["town"], "road_km": None,
            "score_parts": {k: round(v, 1) for k, v in rules.score_parts(e).items()},
            "haze": {"to_border": haze is not None, "country": haze},
            "weather": w,
            "last_check": {"said_24h_pct": round(cy["p24"] * 100, 1), "saw_new": ev["hotspots_24h"] > 0,
                           "result": check_word(cy["p24"], ev["hotspots_24h"] > 0)},
            "days": ev["days"], "history": hist[-10:],
            "_inputs": e,
        }
        recs.append(rec)

    # events seen before but not today: keep until closed (3 days with no hotspots)
    matched_ids = {r["id"] for r in recs}
    closed = []
    for p in base_events:
        if p["id"] in matched_ids:
            continue
        dw = p["days_without_hotspots"] + 1
        if rules.is_closed(dw):
            closed.append(p["id"])
            continue
        r = {k: v for k, v in p.items()}
        r.update({"days_without_hotspots": dw, "hotspots_24h": 0.0, "prev_24h": 0.0, "updated_utc": gen,
                  "growth_pct": -100.0, "is_new": False})
        r["_inputs"] = None
        recs.append(r)

    finish(recs, tw)
    recs.sort(key=lambda r: (-r["level"], (r.get("priority") or {}).get("rank", 999), -r["score"]))
    levels = [x["name"].lower() for x in config.bands()["levels"]][::-1]
    counts = {a: {lv: 0 for lv in levels} for a in ["borneo"] + area_ids}
    for r in recs:
        name = rules.level_row(r["level"])["name"].lower()
        counts["borneo"][name] += 1
        if r["area"] in counts:
            counts[r["area"]][name] += 1
    public = [{k: v for k, v in r.items() if not k.startswith("_")} for r in recs]
    doc = {
        "is_stub": False, "is_sample": is_sample, "generated_at": gen, "as_of_day": str(day),
        "data_through_utc": pd.Timestamp(through).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": ch.mode, "model_version": None if forecaster is None else forecaster.version,
        "note": ("SAMPLE DATA: alerts computed from synthetic detections, not real fires. " if is_sample else "")
                + ("Chance of spreading from compared to normal (fallback): the model did not beat both baselines."
                   if ch.mode != "model" else "Chance of spreading from the 72-hour System model."),
        "weather_note": None if not evs or any(w is not None for w in (wx or [])) else
        "Open-Meteo unavailable: rain and haze not checked today.",
        "counts": counts, "watch": int(len(watch)), "closed_today": closed, "alerts": public,
    }
    new_state = {"as_of": str(day), "events": public, "base": {k: v for k, v in base.items() if k != "base"}}
    return {"doc": doc, "state": new_state, "chance": ch, "area_cells": ch.area_cells(),
            "check": ch.next_day_check(int(forecast.mcfg()["next_day_check_days"]))}


def finish(recs: list[dict], tw: list[dict]) -> None:
    """Rescue priority + team share (Critical only), then actions, resources, who, report."""
    crit = int(config.bands()["levels"][-1]["level"])
    pr = {r["id"]: rules.priority(r["score"], r["town"]["km"], r["growth_pct"]) for r in recs if r["level"] == crit}
    ranks = rules.rank_critical(pr)
    for r in recs:
        r["priority"] = ranks.get(r["id"])
        r["anomaly_label"] = st.vs_normal_label(r.get("anomaly_pct"))
        e = r.get("_inputs") or rules.EventInputs(
            chance_72h=r["chance_72h_pct"] / 100, anomaly_pct=r["anomaly_pct"], frp_sum=r["frp_sum_24h"],
            growth_pct=r["growth_pct"], peat=r["peat"], km_to_town=r["town"]["km"],
            haze_to_border=r["haze"]["to_border"], hotspots_24h=r["hotspots_24h"], prev_24h=r["prev_24h"],
            cloud_pct=(r.get("weather") or {}).get("cloud_pct"), rain_next_mm=(r.get("weather") or {}).get("rain_next_mm"))
        lv = r["level"]
        row = rules.level_row(lv)
        who = rules.who_responds(r["province"], lv, r["haze"]["to_border"])
        note = rules.notification(lv)
        r["level_name"] = row["name"]
        r["directive"] = row["directive"]
        r["status"] = status_word(lv, r["days_without_hotspots"])
        r["actions"] = rules.actions(lv, e)
        r["resources"] = rules.resources(lv, r["peat"], r["hotspots_24h"], r["town"]["km"], r["road_km"])
        r["coordination"] = {**who, "channel": note["channel"], "if_no_response": note["no_response"],
                             "deploy_within_h": row["deploy_within_h"]}
        r["nearby_teams"] = nearby_teams(r["lat"], r["lon"], who["lead"], tw)
        r["report"] = reports.build(r)


def status_word(level: int, days_without: int) -> str:
    s = config.bands()["alert_status"]
    if days_without > 0:
        return s["closing"]
    return s["notified"] if level >= s["notified_from_level"] else s["monitoring"]


def save_state(new_state: dict, path=paths.ALERTS_STATE) -> None:
    path.write_text(json.dumps(new_state, separators=(",", ":"), ensure_ascii=False, default=str), encoding="utf-8")


# --------------------------------------------------------------------------- rescue risk (Analysis)
def area_risk(alerts: list[dict], scope: dict, area_cells: pd.DataFrame, mode: str) -> dict:
    """Status = highest alert level in the area; score = highest event score; chance = highest event
    chance (else the highest cell chance in the area); fuel; people nearby (events within 15 km of a town)."""
    t = config.bands()["rescue_risk_texts"]
    fcfg = fc()

    def inside(prov, dist):
        if scope["province"] is None:
            return True
        return prov == scope["province"] and (scope["district"] is None or dist == scope["district"])
    a = [r for r in alerts if inside(r["province"], r["district"])]
    cells = area_cells[[inside(p, d) for p, d in zip(area_cells["province"], area_cells["district"])]] \
        if len(area_cells) else area_cells
    near_km = float(fcfg["people"]["town_near_km"])
    if a:
        top = max(a, key=lambda r: (r["level"], r["score"]))
        lv = top["level"]
        score = top["score"]
        chance = max(r["chance_72h_pct"] for r in a)
        fuel = {"value": top["fuel"], "note": t["fuel_event_note"].format(source=fcfg["peat"]["source"])}
        note = None
    else:
        lv, score, top = int(config.bands()["levels"][0]["level"]), None, None
        chance = round(float(cells["p72"].max()) * 100, 1) if len(cells) else None
        dists = boundaries_districts(scope)
        order = {"none": 0, "shallow": 1, "deep": 2}
        deepest = max((features.peat_of(d) for d in dists), key=lambda p: order[p], default="none")
        fuel = {"value": config.bands()["fuel_words"][deepest],
                "note": t["fuel_area_note"].format(source=fcfg["peat"]["source"])}
        note = t["no_events"]
    n_near = sum(1 for r in a if r["town"]["km"] <= near_km)
    row = rules.level_row(lv)
    return {"is_stub": False, "mode": mode, "note": note, "level": lv, "level_name": row["name"], "score": score,
            "directive": row["directive"], "events": len(a),
            "chance": {"pct": chance, "word": st.chance_word(chance), "source": "model" if mode == "model" else "fallback"},
            "fuel_type": fuel,
            "people_nearby": {"value": str(n_near), "note": t["people"].format(n=n_near, km=f"{near_km:g}")}}


_DISTRICTS: dict = {}


def boundaries_districts(scope: dict) -> list[str]:
    if "all" not in _DISTRICTS:
        from . import geo
        b = geo.load_boundaries()
        _DISTRICTS["all"] = list(zip(b["province"].astype(str), b["district"].astype(str)))
    if scope["district"] is not None:
        return [scope["district"]]
    return [d for p, d in _DISTRICTS["all"] if scope["province"] is None or p == scope["province"]]


# --------------------------------------------------------------------------- model.json
def model_doc(card: dict | None, check: dict, is_sample: bool) -> dict:
    if card is None:
        return {"is_stub": False, "is_sample": is_sample, "mode": forecast.FALLBACK, "version": None,
                "note": "No trained model found (run python -m pipeline.train). The chance of spreading comes "
                        "from compared to normal.", "model": None, "baselines": None, "next_day_check": check}
    m = card["model1"]
    h72 = m[str(max(int(k) for k in m))]
    keep = ("auc", "hit_rate", "false_alarm_rate", "brier")
    pick = lambda d: {k: d[k] for k in keep}
    p, b = h72["model"], h72["burned_yesterday"]
    return {
        "is_stub": False, "is_sample": is_sample, "mode": card["mode"], "mode_reason": card["mode_reason"],
        "version": card["version"], "trained_at": card["trained_at"], "trained_on_sample": card["is_sample"],
        "note": ("Trained and checked on SAMPLE DATA (synthetic): the numbers show the method works, not real "
                 "skill. " if card["is_sample"] else "")
                + "Beat both baselines = higher AUC and lower Brier score in the test year. Hit rate and false alarm "
                  f"rate use a 50% cut-off: at that cut-off 'burned yesterday' warns about more fires "
                  f"({_pct(b['hit_rate'])} vs {_pct(p['hit_rate'])}) but with more false alarms "
                  f"({_pct(b['false_alarm_rate'])} vs {_pct(p['false_alarm_rate'])}).",
        "test_year": card["split"]["test_year"], "split": card["split"],
        "model": pick(p), "baselines": {"burned_yesterday": pick(b), "usual_for_month": pick(h72["usual_for_month"])},
        "beats_baselines": h72["beats_baselines"],
        "horizons": {f"{int(k) * 24}h": {"auc": v["model"]["auc"], "brier": v["model"]["brier"],
                                          "beats_baselines": v["beats_baselines"]} for k, v in m.items()},
        "test_rows": h72["rows"]["test"], "positives": p["positives"],
        "inputs": card["features"], "not_used": card["not_used"],
        "monthly": card["model2"],
        "backtest": card.get("backtest"),
        "next_day_check": check,
    }


def _pct(x):
    return "-" if x is None else f"{x * 100:.0f}%"


# --------------------------------------------------------------------------- backtest
def backtest(cells: pd.DataFrame, panel, clim, boundaries) -> dict:
    """2019 / 2023 fire seasons: for each day, cluster events and score them with the rules (no
    stability, no weather: haze = no). First day each province had a High or Critical alert vs its peak
    day (most hotspots). Trained years are in-sample for the model, so this checks the rules' timing."""
    mc = forecast.mcfg()
    fcst = forecast.load()
    tw = towns()
    daily = daily_counts(cells)
    out = []
    for year in mc["backtest_years"]:
        months = mc["backtest_months"]
        d0, d1 = date(year, months[0], 1), (pd.Timestamp(year, months[-1], 1) + pd.offsets.MonthEnd(0)).date()
        rws = features.rows(panel, clim, day_from=d0, day_to=d1)
        p72 = fcst.predict(rws, 3) if (fcst is not None and fcst.mode == "model") else None
        rws = rws.assign(p72=p72 if p72 is not None else 0.0)
        by_day = {d: g for d, g in rws.groupby("d")}
        first = {}
        alert_days = {}
        for d in pd.date_range(d0, d1):
            day = d.date()
            through = pd.Timestamp(day) + pd.Timedelta(hours=24) - MYT - pd.Timedelta(seconds=1)
            c = cells[(cells["t"] <= through) & (cells["t"] > through - pd.Timedelta(hours=48))]
            evs, _ = events.build(c, through)
            if not evs:
                continue
            an = anomalies(daily, day, exclude_year=year)
            g = by_day.get(panel.day_index(day))
            for ev in evs:
                if p72 is not None and g is not None:
                    idx = np.unique(panel.lookup(np.array(ev["cells"])[:, 0], np.array(ev["cells"])[:, 1]))
                    sub = g[g["i"].isin(idx)]
                    p = float(sub["p72"].max()) if len(sub) else 0.0
                else:
                    p = rules.fallback_chance(event_anomaly(an, ev["province"], ev["district"])[1])
                e, _ = inputs_for(ev, {"p72": p}, an, None, None, tw)
                _, lv, _ = rules.level_for(e)
                key = ev["province"]
                if lv >= 3:
                    alert_days.setdefault(key, set()).add(day)
                    first.setdefault((key, 3), day)
                if lv >= 4:
                    first.setdefault((key, 4), day)
        season = daily[(daily["year"] == year) & daily["month"].isin(months)]
        peaks = season.groupby(["province", "day"])["weight"].sum().reset_index()
        for prov, g in peaks.groupby("province"):
            if g["weight"].sum() < 50:
                continue
            pk = pd.Timestamp(g.loc[g["weight"].idxmax(), "day"]).date()
            fh, fcr = first.get((prov, 3)), first.get((prov, 4))
            out.append({"year": year, "province": prov, "peak_day": str(pk),
                        "first_high": None if fh is None else str(fh),
                        "first_critical": None if fcr is None else str(fcr),
                        "days_early": None if fh is None else (pk - fh).days,
                        "high_or_critical_days": len(alert_days.get(prov, ()))})
    return {"note": "Rules replayed day by day over Jun-Oct; no weather (haze = no), no stability. "
                    "These years are in the training period, so the chance is in-sample.",
            "rows": out}
