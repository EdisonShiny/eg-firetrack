"""Fixed, transparent rules (docs/technical.md "The logic" 4-6, logic-explained.md section 3).

The model only gives a chance of spreading. Everything below (risk score, level, overrides,
stability, rescue priority and team share, who responds, resources, actions, notification channel)
is a pure function of an event's numbers and the config files:
  config/bands.yaml (score parts, levels, overrides, stability, priority, notifications),
  config/resources.yaml, config/actions.yaml, config/jurisdictions.json.
Nothing here is hard-coded; tests/test_rules.py checks every rule, incl. the Kapuas example.
"""
from __future__ import annotations

import ast
import math
import operator
from dataclasses import dataclass, field

from . import config
from . import stats as st


def B() -> dict:
    return config.bands()


@dataclass
class EventInputs:
    """The numbers the rules need for one fire event."""
    chance_72h: float                  # 0-1
    anomaly_pct: float | None          # compared to normal, %
    frp_sum: float                     # MW, last 24 h
    growth_pct: float                  # % vs the previous 24 h
    peat: str = "none"                 # none | shallow | deep
    km_to_town: float = math.inf
    haze_to_border: bool = False
    hotspots_24h: float = 0
    prev_24h: float = 0
    road_km: float | None = None       # no road data yet -> None
    cloud_pct: float | None = None
    rain_next_mm: float | None = None
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- risk score
def exposure(km_to_town: float) -> float:
    """People exposure 0-1 = (100 - 2.5 x km to the nearest town) / 100, 0 at >= 40 km."""
    return max(0.0, 100.0 - 2.5 * float(km_to_town)) / 100.0


def score_parts(e: EventInputs) -> dict:
    """The six parts of the risk score (unrounded points)."""
    p = B()["risk_score_parts"]
    anomaly = max(e.anomaly_pct or 0.0, 0.0)
    # half from total FRP (1,000 MW = full), half from growth (+100% = full), each half capped
    intensity = 0.5 * min(e.frp_sum / p["frp_full_at_mw"], 1.0)         + 0.5 * min(max(e.growth_pct, 0.0) / p["growth_full_at_pct"], 1.0)
    return {
        "chance": p["chance_max"] * float(e.chance_72h),
        "compared_to_normal": p["anomaly_max"] * min(anomaly / p["anomaly_full_at_pct"], 1.0),
        "intensity_growth": p["intensity_max"] * intensity,
        "fuel": float(p["peat"][e.peat]),
        "people": p["people_max"] * exposure(e.km_to_town),
        "haze": float(p["haze_border"]) if e.haze_to_border else 0.0,
    }


def risk_score(e: EventInputs) -> int:
    return st.round_half_up(sum(score_parts(e).values()))


def base_level(score: float) -> int:
    return int(st.level_for_score(score)["level"])


def level_row(level: int) -> dict:
    return next(r for r in B()["levels"] if int(r["level"]) == int(level))


def apply_overrides(level: int, e: EventInputs) -> tuple[int, list[str]]:
    """Safety overrides: town within 5 km or >= 50 hotspots in 24 h -> at least High.
    Outlier review: a > 10x jump in 24 h cannot raise the event to Critical until reviewed."""
    o = B()["overrides"]
    why = []
    t = o["min_level_if_town_km_below"]
    if e.km_to_town < t["km"] and level < t["level"]:
        level = int(t["level"])
        why.append(f"town within {t['km']} km")
    h = o["min_level_if_hotspots_24h_at_least"]
    if e.hotspots_24h >= h["count"] and level < h["level"]:
        level = int(h["level"])
        why.append(f">= {h['count']} hotspots in 24 h")
    if is_outlier(e):
        cap = int(B()["outlier_review"]["max_level_until_reviewed"])
        if level > cap:
            level = cap
            why.append("sudden jump: flagged for review before Critical")
    return level, why


def is_outlier(e: EventInputs) -> bool:
    r = float(B()["outlier_review"]["jump_ratio"])
    return e.prev_24h > 0 and e.hotspots_24h >= r * e.prev_24h


def level_for(e: EventInputs) -> tuple[int, int, list[str]]:
    """-> (score, level after overrides, override reasons)."""
    s = risk_score(e)
    lv, why = apply_overrides(base_level(s), e)
    return s, lv, why


# --------------------------------------------------------------------------- stability
def stable_level(new_level: int, prev_level: int | None, prev_days_below: int = 0) -> tuple[int, int]:
    """Up at once; down only after `downgrade_after_days_below` days in a row below.
    -> (level shown, days below so far)."""
    need = int(B()["stability"]["downgrade_after_days_below"])
    if prev_level is None or new_level >= prev_level:
        return new_level, 0
    below = prev_days_below + 1
    if below >= need:
        return new_level, 0
    return prev_level, below


def days_without(prev_days_without: int, hotspots_24h: float) -> int:
    return 0 if hotspots_24h > 0 else prev_days_without + 1


def is_closed(days_without_hotspots: int) -> bool:
    return days_without_hotspots >= int(B()["stability"]["close_after_days_without_hotspots"])


# --------------------------------------------------------------------------- rescue priority
def people_exposure_points(km_to_town: float) -> float:
    return 100.0 * exposure(km_to_town)


def priority(score: float, km_to_town: float, growth_pct: float) -> int:
    """0.5 x risk score + 0.3 x people exposure + 0.2 x growth (growth capped at 100%)."""
    rp = B()["rescue_priority"]
    w = rp["weights"]
    g = min(float(growth_pct), float(rp["growth_cap_pct"]))
    return st.round_half_up(w["risk"] * score + w["people"] * people_exposure_points(km_to_town) + w["growth"] * g)


def rank_critical(priorities: dict[str, float]) -> dict[str, dict]:
    """Critical alerts only: P1 = highest priority; share = priority / sum x 100, whole percents
    that always add up to 100 (largest remainder). Ties keep the input order."""
    if not priorities:
        return {}
    order = sorted(priorities, key=lambda k: -priorities[k])
    vals = {k: max(float(priorities[k]), 0.0) for k in order}
    total = sum(vals.values())
    if total <= 0:
        raw = {k: 100.0 / len(order) for k in order}
    else:
        raw = {k: v / total * 100.0 for k, v in vals.items()}
    share = {k: int(math.floor(raw[k])) for k in order}
    left = 100 - sum(share.values())
    for k in sorted(order, key=lambda k: -(raw[k] - share[k]))[:left]:
        share[k] += 1
    return {k: {"rank": i + 1, "priority": priorities[k], "share_pct": share[k]} for i, k in enumerate(order)}


# --------------------------------------------------------------------------- who responds
def who_responds(province: str, level: int, haze_to_border: bool) -> dict:
    j = config.load("jurisdictions.json")
    r = j[province]
    crit = int(B()["levels"][-1]["level"])
    also = []
    if level >= crit and r.get("critical_adds"):
        also.append(r["critical_adds"])
    if haze_to_border:
        also.append(j["_haze_crosses_border"]["also_inform"])
    return {"lead": r["lead"], "support": r["support"], "also_inform": also,
            "duty_officer": r.get("contact"), "country": r["country"]}


def notification(level: int) -> dict:
    return dict(B()["notifications"][level_row(level)["name"]])


# --------------------------------------------------------------------------- resources
def resources(level: int, peat: str, hotspots_24h: float, km_to_town: float,
              road_km: float | None = None) -> dict:
    """Base kit by level + modifiers (config/resources.yaml)."""
    rc = config.load("resources.yaml")
    name = level_row(level)["name"]
    base = rc["base"][name]
    mod = rc["modifiers"]
    lo, hi = base["firefighters"]
    items = []
    lances = 0
    notes = []
    if peat == "deep":
        m = float(mod["deep_peat"]["firefighters_multiplier"])
        lo, hi = st.round_half_up(lo * m), st.round_half_up(hi * m)
        lances = int(mod["deep_peat"]["peat_lances"].get(name, 0))
        notes.append(f"deep peat: firefighters x {m:g}")
    elif peat == "shallow":
        lances = int(mod["shallow_peat"]["peat_lances"])
    ec = mod["extra_crew"]
    crews = int(max(0.0, float(hotspots_24h) - ec["per_hotspots_above"]) // ec["every"])
    if crews:
        lo += crews * ec["crew_size"]
        hi += crews * ec["crew_size"]
        notes.append(f"+{crews} crew(s) of {ec['crew_size']} for {int(hotspots_24h)} hotspots")
    heli = int(base["helicopters"])
    if road_km is not None and road_km > mod["far_from_road_km"]["above"]:
        heli += int(mod["far_from_road_km"]["add_helicopters"])
        notes.append(f"> {mod['far_from_road_km']['above']} km from a road: +1 helicopter")
    if km_to_town < mod["town_within_km"]["below"]:
        items += list(mod["town_within_km"]["add"])
    items = list(base.get("extras", [])) + items
    rows = [{"name": "Firefighters", "qty": f"{lo}–{hi}"},
            {"name": "Fire engines", "qty": str(base["engines"])},
            {"name": "Portable pumps", "qty": str(base["pumps"])},
            {"name": "Helicopters (water bombing)", "qty": str(heli)}]
    if lances:
        rows.append({"name": "Peat injection lances", "qty": str(lances)})
    rows += [{"name": x, "qty": "yes"} for x in items]
    return {"level": name, "firefighters": [lo, hi], "engines": int(base["engines"]), "pumps": int(base["pumps"]),
            "helicopters": heli, "peat_lances": lances, "extras": items,
            "arrive_within_h": rc["arrive_within_h"].get(name), "rows": rows, "notes": notes}


# --------------------------------------------------------------------------- actions
_OPS = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.Gt: operator.gt, ast.GtE: operator.ge}


def eval_condition(expr: str, ctx: dict) -> bool:
    """Evaluate an actions.yaml condition safely: names, numbers, strings, comparisons, and/or/not.
    A comparison with an unknown value (None) is False."""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.BoolOp):
            vals = [ev(v) for v in n.values]
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            return not ev(n.operand)
        if isinstance(n, ast.Compare):
            left = ev(n.left)
            for op, comp in zip(n.ops, n.comparators):
                right = ev(comp)
                if left is None or right is None or not _OPS[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(n, ast.Name):
            if n.id in ("true", "True"):
                return True
            if n.id in ("false", "False"):
                return False
            if n.id not in ctx:
                raise KeyError(f"unknown name in actions.yaml condition: {n.id}")
            return ctx[n.id]
        if isinstance(n, ast.Constant):
            return n.value
        raise ValueError(f"not allowed in actions.yaml condition: {ast.dump(n)}")
    return bool(ev(ast.parse(expr, mode="eval")))


def action_context(level: int, e: EventInputs) -> dict:
    return {"level": level, "peat": e.peat, "road_km": e.road_km, "growth_pct": e.growth_pct,
            "town_km": e.km_to_town, "haze_to_border": bool(e.haze_to_border),
            "cloud_pct": e.cloud_pct, "rain_next_mm": e.rain_next_mm}


class _Blank(dict):
    def __missing__(self, key):
        return "–"


def action_words(level: int, e: EventInputs) -> dict:
    return _Blank(hotspots=st.round_half_up(e.hotspots_24h), growth=st.signed_pct(e.growth_pct),
                  town_km=f"{e.km_to_town:.0f}", road_km="–" if e.road_km is None else f"{e.road_km:.0f}",
                  level_name=level_row(level)["name"])


def actions(level: int, e: EventInputs) -> list[dict]:
    """Every actions.yaml row whose condition holds: when, action, plain reason (why) and the rule."""
    ctx = action_context(level, e)
    words = action_words(level, e)
    return [{"when": a["when"], "action": a["action"],
             "why": str(a.get("why", a["if"])).format_map(words), "rule": a["if"]}
            for a in config.load("actions.yaml") if eval_condition(str(a["if"]), ctx)]


# --------------------------------------------------------------------------- area status
def fallback_chance(status: str | None) -> float:
    """Chance (0-1) in compared-to-normal fallback mode, from the status word."""
    t = config.load("forecast.yaml")["fallback_chance_pct"]
    return float(t.get(status or "none", t["none"])) / 100.0
