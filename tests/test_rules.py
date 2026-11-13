"""Phase 6 rules: risk score, level, overrides, stability, priority/share, who/resources/actions,
notifications. Includes the worked example from docs/logic-explained.md (Kapuas, 21 Sep 2026)."""
import math

import pytest

from pipeline import config, rules
from pipeline.rules import EventInputs


def kapuas(**kw):
    base = dict(chance_72h=0.83, anomaly_pct=280, frp_sum=1000, growth_pct=48, peat="deep", km_to_town=12,
                haze_to_border=True, hotspots_24h=41, prev_24h=41 / 1.48)
    base.update(kw)
    return EventInputs(**base)


# --------------------------------------------------------------------------- Kapuas worked example
def test_kapuas_score_parts():
    p = rules.score_parts(kapuas())
    assert p["chance"] == pytest.approx(33.2)
    assert p["compared_to_normal"] == pytest.approx(18.67, abs=0.01)
    assert p["intensity_growth"] == pytest.approx(7.4)
    assert p["fuel"] == 10
    assert p["people"] == pytest.approx(10.5)
    assert p["haze"] == 5


def test_kapuas_score_85_critical():
    score, level, why = rules.level_for(kapuas())
    assert score == 85
    assert level == 4 and rules.level_row(level)["name"] == "Critical"
    assert why == []


def test_kapuas_priority_73_p1_20_percent():
    assert rules.exposure(12) == pytest.approx(0.7)
    pr = rules.priority(85, 12, 48)
    assert pr == 73
    # Kapuas is the highest of 6 Critical alerts whose priorities add up to 370
    ranks = rules.rank_critical({"kapuas": pr, "b": 70, "c": 62, "d": 60, "e": 55, "f": 50})
    assert ranks["kapuas"]["rank"] == 1
    assert ranks["kapuas"]["share_pct"] == 20                 # 73 / 370 = 19.7% -> 20%
    assert sum(r["share_pct"] for r in ranks.values()) == 100


# --------------------------------------------------------------------------- score parts
def test_score_zero_and_max():
    zero = EventInputs(chance_72h=0, anomaly_pct=None, frp_sum=0, growth_pct=-50, peat="none", km_to_town=100)
    assert rules.risk_score(zero) == 0
    top = EventInputs(chance_72h=1, anomaly_pct=900, frp_sum=5000, growth_pct=500, peat="deep", km_to_town=0,
                      haze_to_border=True)
    assert rules.risk_score(top) == 100


@pytest.mark.parametrize("pct,points", [(None, 0), (-50, 0), (0, 0), (150, 10), (300, 20), (600, 20)])
def test_anomaly_points_linear_to_300(pct, points):
    e = EventInputs(chance_72h=0, anomaly_pct=pct, frp_sum=0, growth_pct=0)
    assert rules.score_parts(e)["compared_to_normal"] == pytest.approx(points)


def test_intensity_halves_capped_separately():
    e = EventInputs(chance_72h=0, anomaly_pct=0, frp_sum=0, growth_pct=300)   # growth alone gives half
    assert rules.score_parts(e)["intensity_growth"] == pytest.approx(5)
    e = EventInputs(chance_72h=0, anomaly_pct=0, frp_sum=500, growth_pct=0)
    assert rules.score_parts(e)["intensity_growth"] == pytest.approx(2.5)


@pytest.mark.parametrize("peat,pts", [("none", 0), ("shallow", 5), ("deep", 10)])
def test_fuel_points(peat, pts):
    assert rules.score_parts(EventInputs(chance_72h=0, anomaly_pct=0, frp_sum=0, growth_pct=0, peat=peat))["fuel"] == pts


@pytest.mark.parametrize("km,exp", [(0, 1.0), (12, 0.7), (20, 0.5), (40, 0.0), (55, 0.0)])
def test_people_exposure(km, exp):
    assert rules.exposure(km) == pytest.approx(exp)


# --------------------------------------------------------------------------- level + overrides
@pytest.mark.parametrize("score,level", [(0, 1), (24, 1), (25, 2), (49, 2), (50, 3), (74, 3), (75, 4), (100, 4)])
def test_level_bands(score, level):
    assert rules.base_level(score) == level


def low_event(**kw):
    base = dict(chance_72h=0.1, anomaly_pct=0, frp_sum=10, growth_pct=0, peat="none", km_to_town=80,
                hotspots_24h=5, prev_24h=5)
    base.update(kw)
    return EventInputs(**base)


def test_override_town_within_5_km():
    s, lv, why = rules.level_for(low_event(km_to_town=4.9))
    assert s < 25 and lv == 3 and "town" in why[0]
    assert rules.level_for(low_event(km_to_town=5.0))[1] < 3


def test_override_50_hotspots():
    s, lv, why = rules.level_for(low_event(hotspots_24h=50, prev_24h=40))
    assert lv == 3 and "50" in why[0]
    assert rules.level_for(low_event(hotspots_24h=49, prev_24h=40))[1] < 3


def test_override_never_lowers():
    lv, why = rules.apply_overrides(4, low_event(km_to_town=1))
    assert lv == 4 and why == []


def test_outlier_jump_blocks_critical():
    e = kapuas(hotspots_24h=41, prev_24h=4)                 # > 10x in 24 h
    assert rules.is_outlier(e)
    s, lv, why = rules.level_for(e)
    assert s >= 75 and lv == 3 and "review" in why[-1]
    assert not rules.is_outlier(kapuas(prev_24h=0))         # a new event is not an outlier jump


# --------------------------------------------------------------------------- stability
def test_stability_up_at_once():
    assert rules.stable_level(4, 2, 0) == (4, 0)


def test_stability_down_after_two_days_below():
    lv, below = rules.stable_level(2, 3, 0)
    assert (lv, below) == (3, 1)                            # day 1 below: hold
    assert rules.stable_level(2, lv, below) == (2, 0)       # day 2 below: go down


def test_stability_counter_resets_when_back_up():
    lv, below = rules.stable_level(2, 3, 0)
    assert rules.stable_level(3, lv, below) == (3, 0)


def test_stability_new_event():
    assert rules.stable_level(2, None) == (2, 0)


def test_close_after_three_days_without_hotspots():
    d = 0
    for _ in range(2):
        d = rules.days_without(d, 0)
        assert not rules.is_closed(d)
    d = rules.days_without(d, 0)
    assert d == 3 and rules.is_closed(d)
    assert rules.days_without(2, 1) == 0


# --------------------------------------------------------------------------- priority / share
def test_priority_growth_capped_at_100():
    assert rules.priority(80, 50, 300) == rules.priority(80, 50, 100) == 60


def test_rank_shares_add_to_100_and_order():
    r = rules.rank_critical({"a": 10, "b": 30, "c": 20})
    assert [k for k, _ in sorted(r.items(), key=lambda kv: kv[1]["rank"])] == ["b", "c", "a"]
    assert sum(v["share_pct"] for v in r.values()) == 100
    assert r["b"]["share_pct"] == 50


def test_rank_single_and_empty():
    assert rules.rank_critical({"x": 50})["x"] == {"rank": 1, "priority": 50, "share_pct": 100}
    assert rules.rank_critical({}) == {}


# --------------------------------------------------------------------------- who responds
@pytest.mark.parametrize("province", ["Sarawak", "Sabah", "Brunei", "West Kalimantan", "Central Kalimantan",
                                      "South Kalimantan", "East Kalimantan", "North Kalimantan"])
def test_who_responds_table(province):
    j = config.load("jurisdictions.json")[province]
    w = rules.who_responds(province, 3, False)
    assert w["lead"] == j["lead"] and w["support"] == j["support"] and w["also_inform"] == []
    c = rules.who_responds(province, 4, False)
    assert c["also_inform"] == ([j["critical_adds"]] if j["critical_adds"] else [])


def test_who_responds_examples_and_haze():
    assert rules.who_responds("Sarawak", 4, False)["also_inform"] == ["NADMA"]
    assert rules.who_responds("Brunei", 4, False)["also_inform"] == []
    k = rules.who_responds("Central Kalimantan", 4, True)
    assert k["lead"] == "BPBD Central Kalimantan" and k["support"] == "Manggala Agni"
    assert k["also_inform"] == ["BNPB", "ASMC and the neighbouring country"]
    assert rules.who_responds("Sabah", 2, True)["also_inform"] == ["ASMC and the neighbouring country"]


@pytest.mark.parametrize("level,channel", [(1, "dashboard only"), (2, "dashboard + email to the local agency"),
                                           (3, "SMS + email to lead and support"),
                                           (4, "SMS + call + email + national agency")])
def test_notification_channel(level, channel):
    assert rules.notification(level)["channel"] == channel


# --------------------------------------------------------------------------- resources
@pytest.mark.parametrize("level,ff,eng,pumps,heli", [(1, [5, 10], 1, 0, 0), (2, [20, 50], 3, 4, 0),
                                                     (3, [50, 150], 5, 10, 1), (4, [150, 250], 6, 20, 2)])
def test_resources_base(level, ff, eng, pumps, heli):
    r = rules.resources(level, "none", 5, 80)
    assert r["firefighters"] == ff and r["engines"] == eng and r["pumps"] == pumps and r["helicopters"] == heli
    assert r["peat_lances"] == 0


def test_resources_arrive_within():
    assert [rules.resources(lv, "none", 5, 80)["arrive_within_h"] for lv in (1, 2, 3, 4)] == [None, 24, 6, 2]


def test_resources_extras():
    assert "verification team" in rules.resources(2, "none", 5, 80)["extras"]
    assert any("cloud seeding" in x for x in rules.resources(4, "none", 5, 80)["extras"])


@pytest.mark.parametrize("level,lances", [(4, 10), (3, 6), (2, 3)])
def test_resources_deep_peat(level, lances):
    base = rules.resources(level, "none", 5, 80)["firefighters"]
    r = rules.resources(level, "deep", 5, 80)
    assert r["firefighters"] == [round(base[0] * 1.5), round(base[1] * 1.5)]
    assert r["peat_lances"] == lances


def test_resources_far_from_road_adds_helicopter():
    assert rules.resources(3, "none", 5, 80, road_km=11)["helicopters"] == 2
    assert rules.resources(3, "none", 5, 80, road_km=10)["helicopters"] == 1
    assert rules.resources(3, "none", 5, 80, road_km=None)["helicopters"] == 1   # unknown road: no change


def test_resources_town_within_15_km():
    assert "field medical post" in rules.resources(3, "none", 5, 14.9)["extras"]
    assert "field medical post" not in rules.resources(3, "none", 5, 15)["extras"]


@pytest.mark.parametrize("hotspots,extra", [(20, 0), (29, 0), (30, 10), (41, 20), (60, 40)])
def test_resources_extra_crew_every_10_above_20(hotspots, extra):
    assert rules.resources(3, "none", hotspots, 80)["firefighters"] == [50 + extra, 150 + extra]


def test_resources_kapuas():
    r = rules.resources(4, "deep", 41, 12)
    assert r["firefighters"] == [245, 395]                  # (150-250) x 1.5 + 2 crews of 10
    assert r["peat_lances"] == 10 and r["helicopters"] == 2 and r["arrive_within_h"] == 2
    assert "N95 masks for residents" in r["extras"]


# --------------------------------------------------------------------------- actions
def acts(level, **kw):
    e = low_event(**kw)
    return [a["action"] for a in rules.actions(level, e)]


A = {a["action"]: a for a in config.load("actions.yaml")}
DISPATCH = "Dispatch ground crews to the fire edge"
PEAT_INJ = "Start peat injection on smouldering ground"
AERIAL = "Request aerial water bombing"
VERIFY = "Send a verification team to the site"
FIREBREAK = "Cut firebreaks on the downwind side"
HEALTH = "Issue a health advisory and hand out masks"
CANALS = "Block drainage canals to rewet the peat"
SEEDING = "Assess cloud seeding with the weather agency (cloud cover >= 40%, little rain forecast)"
ASMC = "Inform ASMC and the neighbouring country"
RECHECK = "Re-check with the next satellite pass"


def test_all_actions_known():
    assert set(A) == {DISPATCH, PEAT_INJ, AERIAL, VERIFY, FIREBREAK, HEALTH, CANALS, SEEDING, ASMC, RECHECK}


def test_action_low_only_recheck():
    assert acts(1) == [RECHECK]


def test_action_dispatch_and_firebreaks_high_critical():
    for lv in (3, 4):
        assert DISPATCH in acts(lv) and FIREBREAK in acts(lv)
    assert DISPATCH not in acts(2) and FIREBREAK not in acts(2)


def test_action_peat_injection():
    assert PEAT_INJ in acts(3, peat="shallow") and PEAT_INJ in acts(4, peat="deep")
    assert PEAT_INJ not in acts(3, peat="none") and PEAT_INJ not in acts(2, peat="deep")


def test_action_aerial():
    assert AERIAL in acts(3, road_km=11) and AERIAL in acts(4, growth_pct=41)
    assert AERIAL not in acts(3, road_km=10, growth_pct=40)
    assert AERIAL not in acts(3, road_km=None, growth_pct=0)        # unknown road is not "far"
    assert AERIAL not in acts(2, growth_pct=90)


def test_action_verification_moderate_only():
    assert VERIFY in acts(2) and VERIFY not in acts(3) and VERIFY not in acts(1)


def test_action_health_advisory():
    assert HEALTH in acts(2, km_to_town=14) and HEALTH not in acts(2, km_to_town=15)
    assert HEALTH not in acts(1, km_to_town=3)


def test_action_canals_deep_peat():
    assert CANALS in acts(2, peat="deep") and CANALS not in acts(2, peat="shallow")


def test_action_cloud_seeding_critical():
    assert SEEDING in acts(4) and SEEDING not in acts(3)


def test_action_haze_inform_asmc():
    assert ASMC in acts(1, haze_to_border=True) and ASMC not in acts(4)


def test_action_kapuas():
    got = [a["action"] for a in rules.actions(4, kapuas())]
    assert got == [DISPATCH, PEAT_INJ, AERIAL, FIREBREAK, HEALTH, CANALS, SEEDING, ASMC, RECHECK]
    assert [a["when"] for a in rules.actions(4, kapuas())][:3] == ["0-2 h"] * 3


def test_action_reasons_are_plain_words():
    a = {x["action"]: x for x in rules.actions(4, kapuas())}
    assert a[DISPATCH]["why"] == "41 active hotspots, +48% in 24 h"
    assert a[HEALTH]["why"] == "town only 12 km away"
    assert a[DISPATCH]["rule"] == "level >= 3"
    assert all("{" not in x["why"] for x in a.values())


def test_condition_evaluator_is_safe():
    assert rules.eval_condition("level >= 3 and (x > 1 or y == 'a')", {"level": 3, "x": 0, "y": "a"})
    assert not rules.eval_condition("road_km > 10", {"road_km": None})
    with pytest.raises(ValueError):
        rules.eval_condition("__import__('os')", {})
    with pytest.raises(KeyError):
        rules.eval_condition("nope > 1", {})


# --------------------------------------------------------------------------- fallback chance
@pytest.mark.parametrize("status,p", [("Normal", 0.2), ("Above average", 0.5), ("Unusual", 0.8), (None, 0.2)])
def test_fallback_chance_from_compared_to_normal(status, p):
    assert rules.fallback_chance(status) == pytest.approx(p)
