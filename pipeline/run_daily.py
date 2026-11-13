"""Daily run (GitHub Action, 06:00 MYT): python -m pipeline.run_daily --export web/public/data

1. ingest: download the gap since the last data from FIRMS (keeps the existing data if FIRMS is down)
2. harmonize: fire cells, k, monthly counts
3. export: every JSON file the website reads (statistics, calendar, analysis, ranking, map points),
   plus fire events -> 72-hour chance (committed model, scoring only) -> rules -> alerts.json / model.json.
   Event IDs and level stability are saved in data/processed/alerts_state.json.
"""
from __future__ import annotations

import argparse
import json
import logging

from . import export, harmonize, ingest, weather


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--export", metavar="DIR", help="folder for the website JSON, e.g. web/public/data")
    p.add_argument("--skip-update", action="store_true", help="do not call FIRMS (offline re-export)")
    p.add_argument("--no-weather", action="store_true", help="do not call Open-Meteo (rain / haze left empty)")
    a = p.parse_args(argv)

    if not a.skip_update:
        result = ingest.update()
        print("ingest:", json.dumps(result, default=str))
        if result.get("is_sample"):
            print("NOTE: history is SAMPLE DATA (no FIRMS archive yet).")
    harmonize.run()
    if a.export:
        export.run(a.export, weather_fn=None if a.no_weather else weather.fetch, save_state=True)


if __name__ == "__main__":
    main()
