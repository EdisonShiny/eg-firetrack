"""Phase 3: every band in config/bands.yaml and the statistics rules (docs/technical.md
"Predefined display values", docs/logic-explained.md sections 3 and 5)."""
import pandas as pd
import pytest

from pipeline import config
from pipeline import stats as st

B = config.bands()


# --------------------------------------------------------------------------- band lookup
@pytest.mark.parametrize("x,expected", [(24.4, 24), (24.5, 25), (-10.5, -10), (-10.6, -11), (0, 0)])
def test_round_half_up(x, expected):
    assert st.round_half_up(x) == expected


def test_band_none_and_nan():
    assert st.band(None, B["chance_words"]) is None
    assert st.band(float("nan"), B["chance_words"]) is None


# --------------------------------------------------------------------------- chance words (0-24/25-49/50-74/75-100)
@pytest.mark.parametrize("pct,word", [
    (0, "Unlikely"), (24, "Unlikely"), (25, "Possible"), (49, "Possible"),
    (50, "Likely"), (74, "Likely"), (75, "Very likely"), (100, "Very likely"),
    (24.4, "Unlikely"), (24.5, "Possible")])
def test_chance_words(pct, word):
    assert st.chance_word(pct) == word


# --------------------------------------------------------------------------- compared to normal (+25% / +100%)
@pytest.mark.parametrize("pct,status", [
    (-100, "Normal"), (0, "Normal"), (24, "Normal"), (24.9, "Above average"),
    (25, "Above average"), (99, "Above average"), (100, "Above average"),
    (100.4, "Above average"), (101, "Unusual"), (280, "Unusual")])
def test_compared_to_normal(pct, status):
    assert st.anomaly_status(pct) == status


def test_anomaly_worked_example():
    """A usual September of 1,170, September 2026 has 2,340 -> +100% -> Above average (edge of Unusual)."""
    pct = st.anomaly_pct(2340, 1170)
    assert pct == pytest.approx(100.0)
    assert st.anomaly_status(pct) == "Above average"


def test_anomaly_usual_zero_is_none():
    assert st.anomaly_pct(5, 0) is None
    assert st.anomaly_status(None) is None


# --------------------------------------------------------------------------- risk score -> level (24/25, 49/50, 74/75)
@pytest.mark.parametrize("score,level,name", [
    (0, 1, "Low"), (24, 1, "Low"), (25, 2, "Moderate"), (49, 2, "Moderate"),
    (50, 3, "High"), (74, 3, "High"), (75, 4, "Critical"), (85, 4, "Critical"), (100, 4, "Critical")])
def test_levels(score, level, name):
    row = st.level_for_score(score)
    assert (row["level"], row["name"]) == (level, name)


def test_level_rows_carry_directive_deploy_and_colour():
    assert st.level_for_score(80)["deploy_within_h"] == 2
    assert st.level_for_score(60)["deploy_within_h"] == 6
    assert st.level_for_score(30)["deploy_within_h"] == 24
    assert st.level_for_score(10)["deploy_within_h"] is None
    assert st.level_for_score(80)["colour"] == "#DC2626"
    assert st.level_for_score(10)["directive"].startswith("Monitor daily")


# --------------------------------------------------------------------------- trend direction (-10% / +10%)
@pytest.mark.parametrize("pct,word", [
    (-50, "Falling"), (-11, "Falling"), (-10.6, "Falling"), (-10, "Stable"), (0, "Stable"),
    (10, "Stable"), (10.4, "Stable"), (11, "Rising"), (35, "Rising")])
def test_trend_direction(pct, word):
    assert st.trend_word(pct) == word


def test_week_on_week_mean_of_three_changes():
    r = st.week_on_week([100, 120, 150, 200])          # +20, +25, +33.3 -> mean 26.1
    assert r["changes_pct"] == [20.0, 25.0, 33.3]
    assert r["pct"] == pytest.approx(26.1, abs=0.05)
    assert r["word"] == "Rising" and r["rising_weeks"] == 3


def test_week_on_week_zero_weeks():
    assert st.week_on_week([0, 0, 0, 0]) == {"weekly": [0, 0, 0, 0], "changes_pct": [None, None, None],
                                             "pct": 0.0, "word": "Stable", "rising_weeks": 0}
    r = st.week_on_week([0, 0, 0, 5])                  # no week to compare with -> unknown
    assert r["pct"] is None and r["word"] is None


# --------------------------------------------------------------------------- unusual month (2x usual)
@pytest.mark.parametrize("count,usual,flag", [
    (200, 100, True), (199.9, 100, False), (199, 100, False), (350, 100, True),
    (5, 0, False), (0, 0, False)])
def test_unusual_month(count, usual, flag):
    assert st.is_unusual(count, usual) is flag


def test_unusual_ratio_comes_from_config():
    assert B["unusual_month_ratio"] == 2.0


def test_ratio_to_usual():
    assert st.ratio_to_usual(1612, 500) == 3.22
    assert st.ratio_to_usual(3, 0) is None


# --------------------------------------------------------------------------- medians use full years only
def grid_from(rows):
    return st.month_grid(pd.DataFrame(rows, columns=["year", "month", "count"]))


def test_month_grid_fills_missing_with_zero():
    g = grid_from([(2019, 9, 100)])
    assert list(g.index) == list(range(2017, 2027))
    assert g.loc[2019, 9] == 100 and g.loc[2018, 9] == 0


def test_usual_is_median_of_2017_2025_and_ignores_2026():
    rows = [(y, 9, v) for y, v in zip(range(2017, 2026), [10, 20, 30, 40, 50, 60, 70, 80, 90])]
    rows.append((2026, 9, 100000))
    usual = st.usual_months(grid_from(rows))
    assert usual[9] == 50                              # 5th of 9 sorted values
    assert st.median_years() == list(range(2017, 2026))


def test_usual_counts_empty_years_as_zero():
    rows = [(2019, 9, 900), (2023, 9, 800), (2017, 9, 10)]   # 6 of 9 years have no fires -> median 0
    assert st.usual_months(grid_from(rows))[9] == 0


def test_yearly_average_full_years_only():
    rows = [(y, 1, 100) for y in range(2017, 2026)] + [(2026, 1, 5000)]
    assert st.yearly_average(grid_from(rows)) == 100


# --------------------------------------------------------------------------- fire season (1.25x) and strength
def usual_series(values):
    return pd.Series(values, index=st.MONTHS, dtype=float)


def test_fire_season_edge_at_1_25():
    # mean of the 12 medians = 100; 125 is exactly 1.25x -> in, 124 -> out
    vals = [100.0] * 12
    vals[7], vals[8], vals[9] = 125.0, 150.0, 124.0          # Aug, Sep, Oct
    vals[0] = 100.0 - (125 + 150 + 124 - 300)                 # keep the mean at 100
    u = usual_series(vals)
    assert u.mean() == pytest.approx(100)
    fs = st.fire_season(u)
    assert fs["months"] == [8, 9]
    assert fs["label"] == "Aug – Sep"
    assert fs["ratio"] == B["fire_season_ratio"] == 1.25


def test_fire_season_wraps_over_new_year_and_share():
    u = usual_series([300, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 300])   # Dec + Jan
    rows = [(y, m, u[m]) for y in range(2017, 2026) for m in st.MONTHS]
    fs = st.fire_season(u, grid_from(rows))
    assert fs["months"] == [1, 12] and fs["label"] == "Dec – Jan"
    assert fs["share_pct"] == pytest.approx(600 / 700 * 100, abs=0.1)


def test_fire_season_no_fires():
    assert st.fire_season(usual_series([0] * 12))["months"] == []


def test_season_strength():
    u = usual_series([46, 50, 60, 70, 80, 90, 200, 400, 522, 300, 100, 60])
    assert st.season_strength(u) == pytest.approx(11.3)
    assert st.season_strength(usual_series([0] + [5] * 11)) is None


# --------------------------------------------------------------------------- calendar colours: 7 quantile bins
def test_quantile_edges_and_bins():
    assert len(B["calendar_ramp"]) == 7
    edges = st.quantile_edges(range(0, 71))
    assert len(edges) == 8 and edges[0] == 0 and edges[-1] == 70
    assert st.bin_index(0, edges) == 0
    assert st.bin_index(70, edges) == 6
    assert st.bin_index(edges[1], edges) == 0          # inner edges are upper-inclusive
    assert st.bin_index(edges[1] + 0.01, edges) == 1
    assert sorted({st.bin_index(v, edges) for v in range(71)}) == list(range(7))


# --------------------------------------------------------------------------- prediction range (15/25/35%)
def test_prediction_band():
    p = st.prediction_band([100, 100, 100])
    assert [(x["low"], x["high"]) for x in p] == [(85, 115), (75, 125), (65, 135)]
    assert [x["range_pct"] for x in p] == B["prediction_range_pct"] == [15, 25, 35]


# --------------------------------------------------------------------------- sudden increase (2x and >= 10)
@pytest.mark.parametrize("last7,prev7,flag", [
    (10, 5, True), (9, 2, False), (20, 10, True), (19, 10, False), (10, 0, True), (0, 0, False)])
def test_sudden_increase(last7, prev7, flag):
    assert st.sudden_increase(last7, prev7) is flag


# --------------------------------------------------------------------------- FRP dot size, very intense
@pytest.mark.parametrize("frp,size", [(9.9, "small"), (10, "medium"), (50, "medium"), (50.1, "large")])
def test_frp_dot_size(frp, size):
    assert st.frp_size(frp) == size


def test_very_intense_frp():
    assert st.is_very_intense(100) and not st.is_very_intense(99.9)


# --------------------------------------------------------------------------- texts and no hard-coded words
def test_signed_pct():
    assert st.signed_pct(27.6) == "+28%" and st.signed_pct(-3) == "-3%" and st.signed_pct(None) == "–"


def test_texts_present_in_bands_yaml():
    t = B["texts"]
    for key in ("peak_in_view", "last_12_months", "month_vs_normal", "year_so_far", "next_months", "data_note"):
        assert {"title", "text"} <= set(t[key])
    assert set(t["tags"]) == {"past", "now", "next", "data"}


# --------------------------------------------------------------------------- compared to normal: floor, cap, windows
def test_floor_stops_near_zero_median_exploding():
    floor = B["compared_to_normal_rule"]["floor_cells"]
    assert floor == 10
    r = st.compare_to_normal(58, [0, 1, 1, 0, 2, 1, 0, 1, 1])        # median 1 -> +5700% without the floor
    assert r["median"] == 1 and r["baseline"] == floor and r["floored"]
    assert r["pct"] == pytest.approx(480) and r["ratio"] == pytest.approx(5.8)
    assert r["label"] == "5.8×" and r["status"] == "Unusual"
    r = st.compare_to_normal(30, [40] * 9)                             # median above the floor: unchanged
    assert not r["floored"] and r["pct"] == pytest.approx(-25)
    assert st.compare_to_normal(0, [])["baseline"] == floor              # no history -> floor, never None


def test_floor_is_configurable():
    assert st.compare_to_normal(10, [1, 1, 1], floor=2)["pct"] == pytest.approx(400)


@pytest.mark.parametrize("pct,label", [
    (None, "–"), (-35, "−35%"), (0, "0%"), (18, "+18%"), (45, "+45%"), (100, "+100%"), (100.4, "+100%"),
    (100.6, "2.0×"), (120, "2.2×"), (220, "3.2×"), (900, "10.0×"), (904, "10.0×"),
    (906, ">10×"), (5700, ">10×")])
def test_vs_normal_label_pct_then_ratio_then_cap(pct, label):
    assert st.vs_normal_label(pct) == label


@pytest.mark.parametrize("pct", [None, -100, -35, 0, 18, 99.6, 100.6, 220, 904, 906, 5700, 1e9])
def test_vs_normal_label_is_short_enough_for_a_tile(pct):
    """The big tile value never grows past 5 characters ("+100%", "10.0×", ">10×"), so it cannot overflow."""
    assert len(st.vs_normal_label(pct)) <= 5


def test_bands_unchanged_by_display():
    r = st.compare_to_normal(5000, [100] * 9)
    assert r["label"] == ">10×" and r["status"] == "Unusual"
    assert st.compare_to_normal(150, [100] * 9)["status"] == "Above average"


def _counter(rows):
    return st.WindowCounter([pd.Timestamp(t) for t, _ in rows], [w for _, w in rows])


def test_window_matching_same_calendar_window_each_year():
    end = pd.Timestamp("2026-11-09 20:40")
    rows = [("2026-11-09 10:00", 30), ("2026-11-03 10:00", 7), ("2026-10-20 10:00", 100),
            ("2026-01-15 00:00", 1000)]
    for y in range(2017, 2026):
        rows += [(f"{y}-11-09 10:00", 2),          # inside every window
                 (f"{y}-11-09 21:00", 50),         # after the same hour: only in current +-3 days
                 (f"{y}-11-05 10:00", 5),          # 7d / 30d / month / year (before day -3's window)
                 (f"{y}-10-20 10:00", 40),         # 30d / year, not month
                 (f"{y}-03-01 10:00", 400)]        # year only
    c = _counter(rows)
    cur, past, info = st.same_window(c, "7d", end)
    assert cur == 37 and past == [7.0] * 9 and info["years"] == [2017, 2025]
    cur, past, _ = st.same_window(c, "30d", end)
    assert cur == 137 and past == [47.0] * 9
    cur, past, _ = st.same_window(c, "month", end)
    assert cur == 37 and past == [7.0] * 9
    cur, past, _ = st.same_window(c, "year", end)
    assert cur == 1137 and past == [447.0] * 9
    cur, past, _ = st.same_window(c, "current", end)          # 24 h vs mean of day +-3 (7 days)
    assert cur == 30 and past == [pytest.approx((2 + 50) / 7)] * 9


def test_window_skips_years_before_the_data():
    end = pd.Timestamp("2026-01-05 12:00")
    c = _counter([("2017-01-02 00:00", 1), ("2018-01-02 00:00", 1)])
    _, past, info = st.same_window(c, "30d", end)              # 2017 window starts in Dec 2016
    assert len(past) == 8 and info["years"] == [2018, 2025]
    _, past, info = st.same_window(c, "year", end)             # Jan 1 2017 is inside the data
    assert len(past) == 9 and past[:2] == [1.0, 1.0] and info["years"] == [2017, 2025]
