"""Phase 6 forecast: features (no look-ahead), metrics, baselines, the 'beats both baselines' rule,
calibration, SHAP scaling, and the committed model files."""
import json

import numpy as np
import pandas as pd
import pytest

from pipeline import features, forecast, paths


@pytest.fixture
def tiny_cells():
    """One 0.1 deg cell with fire on 2024-01-03 and 2024-01-05, a neighbour cell on 2024-01-04."""
    rows = [("2024-01-03", -2.55, 113.55, 1.0), ("2024-01-05", -2.55, 113.55, 2.0),
            ("2024-01-04", -2.45, 113.55, 1.0)]
    return pd.DataFrame([{"day": d, "lat": la, "lon": lo, "weight": w, "year": 2024, "month": 1}
                         for d, la, lo, w in rows])


def test_panel_counts_and_block(tiny_cells, squares):
    p = features.build_panel(tiny_cells, "2024-01-01", "2024-01-10", squares)
    i = p.lookup([-2.55], [113.55])[0]
    assert i >= 0
    assert p.C[i].tolist()[:6] == [0, 0, 1, 0, 2, 0]
    assert p.N[i, 3] == 1                                   # the neighbour's fire counts in the block
    assert len(p.keys) == 30                                # 2 fire cells, 5 x 5 blocks overlap in 30 cells
    assert p.district[i] == "Kapuas"


def test_rows_use_only_the_past_and_targets_the_future(tiny_cells, squares):
    p = features.build_panel(tiny_cells, "2024-01-01", "2024-01-10", squares)
    clim = features.climatology(tiny_cells, p, [2024])
    r = features.rows(p, clim)
    i = p.lookup([-2.55], [113.55])[0]
    row = r[(r["i"] == i) & (r["d"] == 3)].iloc[0]         # 2024-01-04
    assert row["cell_1d"] == 0 and row["cell_3d"] == 1 and row["near_1d"] == 1
    assert row["days_since_fire"] == 1
    assert row["y1"] == 1 and row["y3"] == 1                # fire on 01-05
    last = r[(r["i"] == i) & (r["d"] == 9)].iloc[0]         # last panel day: future unknown
    assert np.isnan(last["y1"])
    first = r[(r["i"] == i) & (r["d"] == 1)]
    assert first.empty                                      # nothing in the block yet -> not scored
    assert set(features.FEATURES) <= set(r.columns)
    assert row["peat"] == features.PEAT_CODE["deep"]        # Kapuas is in the deep-peat list


def test_climatology_leave_one_year_out(squares):
    c = pd.DataFrame([{"day": f"{y}-01-10", "lat": -2.55, "lon": 113.55, "weight": w, "year": y, "month": 1}
                      for y, w in ((2022, 31.0), (2023, 62.0))])
    p = features.build_panel(c, "2022-01-01", "2023-12-31", squares)
    clim = features.climatology(c, p, [2022, 2023])
    i = np.array([p.lookup([-2.55], [113.55])[0]])
    allyrs = features.usual_rate(clim, i, np.array([2025]), np.array([1]), loyo=True)
    assert allyrs[0] == pytest.approx(93 / 62)
    loyo = features.usual_rate(clim, i, np.array([2023]), np.array([1]), loyo=True)
    assert loyo[0] == pytest.approx(31 / 31)               # 2023's own fires are left out


def test_peat_of():
    assert features.peat_of("Kapuas") == "deep"
    assert features.peat_of("Barito Kuala") == "shallow"
    assert features.peat_of("Kudat") == "none"


def test_metrics_definitions():
    y = [1, 1, 0, 0, 0]
    p = [0.9, 0.2, 0.7, 0.1, 0.1]
    m = forecast.metrics(y, p, cutoff=0.5)
    assert m["hit_rate"] == 0.5                             # 1 of 2 real fires warned
    assert m["false_alarm_rate"] == 0.5                     # 1 of 2 warnings had no fire
    assert m["brier"] == pytest.approx(np.mean((np.array(p) - np.array(y)) ** 2), abs=1e-4)
    assert m["auc"] == pytest.approx(0.833, abs=0.001)


def test_beats_needs_better_auc_and_brier():
    base = {"auc": 0.80, "brier": 0.10}
    assert forecast.beats({"auc": 0.85, "brier": 0.09}, base)
    assert not forecast.beats({"auc": 0.85, "brier": 0.11}, base)
    assert not forecast.beats({"auc": 0.79, "brier": 0.05}, base)
    assert not forecast.beats({"auc": None, "brier": 0.05}, base)


def test_persistence_baseline():
    r = pd.DataFrame({"cell_1d": [0, 2, 0.5]})
    assert forecast.persistence(r).tolist() == [0, 1, 1]


def test_usual_baseline_shrinks_to_month_rate():
    keys = np.array([10, 20])
    tr = pd.DataFrame({"i": [0, 0, 0, 0, 1], "month": [9] * 5, "y3": [1, 1, 1, 1, 0]})
    ub = forecast.UsualBaseline(tr, "y3", keys, k=5)
    p = ub.predict(pd.DataFrame({"i": [0, 1], "month": [9, 9]}))
    assert p[0] > p[1] and 0 < p[1] < 0.8
    assert ub.predict(pd.DataFrame({"i": [0], "month": [3]}))[0] == pytest.approx(0.8)  # unseen month -> mean


def test_calibrate_is_monotone_interpolation():
    t = {"x": [0.0, 0.5, 1.0], "y": [0.0, 0.2, 0.9]}
    assert forecast.calibrate(np.array([0.25, 0.75]), t).tolist() == pytest.approx([0.1, 0.55])


# --------------------------------------------------------------------------- committed models
needs_models = pytest.mark.skipif(not (paths.MODELS / "model_card.json").exists(),
                                  reason="run python -m pipeline.train first")


@needs_models
def test_model_card_and_mode_rule():
    card = json.loads((paths.MODELS / "model_card.json").read_text(encoding="utf-8"))
    h = card["model1"]["3"]
    assert h["beats_baselines"] == (forecast.beats(h["model"], h["burned_yesterday"])
                                    and forecast.beats(h["model"], h["usual_for_month"]))
    assert card["mode"] == ("model" if h["beats_baselines"] else forecast.FALLBACK)
    assert card["split"]["test_year"] == 2025 and card["features"] == features.FEATURES
    for f in ("forecast24.txt", "forecast48.txt", "forecast72.txt", "monthly.txt", "monthly_frp.txt"):
        assert (paths.MODELS / f).stat().st_size < 5 * 1024 * 1024     # small enough to commit
    assert {r["year"] for r in card["backtest"]["rows"]} <= {2019, 2023}


@needs_models
def test_forecaster_scores_and_explains():
    f = forecast.load()
    X = pd.DataFrame([{"cell_1d": 4, "cell_3d": 6, "cell_7d": 9, "near_1d": 8, "near_3d": 15, "near_7d": 30,
                       "days_since_fire": 0, "burned_2y": 20, "usual_cell": 0.2, "usual_near": 1.0, "peat": 2,
                       "month": 9},
                      {"cell_1d": 0, "cell_3d": 0, "cell_7d": 0, "near_1d": 0, "near_3d": 0, "near_7d": 1,
                       "days_since_fire": 365, "burned_2y": 0, "usual_cell": 0.0, "usual_near": 0.0, "peat": 0,
                       "month": 2}])
    p = f.predict(X, 3)
    assert 0 <= p[1] < p[0] <= 1
    rs = f.reasons(X, 3)
    assert len(rs) == 2 and len(rs[0]) == 6
    assert {"feature", "label", "value", "effect_pp"} <= set(rs[0][0])
    # effects (all features) add up to chance - average cell, in percentage points
    full = f.reasons(X.iloc[[0]], 3, top=len(features.FEATURES))[0]
    p0 = f.card["model1"]["3"]["base_rate"]
    assert sum(r["effect_pp"] for r in full) == pytest.approx((p[0] - p0) * 100, abs=0.5)


def test_save_booster_writes_lf_only(tmp_path):
    class FakeBooster:
        def save_model(self, path, **kw):
            with open(path, "wb") as f:
                f.write(b"tree\r\nend of parameters\r\n\npandas_categorical:[]\r\n")

    out = tmp_path / "m.txt"
    forecast.save_booster(FakeBooster(), out)
    assert b"\r" not in out.read_bytes()
    assert out.read_bytes() == b"tree\nend of parameters\n\npandas_categorical:[]\n"


def test_committed_models_have_lf_line_endings():
    # The daily GitHub Action (Linux) loads these; a CRLF file breaks LightGBM parsing.
    for f in (paths.PROCESSED / "models").glob("*.txt"):
        assert b"\r\n" not in f.read_bytes(), f.name
