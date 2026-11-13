# EG FireTrack
Wildfire hotspot monitoring for Borneo · NASA Space Apps Challenge 2026 · powered by EG Solution 2.0 Team

Live site: https://REPLACE-ME.vercel.app  ← judges: click here, no login needed

EG FireTrack harmonizes 10 years (2017–2026) of NASA MODIS and VIIRS fire hotspots into one record
and shows where fires are (Map), when they happen (Calendar), how unusual they are (Analysis)
and what to do (Alerts).

## How the data works
- **Sources:** NASA FIRMS hotspots from two satellite sensors, MODIS (1 km, since 2000) and VIIRS (375 m,
  since 2012), for Borneo, 2017–2026. Medians and averages use full years only.
- **Harmonization:** VIIRS pixels are ~7× smaller, so it catches small fires MODIS misses and counts one fire
  several times. The pipeline snaps both to a 1 km grid (one fire cell per day), matches MODIS and VIIRS cells
  within ±1 km / ±1 h as the same fire, keeps all VIIRS cells + MODIS-only cells, and calibrates a
  VIIRS÷MODIS ratio per province and season to fill days with no VIIRS data (details in `docs/technical.md`
  and `docs/logic-explained.md`).
- **Pipeline** (`pipeline/`, Python): ingest → harmonize → statistics → fire events → 72-hour and monthly
  forecasts (machine learning) → risk score, alert level and response rules → export.
- **Rules live in config:** every threshold, wording and response rule is in `config/` (`bands.yaml`,
  `resources.yaml`, `actions.yaml`, `jurisdictions.json`, …), not in code.
- **Storage:** `data/raw/` (archive downloads) stays local; `data/processed/` holds the harmonized
  history as Parquet plus simplified boundaries. Each daily run downloads only the last 24 h and appends.
- **Website data:** the pipeline writes small JSON files to `web/public/data/` (aggregated by
  province/district/month; raw points only for the last 30 days). The React site reads only these files,
  so there is no backend server. If FIRMS is unreachable, `data/sample/` is used and the site says "sample data".

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r pipeline/requirements.txt
cp .env.example .env                                   # then add your FIRMS_MAP_KEY
python -m pipeline.run_daily --export web/public/data  # builds the JSON data
cd web && npm install && npm run dev                   # open http://localhost:5173
```

## How it updates
A GitHub Action (`.github/workflows/daily.yml`) runs every day at 06:00 MYT: it downloads new
FIRMS data, harmonizes it, runs the forecast and alert rules, writes JSON files to
`web/public/data`; Vercel redeploys the website from that push.

## Deploy (how this site is hosted)
- **Website:** Vercel project with **Root Directory = `web`** (Vite, build `npm run build`, output `dist`).
  `web/vercel.json` sends every page URL (e.g. `/alerts`) to the app, and `web/api/notify.ts` is the only
  serverless function ("Notify nearby teams"; demo mode until `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` are set).
- **Daily data:** `.github/workflows/daily.yml` (06:00 MYT, or **Actions → Run workflow**) needs the repository
  secret `FIRMS_MAP_KEY` (Telegram ones optional). It commits the new data and Vercel's GitHub integration
  redeploys the site from that push. Without a FIRMS key or when FIRMS is down, the existing data is kept and
  the reason is shown in the Data status popover.

## Tests
```bash
pytest -q                      # pipeline rules
cd web && npm test && npm run build
```

## Data sources
NASA FIRMS (MODIS C6.1, VIIRS 375 m), Open-Meteo, NASA GFWED, GADM, WorldPop, OpenStreetMap.
Numbers marked "sample data" are illustrative.
