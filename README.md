# EG FireTrack

**Wildfire monitoring and early warning for Borneo, using NASA satellite data**

NASA Space Apps Challenge 2026 · Harmonization of MODIS and VIIRS Hot Spots· EG Solution 2.0 Team

### 🔗 Live website: **https://eg-firetrack.vercel.app**
Click to open. No login needed; works on computer and phone.

---

## The problem
NASA has two fire sensors: **MODIS** (1 km pixels) and **VIIRS** (375 m pixels). They count the same fires differently, so their numbers can't be compared or simply added.

## Our solution: five features
1. **Harmonized:** 10 years (2017–2026) of MODIS + VIIRS merged into one record, with every fire counted once.
2. **Analysis:** where and when fires happen, and whether today is normal or unusual.
3. **Forecast:** machine learning gives the chance a fire spreads in the next 72 hours, and shows why.
4. **Prediction:** expected fire activity for the next 3 months.
5. **Suggestion:** alert level, recommended actions, resources, who responds, and which fire to reach first.

## The four pages
| Page | Answers |
|---|---|
| **Map** | Where are the fires? |
| **Calendar** | When do fires happen? |
| **Analysis** | How did it change, and where is it going? |
| **Alerts** | What should be done, and where first? |

Tip: click **Intro** on the website for a quick guide.

## How harmonization works
1. Keep real vegetation fires only.
2. Put both sensors on the same **1 km grid**; each square counts once per day.
3. If MODIS and VIIRS see fire within **1 km and 1 hour**, it's the **same fire**, counted once.
4. Keep all VIIRS fires, plus the MODIS fires VIIRS missed.
5. On days without VIIRS data, estimate from MODIS with a calibration factor (k).

The result is checked by hiding each year and predicting it from the others.

## Always up to date
Every day at 06:00 Malaysia time, the system downloads new NASA FIRMS data, updates everything, and republishes the website automatically. **Data status** on the site shows the latest update.

## Built with
Python · pandas · GeoPandas · LightGBM · SHAP · React · Leaflet · ECharts · GitHub Actions · Vercel

## Data
NASA FIRMS (MODIS C6.1, VIIRS 375 m) · GADM boundaries · Open-Meteo weather · OpenStreetMap / Esri base maps

## Run locally
```bash
pip install -r pipeline/requirements.txt
python -m pipeline.run_daily --export web/public/data   # needs FIRMS_MAP_KEY in .env
cd web && npm install && npm run dev                    # http://localhost:5173
```
