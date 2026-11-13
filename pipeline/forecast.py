"""72-hour chance of spreading and 3-month prediction (docs/technical.md "The logic" 2-3).

Model 1: LightGBM per horizon (24 / 48 / 72 h) on the cell-day table from features.py,
  scale_pos_weight for imbalance, isotonic calibration, time split (train / calibrate / test years
  in config/forecast.yaml). Must beat "burned yesterday -> burns tomorrow" and "usual for this month"
  on AUC and Brier score in the test year, or the System runs in compared-to-normal fallback mode.
Model 2: one pooled LightGBM regression for every area (inputs: last 3 months, the usual count of the
  target month, this month vs normal, horizon, month); used only if it beats "usual for this month"
  on the test year, else the usual value is shown and labelled.
Training runs locally (pipeline/train.py) and writes data/processed/models/; the daily run only scores.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, features, paths
from . import stats as st

MODELS = paths.PROCESSED / "models"
CARD = MODELS / "model_card.json"
FALLBACK = "compared-to-normal fallback"


def save_booster(booster, path: Path, **kw) -> None:
    """Save a LightGBM model with LF line endings only, so the committed file is identical on
    Windows and on the Linux GitHub Action (LightGBM on Windows writes some CRLF lines)."""
    booster.save_model(str(path), **kw)
    data = path.read_bytes()
    if b"\r\n" in data:
        path.write_bytes(data.replace(b"\r\n", b"\n"))


def mcfg() -> dict:
    return config.load("forecast.yaml")["model"]


# --------------------------------------------------------------------------- metrics
def metrics(y, p, cutoff: float | None = None) -> dict:
    from sklearn.metrics import roc_auc_score

    cutoff = mcfg()["cutoff"] if cutoff is None else cutoff
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    warn = p >= cutoff
    tp = int(np.sum(warn & (y == 1)))
    fp = int(np.sum(warn & (y == 0)))
    fn = int(np.sum(~warn & (y == 1)))
    auc = float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else None
    return {"auc": None if auc is None else round(auc, 3),
            "hit_rate": None if tp + fn == 0 else round(tp / (tp + fn), 3),       # share of real fires warned about
            "false_alarm_rate": None if tp + fp == 0 else round(fp / (tp + fp), 3),  # share of warnings with no fire
            "brier": round(float(np.mean((p - y) ** 2)), 4) if len(y) else None,
            "n": int(len(y)), "positives": int(y.sum())}


def beats(model: dict, base: dict) -> bool:
    """Better AUC and lower (better) Brier score than the baseline."""
    if model["auc"] is None or base["auc"] is None:
        return False
    return model["auc"] > base["auc"] and model["brier"] < base["brier"]


def persistence(rows: pd.DataFrame) -> np.ndarray:
    """Baseline 1: burned yesterday (cell had fire on the day) -> burns in the next days."""
    return (rows["cell_1d"].to_numpy() > 0).astype(float)


class UsualBaseline:
    """Baseline 2: usual for this month = the share of scored cell-days with fire in the next h days,
    per cell and month in the training years (shrunk to the month average when there are few)."""

    def __init__(self, train: pd.DataFrame, ycol: str, keys: np.ndarray, k: float = 5.0):
        t = train.assign(key=keys[train["i"].to_numpy()])
        self.month_rate = t.groupby("month")[ycol].mean()
        g = t.groupby(["key", "month"])[ycol].agg(["sum", "count"]).reset_index()
        g["rate"] = (g["sum"] + k * g["month"].map(self.month_rate)) / (g["count"] + k)
        self.table = g.set_index(["key", "month"])["rate"]
        self.keys = keys

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        idx = pd.MultiIndex.from_arrays([self.keys[rows["i"].to_numpy()], rows["month"].to_numpy()])
        v = self.table.reindex(idx).to_numpy()
        fb = rows["month"].map(self.month_rate).fillna(float(self.month_rate.mean())).to_numpy()
        return np.where(np.isnan(v), fb, v)


# --------------------------------------------------------------------------- model 1
def _fit(train: pd.DataFrame, cal: pd.DataFrame, ycol: str):
    import lightgbm as lgb
    from sklearn.isotonic import IsotonicRegression

    c = mcfg()
    pos = float(train[ycol].sum())
    params = dict(c["params"], scale_pos_weight=(len(train) - pos) / max(pos, 1.0))
    dtr = lgb.Dataset(train[features.FEATURES], train[ycol], categorical_feature=["peat"], free_raw_data=False)
    dva = lgb.Dataset(cal[features.FEATURES], cal[ycol], reference=dtr)
    booster = lgb.train(params, dtr, num_boost_round=int(c["num_boost_round"]), valid_sets=[dva],
                        callbacks=[lgb.early_stopping(30, verbose=False)])
    raw = booster.predict(cal[features.FEATURES], num_iteration=booster.best_iteration)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw, cal[ycol])
    cal_table = {"x": [float(v) for v in iso.X_thresholds_], "y": [float(v) for v in iso.y_thresholds_]}
    return booster, cal_table


def calibrate(raw: np.ndarray, table: dict) -> np.ndarray:
    return np.interp(raw, table["x"], table["y"])


def train_model1(table: pd.DataFrame, keys: np.ndarray, out_dir: Path = MODELS) -> dict:
    """Fit boosters + calibration per horizon, evaluate on the test year vs both baselines."""
    c = mcfg()
    a, b = c["train_years"]
    tr = table[(table["year"] >= a) & (table["year"] <= b)]
    ca = table[table["year"] == c["calibration_year"]]
    te = table[table["year"] == c["test_year"]]
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {}
    for h in c["horizons_days"]:
        y = f"y{h}"
        trh, cah, teh = (x[x[y].notna()] for x in (tr, ca, te))
        booster, cal_table = _fit(trh, cah, y)
        save_booster(booster, out_dir / f"forecast{24 * h}.txt", num_iteration=booster.best_iteration)
        p_cal = calibrate(booster.predict(cah[features.FEATURES], num_iteration=booster.best_iteration), cal_table)
        p_te = calibrate(booster.predict(teh[features.FEATURES], num_iteration=booster.best_iteration), cal_table)
        ub = UsualBaseline(pd.concat([trh, cah]), y, keys)
        res[h] = {
            "calibration": cal_table,
            "base_rate": round(float(np.mean(p_cal)), 4),
            "trees": int(booster.best_iteration or booster.num_trees()),
            "model": metrics(teh[y], p_te),
            "burned_yesterday": metrics(teh[y], persistence(teh)),
            "usual_for_month": metrics(teh[y], ub.predict(teh)),
            "rows": {"train": int(len(trh)), "calibration": int(len(cah)), "test": int(len(teh))},
        }
        r = res[h]
        r["beats_baselines"] = beats(r["model"], r["burned_yesterday"]) and beats(r["model"], r["usual_for_month"])
    return res


class Forecaster:
    """Loads the committed boosters; scores feature rows; explains with SHAP (LightGBM pred_contrib)."""

    def __init__(self, folder: Path = MODELS):
        import lightgbm as lgb

        self.card = json.loads((folder / "model_card.json").read_text(encoding="utf-8"))
        self.boosters, self.cal = {}, {}
        for h in mcfg()["horizons_days"]:
            f = folder / f"forecast{24 * h}.txt"
            self.boosters[h] = lgb.Booster(model_file=str(f))
            self.cal[h] = self.card["model1"][str(h)]["calibration"]
        self.mode = self.card.get("mode", FALLBACK)
        self.version = self.card.get("version")

    def predict(self, rows: pd.DataFrame, h: int = 3) -> np.ndarray:
        if rows.empty:
            return np.zeros(0)
        return calibrate(self.boosters[h].predict(rows[features.FEATURES]), self.cal[h])

    def reasons(self, rows: pd.DataFrame, h: int = 3, top: int | None = None) -> list[list[dict]]:
        """Top SHAP effects per row, in percentage points from the average cell. Log-odds SHAP values
        are scaled so they add up to (calibrated chance - average cell chance)."""
        top = top or int(mcfg()["top_reasons"])
        if rows.empty:
            return []
        X = rows[features.FEATURES]
        contrib = self.boosters[h].predict(X, pred_contrib=True)
        phi = contrib[:, :-1]
        p = calibrate(self.boosters[h].predict(X), self.cal[h])
        p0 = float(self.card["model1"][str(h)]["base_rate"])
        labels = config.load("forecast.yaml").get("feature_labels", {})
        out = []
        for r in range(len(X)):
            s = float(phi[r].sum())
            diff = float(p[r]) - p0
            scale = diff / s if abs(s) > 1e-6 and diff * s > 0 else p0 * (1 - p0)
            pp = phi[r] * scale * 100.0
            order = np.argsort(-np.abs(pp))[:top]
            out.append([{"feature": features.FEATURES[j],
                         "label": labels.get(features.FEATURES[j], features.FEATURES[j]),
                         "value": _value(features.FEATURES[j], X.iloc[r, j]),
                         "effect_pp": round(float(pp[j]), 1)} for j in order])
        return out


def _value(name: str, v) -> object:
    if name == "peat":
        return {0: "no peat", 1: "shallow peat", 2: "deep peat"}[int(v)]
    if name == "month":
        return st.MONTH_NAME[int(v) - 1]
    if name.startswith("usual"):
        return round(float(v), 2)
    return int(round(float(v)))


def load() -> Forecaster | None:
    try:
        return Forecaster()
    except (FileNotFoundError, KeyError, OSError):
        return None


# --------------------------------------------------------------------------- model 2 (3 months)
MONTHLY_FEATURES = ["log_last1", "log_last2", "log_last3", "log_usual_t", "anomaly_l", "h", "month_t"]
FRP_FEATURES = ["frp_last1", "frp_last2", "frp_last3", "frp_usual_t", "h", "month_t"]


def _shift(y: int, m: int, k: int) -> tuple[int, int]:
    i = y * 12 + (m - 1) + k
    return i // 12, i % 12 + 1


def _usual(grid: pd.DataFrame, month: int, exclude: int | None = None, how: str = "median") -> float:
    yrs = [y for y in st.median_years() if y in grid.index and y != exclude]
    v = grid.loc[yrs, month].astype(float)
    if how == "median_nonnull":
        v = v.dropna()
        return float(v.median()) if len(v) else float("nan")
    return float(v.median()) if len(v) else 0.0


def monthly_example(cnt: pd.DataFrame, frp: pd.Series, fgrid: pd.DataFrame, ly: int, lm: int, h: int,
                    loyo: bool) -> dict | None:
    """One example: origin = last full month (ly, lm); target = h months later."""
    ty, tm = _shift(ly, lm, h)
    lag = [_shift(ly, lm, -k) for k in range(3)]
    if any(y not in cnt.index for y, _ in lag):
        return None
    ex = ty if loyo else None
    u_t = _usual(cnt, tm, ex)
    u_l = _usual(cnt, lm, ex)
    c_l = [float(cnt.loc[y, m]) for y, m in lag]
    row = {"ty": ty, "tm": tm, "h": h, "month_t": tm,
           "log_last1": math.log1p(c_l[0]), "log_last2": math.log1p(c_l[1]), "log_last3": math.log1p(c_l[2]),
           "log_usual_t": math.log1p(u_t), "usual_t": u_t,
           "anomaly_l": math.log1p(c_l[0]) - math.log1p(u_l),
           "frp_last1": frp.loc[lag[0]] if lag[0] in frp.index else np.nan,
           "frp_last2": frp.loc[lag[1]] if lag[1] in frp.index else np.nan,
           "frp_last3": frp.loc[lag[2]] if lag[2] in frp.index else np.nan}
    row["frp_usual_t"] = _usual(fgrid, tm, ex, "median_nonnull") if len(frp) else np.nan
    if ty in cnt.index:
        row["count_t"] = float(cnt.loc[ty, tm])
        row["frp_t"] = frp.loc[(ty, tm)] if (ty, tm) in frp.index else np.nan
    return row


def scope_tables(cells: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """year x month counts (harmonized), (year, month) -> mean FRP, and FRP as a year x month table."""
    grid = st.month_grid(cells.rename(columns={"weight": "count"}), "count")
    frp = cells.groupby(["year", "month"])["frp"].mean() if len(cells) else pd.Series(dtype=float)
    frp.index = pd.MultiIndex.from_tuples([(int(y), int(m)) for y, m in frp.index]) if len(frp) else frp.index
    fgrid = frp.unstack().reindex(index=grid.index, columns=st.MONTHS) if len(frp) else pd.DataFrame()
    return grid, frp, fgrid


def monthly_table(cells: pd.DataFrame, last_year: int) -> pd.DataFrame:
    """Examples for Borneo, every province and every district, origins up to last_year."""
    mc = config.load("forecast.yaml")["monthly"]
    groups = [("borneo", cells)]
    groups += [(f"p:{p}", g) for p, g in cells.groupby(cells["province"].astype(str))]
    groups += [(f"d:{d}", g) for d, g in cells.groupby(cells["district"].astype(str)) if g["weight"].sum() >= 50]
    rows = []
    for name, g in groups:
        cnt, frp, fgrid = scope_tables(g)
        for y in range(st.all_years()[0], last_year + 1):
            for m in st.MONTHS:
                for h in mc["horizons_months"]:
                    ty, _ = _shift(y, m, h)
                    if ty > last_year:
                        continue
                    ex = monthly_example(cnt, frp, fgrid, y, m, h, loyo=True)
                    if ex:
                        rows.append({"scope": name, **ex})
    return pd.DataFrame(rows)


def train_model2(cells: pd.DataFrame, out_dir: Path = MODELS) -> dict:
    import lightgbm as lgb

    mc = config.load("forecast.yaml")["monthly"]
    t = monthly_table(cells, mc["test_year"])
    tr, te = t[t["ty"] <= mc["train_until_year"]], t[t["ty"] == mc["test_year"]]
    big = te["scope"].str.startswith(("borneo", "p:"))
    res = {}
    for name, feats, target, base_col, fname in (
            ("count", MONTHLY_FEATURES, "count_t", "usual_t", "monthly.txt"),
            ("frp", FRP_FEATURES, "frp_t", "frp_usual_t", "monthly_frp.txt")):
        a = tr[tr[target].notna()]
        b = te[te[target].notna() & big]
        y = np.log1p(a[target]) if name == "count" else a[target]
        booster = lgb.train(dict(mc["params"]), lgb.Dataset(a[feats], y), num_boost_round=int(mc["num_boost_round"]))
        save_booster(booster, out_dir / fname)
        pred = booster.predict(b[feats])
        if name == "count":
            pred = np.expm1(pred).clip(0)
        mae_m = float(np.mean(np.abs(pred - b[target])))
        base = b[base_col].fillna(a[target].median())
        mae_b = float(np.mean(np.abs(base - b[target])))
        res[name] = {"mae_model": round(mae_m, 2), "mae_usual": round(mae_b, 2), "use_model": mae_m < mae_b,
                     "test_rows": int(len(b)), "train_rows": int(len(a))}
    return res


class MonthlyModel:
    def __init__(self, folder: Path = MODELS):
        import lightgbm as lgb

        card = json.loads((folder / "model_card.json").read_text(encoding="utf-8"))
        self.info = card["model2"]
        self.count = lgb.Booster(model_file=str(folder / "monthly.txt"))
        self.frp = lgb.Booster(model_file=str(folder / "monthly_frp.txt"))

    def predict(self, cells: pd.DataFrame, last_full: tuple[int, int]) -> dict:
        """3 months after the current month for one area: values + which method was used."""
        mc = config.load("forecast.yaml")["monthly"]
        cnt, frp, fgrid = scope_tables(cells)
        exs = [monthly_example(cnt, frp, fgrid, *last_full, h, loyo=False) for h in mc["horizons_months"]]
        df = pd.DataFrame(exs)
        use_c, use_f = self.info["count"]["use_model"], self.info["frp"]["use_model"]
        c = np.expm1(self.count.predict(df[MONTHLY_FEATURES])).clip(0) if use_c else df["usual_t"].to_numpy()
        f = self.frp.predict(df[FRP_FEATURES]) if use_f else df["frp_usual_t"].to_numpy()
        f = np.where(np.isnan(f), 0.0, f)
        return {"count": [float(v) for v in c], "frp": [float(v) for v in f],
                "months": [(int(r.ty), int(r.tm)) for r in df.itertuples()],
                "count_method": "model" if use_c else "usual", "frp_method": "model" if use_f else "usual"}


def load_monthly() -> MonthlyModel | None:
    try:
        return MonthlyModel()
    except (FileNotFoundError, KeyError, OSError):
        return None
