"""Offline training (run locally, not in the daily Action): python -m pipeline.train

Writes data/processed/models/ (small LightGBM text boosters + model_card.json) and prints the model
check: AUC, hit rate, false alarm rate and Brier score for the model and both baselines in the test
year, the 3-month model vs "usual", and the 2019 / 2023 backtest. If the 72-hour model does not beat
both baselines, model_card.json says mode = "compared-to-normal fallback" and the daily run uses it.
Retrain once a year after the fire season, or when the 30-day hit rate drops.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime, timezone

import pandas as pd

from . import alerts, config, features, forecast, geo, ingest, paths


def load_cells() -> pd.DataFrame:
    c = pd.read_parquet(paths.HARMONIZED_CELLS)
    for col in ("day", "province", "district", "base_sensor", "country"):
        c[col] = c[col].astype(str)
    c["t"] = pd.to_datetime(c["first_time_utc"])
    return c


def climatology_years() -> list[int]:
    m = forecast.mcfg()
    return list(range(int(m["train_years"][0]), int(m["calibration_year"]) + 1))


def run() -> dict:
    cells = load_cells()
    boundaries = geo.load_boundaries()
    is_sample = bool(ingest.read_meta().get("is_sample", True))
    first, last = cells["day"].min(), cells["day"].max()
    print(f"Building the cell-day table {first} -> {last} ...")
    panel = features.build_panel(cells, first, last, boundaries)
    clim = features.climatology(cells, panel, climatology_years())
    table = features.rows(panel, clim, loyo=True)
    print(f"  {len(panel.keys):,} cells of 0.1 deg, {len(table):,} scored cell-days")

    paths.MODELS.mkdir(parents=True, exist_ok=True)
    m1 = forecast.train_model1(table, panel.keys)
    m2 = forecast.train_model2(cells)
    h72 = m1[max(m1)]
    mode = "model" if h72["beats_baselines"] else forecast.FALLBACK
    h = hashlib.sha256()
    for f in sorted(paths.MODELS.glob("*.txt")):
        h.update(f.read_bytes())
    card = {
        "version": f"{datetime.now(timezone.utc):%Y%m%d}-{h.hexdigest()[:8]}",
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_sample": is_sample,
        "mode": mode,
        "mode_reason": ("The 72-hour model beats both baselines on AUC and Brier score in the test year."
                        if mode == "model" else
                        "The 72-hour model did not beat both baselines on AUC and Brier score in the test year, "
                        "so the chance of spreading comes from compared to normal."),
        "data_range": [first, last],
        "climatology_years": climatology_years(),
        "split": {k: forecast.mcfg()[k] for k in ("train_years", "calibration_year", "test_year")},
        "features": features.FEATURES,
        "not_used": "Weather, land cover and population are not model inputs in this build (no archived "
                    "weather, no land-cover / population raster). Peat = approximate district list.",
        "model1": {str(k): v for k, v in m1.items()},
        "model2": m2,
    }
    paths.MODELS.joinpath("model_card.json").write_text(json.dumps(card, indent=1), encoding="utf-8")
    # backtest needs the saved boosters
    card["backtest"] = alerts.backtest(cells, panel, clim, boundaries)
    paths.MODELS.joinpath("model_card.json").write_text(json.dumps(card, indent=1), encoding="utf-8")
    report(card)
    return card


def report(card: dict) -> None:
    print(f"\n72-hour model check (test year {card['split']['test_year']}, cut-off 50%):")
    print(f"  {'':<8}{'':<18}{'AUC':>7}{'hit':>7}{'f.alarm':>9}{'Brier':>8}")
    for h, r in card["model1"].items():
        for name in ("model", "burned_yesterday", "usual_for_month"):
            m = r[name]
            print(f"  {int(h) * 24:>3} h   {name:<18}{_f(m['auc']):>7}{_f(m['hit_rate']):>7}"
                  f"{_f(m['false_alarm_rate']):>9}{_f(m['brier'], 4):>8}")
        print(f"          beats both baselines: {r['beats_baselines']}  (trees {r['trees']}, rows {r['rows']})")
    print(f"  MODE: {card['mode']}")
    for k, v in card["model2"].items():
        print(f"3-month {k}: MAE model {v['mae_model']} vs usual {v['mae_usual']} -> "
              f"{'model' if v['use_model'] else 'usual'}")
    print("Backtest (High/Critical raised before the peak day):")
    for r in card.get("backtest", {}).get("rows", []):
        print(f"  {r['year']} {r['province']:<20} first High {r['first_high'] or '-':<11} first Critical "
              f"{r['first_critical'] or '-':<11} peak {r['peak_day']} -> {r['days_early']} days early")
    if card["is_sample"]:
        print("NOTE: trained on SAMPLE DATA. Retrain when the FIRMS archive arrives.")


def _f(x, nd=3):
    return "-" if x is None else f"{x:.{nd}f}"


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    run()


if __name__ == "__main__":
    main()
