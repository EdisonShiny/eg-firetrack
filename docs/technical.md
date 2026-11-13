# EG FireTrack – Technical Logic & Build Guide

Nov 9, 2026 · @Edison

How EG FireTrack works under the hood, every rule and value it uses, and the special terms on the website.

## Architecture

A Python pipeline runs once a day and precomputes everything: harmonized data, statistics, forecasts, alerts and reports. It exports the results as small JSON files that the website reads directly, so every page loads fast and nothing heavy runs while a user waits.

&#91;embedded content: system architecture · data to web app\]

The pipeline writes JSON files; the web app reads them, and alarms go straight to nearby teams and the duty officer.

## Data: getting it and harmonizing it

All fire data comes free from NASA FIRMS. We download the 10-year history (2017–2026) once, add new detections every day, and merge both satellites into one harmonized record.

### A. Get the 10-year history (one time)

1. Create a free NASA Earthdata account, then a FIRMS **MAP\_KEY**.
2. On FIRMS **Archive Download**, request CSVs for the Borneo box (longitude 108.5–119.5, latitude −4.5 to 7.5), Jan 2017 to today, for **MODIS C6.1** (Terra + Aqua, 1 km) and **VIIRS 375 m** (S-NPP; NOAA-20 optional).
3. FIRMS emails a download link; it can take hours, so request it early.
4. Keep: `latitude, longitude, acq_date, acq_time, satellite, instrument, confidence, frp, brightness / bright_ti4, daynight, type`.

### B. Get recent data (every day)

- Call the FIRMS area API daily per source, e.g. `https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/VIIRS_SNPP_NRT/108.5,-4.5,119.5,7.5/1`, and the same with `MODIS_NRT`.
- Near-real-time data appears within about 3 hours of each satellite pass.
- Append, remove duplicates (same sensor, lat, lon, date, time), and drop rows older than 10 years.

### C. Clean and standardize

1. Clip points to Borneo land and tag country, state/province and district (GADM).
2. Keep vegetation fires only (`type = 0`).
3. One confidence scale: MODIS 0–29 low, 30–79 nominal, 80–100 high; VIIRS l / n / h. Drop low.
4. Store: `lat, lon, date, time_utc, time_myt, sensor, satellite, confidence, frp, brightness, daynight, province, district`.

### D. Harmonize: the principle

VIIRS pixels are about 7× smaller in area, so one fire lights several VIIRS pixels and VIIRS catches small fires MODIS misses. MODIS sometimes catches a fire VIIRS misses (cloud edge, swath gap, other pass time). Harmonization makes both count fires the same way:

1. **Same grid:** snap every detection to a 1 km grid (0.01°); one fire cell counts **once per day**.
2. **Same time:** calibrate on matching passes only (Aqua and S-NPP both cross at about 1:30 am and pm).
3. **Match:** a MODIS and a VIIRS fire cell within ±1 km and ±1 hour are the **same fire**, counted once.
4. **Merge:** harmonized fires = all VIIRS fire cells + MODIS-only fire cells.
5. **Calibrate:** fit *k = VIIRS cells ÷ MODIS cells* per province and season; on days with no VIIRS data, MODIS × *k* fills the gap.
6. **Check:** leave one year out, refit, predict it, report R² and error. The Analysis page compares Jan–Sep of every year so 2026 compares fairly.

### E. Harmonize: the code

```python
import numpy as np, pandas as pd

df = df[(df.type == 0) & (df.confidence != "low")]
df["cell"] = (np.floor(df.lat / 0.01)).astype(int).astype(str) + "_" + (np.floor(df.lon / 0.01)).astype(int).astype(str)
df["t"] = pd.to_datetime(df.date + " " + df.time_utc)

cells = df.sort_values("t").drop_duplicates(["sensor", "date", "cell"])
v = cells[cells.sensor == "VIIRS"]; m = cells[cells.sensor == "MODIS"]

pair = m.merge(v, on="date", suffixes=("_m", "_v"))
near = (abs(pair.lat_m - pair.lat_v) <= 0.01) & (abs(pair.lon_m - pair.lon_v) <= 0.01) \
       & (abs(pair.t_m - pair.t_v) <= pd.Timedelta("1h"))
matched = set(pair.loc[near, "cell_m"] + "|" + pair.loc[near, "date"])
modis_only = m[~(m.cell + "|" + m.date).isin(matched)]

harmonized = pd.concat([v, modis_only])           # one record, no double count

monthly = cells.groupby(["sensor", "province", "month"]).size().unstack("sensor")
k = (monthly["VIIRS"] / monthly["MODIS"]).groupby("province").median()
```

Outputs: `harmonized_cells` (one row per fire cell per day) and `monthly_counts` (`province, district, year, month, count, frp_mean, frp_high_count`), which every page reads.

## The logic

Machine learning estimates the fire risk; fixed, transparent rules decide level, priority and response; the duty officer confirms. A next-day check feeds results back.

&#91;embedded content: data-to-action flow · 9 steps, 1 feedback loop\]

### 1. Fire events

- Harmonized hotspots within about 2 km over 48 h form one **fire event** (DBSCAN, haversine, `eps = 2 km`, `min_samples = 3`), so one fire gives one alert.
- 1–2 isolated hotspots are only **Watch** (map only). An event needs ≥ 3 hotspots or hotspots on 2 days in a row.
- New hotspots inside an event update it; an event keeps its ID if its centre moves < 5 km.

### 2. 72-hour forecast (machine learning)

- **Predicts:** chance of ≥ 1 hotspot in each 0.1° cell (≈ 11 km) in the next 24, 48, 72 h.
- **Inputs:** hotspots nearby (1, 3, 7 days), same-month median, days without rain, rain forecast, humidity, temperature, wind, Fire Weather Index, peat depth, land cover, burned in the last 2 years, month.
- **Model:** LightGBM; train 2017–2024, test 2025 (time split); `scale_pos_weight` for imbalance; isotonic calibration.
- **Must beat** "burned yesterday → burns tomorrow" and "usual for this month" (AUC, hit rate, false alarm rate, Brier score).
- **Reasons:** SHAP gives each input's + / − effect; the top 6 show on each alert.

### 3. Monthly prediction (Analysis trend line)

- A LightGBM regression per province predicts hotspots and average FRP for the next 3 months.
- Inputs: last 3 months, same-month median, current anomaly, seasonal rainfall outlook, ENSO index.
- Shown dotted with a range of ± 15%, ± 25%, ± 35% for months 1–3.

### 4. Risk score and level

| Part | Points | Rule |
| --- | --- | --- |
| Chance of spreading (72 h) | 0–40 | probability × 40 |
| Compared to normal | 0–20 | 0% = 0, ≥ +300% = 20, linear between |
| Intensity and growth | 0–10 | total FRP and % growth vs yesterday |
| Fuel (peat) | 0–10 | none 0, shallow 5, deep 10 |
| People exposed | 0–15 | distance to towns, population within 30 km |
| Haze across a border | 0–5 | smoke reaches another country within 3 days |

- Level bands: see Predefined display values.
- **Overrides:** fire within 5 km of a town, hospital or airport, or ≥ 50 hotspots in an event in 24 h → at least High; smoke crossing a border → always inform the neighbouring country.
- **Stability:** up at once; down after 2 days below; close after 3 days with no hotspots.

### 5. Rescue priority (Critical alerts)

Priority score = 0.5 × risk score + 0.3 × people exposure + 0.2 × growth. Critical alerts are ranked P1, P2… and each gets a share of rescue teams = its priority ÷ sum of all Critical priorities. The duty officer can override.

### 6. Response rules

**Who responds:**

| Location | Lead agency | Support | Critical adds |
| --- | --- | --- | --- |
| Sarawak | Bomba Sarawak (Fire and Rescue Dept.) | Sarawak state disaster office | NADMA |
| Sabah | Bomba Sabah (Fire and Rescue Dept.) | Sabah state disaster office | NADMA |
| Brunei | Fire and Rescue Department | National Disaster Management Centre |  |
| Kalimantan province | BPBD of that province | Manggala Agni | BNPB |
| Smoke crosses a border | also inform ASMC and the neighbouring country |  |  |

**Resources:**

| Level | Firefighters | Engines | Pumps | Helicopters | Extras |
| --- | --- | --- | --- | --- | --- |
| Low | 5–10 | 1 | 0 | 0 | none |
| Moderate | 20–50 | 3 | 4 | 0 | verification team |
| High | 50–150 | 5 | 10 | 1 |  |
| Critical | 150–250 | 6 | 20 | 2 | cloud seeding aircraft (if clouds ≥ 40%) |

Modifiers: deep peat → firefighters × 1.5 and peat injection lances (10 / 6 / 3 for Critical / High / Moderate); > 10 km from a road → +1 helicopter; town within 15 km → field medical post and N95 masks; every 10 hotspots above 20 → +1 crew of 10. Arrive within ≤ 2 h Critical, ≤ 6 h High, ≤ 24 h Moderate.

**Actions:**

| When | Condition | Action |
| --- | --- | --- |
| 0–2 h | High or Critical | Dispatch ground crews to the fire edge |
| 0–2 h | High/Critical on peat | Start peat injection |
| 0–2 h | > 10 km from a road or growth > 40% | Request aerial water bombing |
| 2–12 h | Moderate | Send a verification team |
| 2–12 h | High or Critical | Cut firebreaks downwind |
| 2–12 h | town within 15 km | Health advisory and masks |
| 12–72 h | deep peat | Block drainage canals to rewet peat |
| 12–72 h | Critical | Assess cloud seeding (cloud cover ≥ 40%, little rain forecast) |
| 12–72 h | smoke crosses a border | Inform ASMC and neighbouring country |
| Daily | all levels | Re-check with the next satellite pass |

### 7. Situation report (System text)

- **Situation:** "{hotspots} hotspots detected in the last 24 h (+{growth}% vs yesterday), on {peat}. Nearest town {km} km; nearest road {km} km. No rain for {days} days."
- **Assessment:** "Compared with a normal {month}, activity is {anomaly}. The System gives a {chance}% chance of further spreading within 72 hours ({words}). Risk score {score}/100 → Level {n} {level}."
- **Recommendation:** the level's directive, plus for Critical "Rescue priority P{rank}: assign about {share}% of available rescue teams."

### 8. Notifications

| Level | Channel | If no one responds |
| --- | --- | --- |
| Low | dashboard only | none |
| Moderate | dashboard + email to the local agency | none |
| High | SMS + email to lead and support | resend after 1 h |
| Critical | SMS + call + email + national agency | escalate to the backup contact after 30 min |

**Notify nearby teams** sends the alert to the lead agency and to teams based within 50 km.

### 9. Next-day check

Each day the System compares yesterday's 72-hour outlook with what satellites saw (correct, missed, false alarm) and records why. Thirty days of checks tune the weights and thresholds.

## Predefined display values

Every number the System shows maps to a fixed band and wording, so every user reads a result the same way.

### Chance of spreading (72-hour System outlook)

| Probability | Words shown | Colour |
| --- | --- | --- |
| 0–24% | Unlikely | green |
| 25–49% | Possible | yellow |
| 50–74% | Likely | orange |
| 75–100% | Very likely | red |

### Compared to normal (anomaly vs median)

Formula: (current − usual) ÷ usual × 100, harmonized fire cells on both sides.
Usual = max(median of the **same calendar window** in each full year 2017–2025, floor of 10 cells)
(config/bands.yaml `compared_to_normal_rule`). Windows: Current = the same 24 h window on the same day
±3 days (averaged); 7 days / 30 days = the same rolling window; This month = the same month up to the
same date and time; This year = Jan 1 to the same date. Display (short, same on Map, Alerts, Analysis, PDF):
up to +100% show the percent ("+18%"), above that the ratio ("3.2×"), above 10× ">10×"; small line
"vs usual · Normal / Above average / Unusual". Tile text never overflows. Map summaries pick the window from the Period
(12 months / 5 years / all use This year); Analysis risk band, Alerts and situation reports use This month.

| Anomaly | Status shown | Meaning |
| --- | --- | --- |
| below +25% | Normal | within the usual range |
| +25% to +100% | Above average | clearly more than usual |
| above +100% | Unusual | more than double the usual |
| calendar cell ≥ 2× median | outlined cell | unusual month |

### Risk score and alert level

| Score (0–100) | Level | Directive shown | Deploy within |
| --- | --- | --- | --- |
| 0–24 | Level 1 · Low | Monitor daily. No deployment needed yet. | none |
| 25–49 | Level 2 · Moderate | Verify on the ground and prepare resources. | 24 h |
| 50–74 | Level 3 · High | Response required. | 6 h |
| 75–100 | Level 4 · Critical | Immediate response required. | 2 h |

### Rescue priority (Critical only)

- **Priority score** = 0.5 × risk score + 0.3 × people exposure + 0.2 × growth; people exposure = 100 − 2.5 × km to the nearest town (0 at ≥ 40 km); growth = % vs yesterday (max 100).
- **Rank:** P1 = highest priority score.
- **Share of rescue teams** = priority ÷ sum of all Critical priorities × 100 (all shares add up to 100%).
- Example (sample data): Kapuas, 12 km from a town, score 85, growth +48% → priority 73 → P1, 20% of rescue teams.

### Rescue risk status (Analysis, per area)

Status = highest alert level in the area; score = highest event score. Extra input bands:

| Input | Bands / words |
| --- | --- |
| Recent direction (week-on-week, 3 weeks) | Falling < −10% · Stable −10% to +10% · Rising > +10% |
| Fuel type | No peat · Shallow peat (< 1 m) · Deep peat (> 1 m) |
| People nearby | number of fire events within 15 km of a town |

### Trend and calendar wording

| Item | Rule | Shown as |
| --- | --- | --- |
| Trend direction | last 12 months vs average full year | "+x% vs average year" |
| Fire season | months whose median ≥ 1.25 × average month | e.g. "Aug – Oct" + share of yearly hotspots |
| Season strength | peak month median ÷ quietest month median | e.g. "10.8×" |
| Calendar colours | 7 bins from quantiles of all months in the area | green → yellow → orange → red |
| Prediction range | ± 15%, ± 25%, ± 35% for months 1–3 | shaded band |

### Other fixed values

| Item | Value |
| --- | --- |
| Hotspot dot size (FRP) | < 10 MW small · 10–50 MW medium · > 50 MW large with outline |
| Very intense hotspot | FRP > 100 MW |
| Fire event | ≥ 3 hotspots within 2 km over 48 h, or 2 days in a row |
| Watch (no alert) | 1–2 isolated hotspots |
| Sudden increase | last 7 days ≥ 2 × previous 7 days and ≥ 10 hotspots |
| Level stability | up at once · down after 2 days below · close after 3 days with none |
| Last prediction check | ✓ correct · ✗ missed · ✗ false alarm (50% chance as the cut-off) |

## Implementation

### Tech stack

| Layer | Tool | Used for |
| --- | --- | --- |
| Fire data | NASA FIRMS archive + FIRMS API (free MAP\_KEY) | MODIS C6.1 and VIIRS 375 m, 10-year history + daily updates |
| Other data | Open-Meteo, NASA GFWED (Fire Weather Index), GADM, WorldPop, a peatland map, OpenStreetMap, NOAA ENSO index | Forecast inputs and response rules |
| Processing | Python, pandas, numpy, geopandas, scikit-learn | Cleaning, harmonization, clustering, statistics |
| Storage | Parquet + DuckDB (or PostgreSQL + PostGIS) | Hotspots, monthly counts, forecasts, alerts |
| Machine learning | LightGBM + SHAP | 72-hour and monthly forecasts, reasons |
| Rules | `jurisdictions.json`, `resources.yaml`, `actions.yaml`, `bands.yaml` | Levels, priority, responders, resources, actions, display wording |
| Data delivery | Static JSON files (exported by the pipeline) + one Vercel serverless function | Page data, CSV export, "Notify nearby teams" |
| Frontend | React + Vite + TypeScript, Leaflet + Leaflet.draw, Apache ECharts | Map, calendar, charts, shared top bar |
| Reports | Jinja2 + WeasyPrint | PDF report |
| Notifications | SMTP email, Twilio SMS, Telegram Bot API | Alerts to teams |
| Hosting | GitHub Actions (daily run), Vercel (web) | Deployment |

### Project folders

```
eg-firetrack/
  .env  docs/  data/raw  data/processed  data/sample
  pipeline/  ingest.py harmonize.py stats.py events.py forecast.py rules.py reports.py run_daily.py
  config/    jurisdictions.json resources.yaml actions.yaml bands.yaml
  web/       api/notify.ts  public/data/*.json  src/components/TopBar.tsx  src/pages/{Map,Calendar,Analysis,Alerts}Page.tsx
  tests/
```

### Risk score, level and priority code

```python
def risk_score(e):
    s  = 40 * e.chance_72h
    s += 20 * min(max(e.anomaly_pct, 0) / 300, 1)
    s += 10 * min(0.5 * e.frp_sum / 1000 + 0.5 * max(e.growth_pct, 0) / 100, 1)
    s += {"none": 0, "shallow": 5, "deep": 10}[e.peat]
    s += 15 * e.exposure                      # 0-1
    s += 5 if e.haze_to_border else 0
    return round(s)

def level(score, e):
    lv = 4 if score >= 75 else 3 if score >= 50 else 2 if score >= 25 else 1
    if e.km_to_town < 5 or e.hotspots_24h >= 50:
        lv = max(lv, 3)
    return lv                                   # 1 Low, 2 Moderate, 3 High, 4 Critical

def priority(e):
    exposure = max(0, 100 - 2.5 * e.km_to_town)
    return round(0.5 * e.score + 0.3 * exposure + 0.2 * min(e.growth_pct, 100))

critical = sorted([e for e in events if e.level == 4], key=priority, reverse=True)
total = sum(priority(e) for e in critical)
for rank, e in enumerate(critical, 1):
    e.rank, e.team_share = rank, round(priority(e) / total * 100)
```

### Backend API

| Endpoint | Returns |
| --- | --- |
| `GET /api/hotspots?area&place&period` | GeoJSON points with all popup fields |
| `GET /api/summary?area&place&period` | 6 numbers for Whole Borneo and for the selected area |
| `GET /api/ranking?order=most\|fewest&period=now\|month\|year` | Top 5 districts |
| `GET /api/places` | Towns and districts with their area (used to auto-set Area) |
| `GET /api/calendar?area&place` | 10 × 12 counts, medians, unusual flags, seasonal summary, yearly totals |
| `GET /api/analysis?area&measure&window` | MODIS raw, VIIRS raw, harmonized, prediction + range, trend summary, rescue risk status, harmonization check |
| `GET /api/alerts?level` | Status counts and list (Critical with rank and team share) |
| `GET /api/alerts/{id}` | Situation report, reasons, actions, resources, coordination |
| `POST /api/alerts/{id}/notify` | Notify nearby teams |
| `GET /api/export/csv?…`, `GET /api/report/pdf?…` | Downloads |

### Frontend

- **Shared top bar:** one component above all pages. Area, Place, Period live in one shared store and in the URL (`?area=sarawak&place=miri&period=30d`), so they stay when switching pages or sharing a link. Choosing a Place sets Area from `/api/places`; changing Area clears a Place outside it. Alert counts refresh every minute.
- **Map:** Leaflet with OpenStreetMap and Esri imagery, `maxBounds` on Borneo, Leaflet.draw, `circleMarker` sized by FRP, popups, clustering.
- **Calendar:** ECharts heatmap, piecewise green → red scale, tooltips, outlined unusual cells, clickable years, yearly bar chart.
- **Analysis:** ECharts line chart with MODIS, VIIRS, harmonized and a dotted prediction + band; Hotspots/FRP and 12 months/5 years/10 years switches; gauge bar for rescue risk status; harmonization check chart.
- **Alerts:** status tiles filter the list; selecting an alert loads its report.

### Exports

- **CSV:** filtered hotspots, monthly and yearly statistics.
- **PDF report:** area, place, period, totals, Compared to normal, calendar, trend chart, alerts, data sources and sensor notes.

### Daily schedule (06:00 MYT)

1. Download the last 24 h from FIRMS; append; keep 10 years.
2. Clean, harmonize, update counts and statistics.
3. Run 72-hour and monthly forecasts; compute SHAP reasons.
4. Cluster events; score, level, priority; response rules; situation reports.
5. Send notifications; record the next-day check.

### Testing

- Unit tests for every band, score, level, override, priority and response rule.
- Harmonization: leave-one-year-out R² and error.
- Backtest the 2019 and 2023 fire seasons: would High or Critical have been raised, and how many days early?
- Every page loads in under 2 seconds with the full 10 years.

## Glossary

Special terms used on the website and in this doc, in alphabetical order.

| Term | Short explanation |
| --- | --- |
| 72-hour System outlook | The forecast model's chance that a fire area gets more hotspots in the next 3 days; shown as "Chance of spreading". |
| Anomaly vs median | How far current activity is from the usual (median) for the same month, in %; shown as "Compared to normal". |
| Aqua / Terra | The two NASA satellites that carry MODIS. |
| ASMC | ASEAN Specialised Meteorological Centre; monitors haze across Southeast Asia. |
| Baseline | A simple rule the forecast must beat to be useful (e.g. "burned yesterday → burns tomorrow"). |
| BNPB / BPBD | Indonesia's national / provincial disaster management agencies. |
| Bomba | Malaysia's Fire and Rescue Department (JBPM). |
| Brightness temperature | How hot the pixel looks to the satellite, in kelvin (K); higher usually means a hotter fire. |
| Calibration factor (k) | The ratio VIIRS fires ÷ MODIS fires, used to put MODIS counts on the VIIRS scale. |
| Cloud seeding | Spraying particles into clouds to make rain; only useful when there are enough clouds. |
| Confidence | How sure the satellite algorithm is that a hotspot is a real fire (low, nominal, high). |
| DBSCAN | A clustering method that groups nearby points; used to turn hotspots into fire events. |
| ENSO / El Niño | A Pacific climate pattern; El Niño years are drier in Borneo and have more fires (e.g. 2019, 2023). |
| Fire event | A group of ≥ 3 hotspots within about 2 km over 48 hours, treated as one fire. |
| Fire season | Months whose usual count is ≥ 1.25× the average month (Borneo: about Aug–Oct). |
| Fire Weather Index (FWI) | A score of how easily fires start and spread, from weather; higher = more dangerous. |
| Firebreak | A cleared strip of land that stops a fire from spreading. |
| FIRMS | NASA's Fire Information for Resource Management System, the free source of hotspot data. |
| FRP (Fire Radiative Power) | How fast a fire releases heat, in megawatts (MW); a measure of intensity, not of area burned. |
| GADM | A free database of country, state and district boundaries. |
| Harmonization | Making MODIS and VIIRS records count fires the same way so they form one consistent record. |
| Hotspot | A satellite pixel much hotter than its surroundings, usually a fire. |
| LightGBM | A fast machine-learning model (gradient boosting) used for the forecasts. |
| Manggala Agni | Indonesia's forest and land fire brigade. |
| MAP\_KEY | The free key that lets you download data from the FIRMS API. |
| Median ("usual") | The middle value of past years for the same month; less affected by extreme years than the average. |
| MODIS | Older NASA fire sensor (since 2000), 1 km pixels. |
| NADMA | Malaysia's National Disaster Management Agency. |
| Near-real-time (NRT) | Satellite data published within about 3 hours of the pass. |
| Overpass | When a satellite passes over an area; Aqua and S-NPP pass at about 1:30 am and pm. |
| Peat / peat injection | Peat is wet, carbon-rich soil that burns underground for weeks; peat injection pushes water deep into it with a lance. |
| R² | How well the harmonized record matches the check data (1.0 = perfect). |
| Rescue priority (P1, P2…) | Ranking of Critical alerts by risk, people exposed and growth, with each one's share of rescue teams. |
| Risk score | A 0–100 rule-based score that sets the alert level. |
| SHAP | A method that shows how much each input pushed the forecast up or down. |
| S-NPP / NOAA-20 | Satellites carrying VIIRS. |
| Situation report | The three-part alert text: Situation, Assessment, Recommendation. |
| System | Any result computed by EG FireTrack's models and rules (used instead of "AI"). |
| Transboundary haze | Smoke that drifts from one country into another. |
| Unusual month | A month with ≥ 2× the usual count; outlined on the calendar. |
| VIIRS | Newer fire sensor (since 2012), 375 m pixels, sees more and smaller fires. |
| Watch | 1–2 isolated hotspots; shown on the map but not yet an alert. |
