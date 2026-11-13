# EG FireTrack – Logic Explained

Nov 9, 2026 · @Edison

A plain-language explanation of every decision EG FireTrack makes: how the two satellites are combined, what machine learning does, how each status and prediction is defined, and what every term means. Exact formulas and code are in the [Technical Logic & Build Guide](technical.md).

## 1. Harmonization explained

Harmonization turns two satellites that count fires differently into one record that counts every fire once, the same way, every day.

### Why it is needed

|  | MODIS | VIIRS |
| --- | --- | --- |
| Pixel size | about 1 km × 1 km | about 375 m × 375 m (≈ 7× smaller in area) |
| What one fire looks like | usually 1 pixel | often several pixels side by side |
| Small fires | often missed | usually seen |
| Typical raw count for the same fires | lower | about 2–3× higher |

If we simply added the two, one fire would be counted several times. If we used either one alone, we would miss fires the other saw. Neither raw count can be compared with the other.

### The five steps in plain words

1. **Keep only real vegetation fires.** Drop volcanoes, gas flares and other fixed heat sources (`type = 0`), and drop low-confidence detections.
2. **Put both on the same grid.** Cover Borneo with a grid of 1 km squares (0.01°). Each detection falls into one square, called a **fire cell**. A square counts **once per day**, however many pixels lit up inside it. This removes most of the pixel-size difference.
3. **Match the same fire.** If a MODIS fire cell and a VIIRS fire cell are within 1 km and 1 hour of each other, they saw **the same fire**, so it counts once.
4. **Merge.** Harmonized fires = all VIIRS fire cells + the MODIS fire cells that VIIRS did not see ("MODIS-only"). VIIRS is the base because it is sharper; MODIS fills its gaps.
5. **Calibrate for gaps.** From 10 years of days when both worked, learn how many VIIRS fire cells there usually are per MODIS fire cell (the factor **k**, per province and season). On a day VIIRS has no data, MODIS fire cells × k estimate what VIIRS would have counted.

### Worked example (sample numbers)

On 21 Sep 2026, one fire burns in Pulang Pisau, and a second small fire burns 20 km away under a cloud edge.

| What happened | Raw MODIS | Raw VIIRS | After step 2 (fire cells) | After steps 3–4 (harmonized) |
| --- | --- | --- | --- | --- |
| Fire A (large) | 1 pixel | 9 pixels | MODIS 1 cell, VIIRS 3 cells | 3 cells (MODIS cell matches a VIIRS cell, counted once) |
| Fire B (under cloud edge) | 1 pixel | 0 pixels | MODIS 1 cell, VIIRS 0 | 1 cell (MODIS-only, kept) |
| **Total** | **2** | **9** | MODIS 2, VIIRS 3 | **4 fire cells** |

Raw counts said 2 or 9; the harmonized record says 4, and it would say 4 again tomorrow for the same situation, whichever satellite passed.

**Calibration example:** over ten Septembers in Central Kalimantan, VIIRS saw 26,000 fire cells and MODIS 10,000, so k = 2.6. If one day VIIRS data is missing and MODIS saw 40 fire cells, the System records 40 × 2.6 = **104** VIIRS-equivalent fire cells for that day.

### How we prove it works

- **Leave-one-year-out check:** hide one year, learn k from the other nine, estimate the hidden year, and compare with what actually happened. Repeat for every year.
- Report **R²** (how closely the estimate follows reality; 1.0 = perfect) and the **average error** in %.
- The Analysis page draws MODIS raw, VIIRS raw and harmonized lines together, using January–September of every year so the current year (2026) compares fairly.

## 2. Machine learning: what it does and does not decide

Machine learning answers only one kind of question: **"how likely is fire activity to grow here?"** Everything that affects people (the level, the priority, who responds, what resources) is decided by fixed rules that anyone can read and check.

| Machine learning decides | Fixed rules decide |
| --- | --- |
| Chance of spreading in the next 24 / 48 / 72 h, per 11 km cell | Compared to normal and its status |
| Hotspots and FRP expected in the next 3 months | Risk score and alert level |
| Which inputs pushed each chance up or down (reasons) | Rescue priority and share of teams |
|  | Who responds, resources, actions, notification channel |

Why split it this way: in an emergency, people must trust and explain each decision. A model's chance is useful evidence; a rule turns that evidence into an action the same way every time.

### Model 1: 72-hour chance of spreading

- **The question:** for each 0.1° grid cell (about 11 km) and each day, will there be at least one hotspot in the next 72 hours? (Also 24 h and 48 h.)
- **The answer:** a probability from 0% to 100%.
- **The model:** LightGBM, a "gradient boosting" model. It builds hundreds of small decision trees, each one correcting the mistakes of the trees before it (for example: "if no rain for > 14 days AND > 50 hotspots nearby → chance goes up").
- **What it learns from (inputs):**

| Group | Inputs |
| --- | --- |
| Recent fire | hotspots in the cell and within 25 km over the last 1, 3, 7 days |
| History | usual (median) count for this month |
| Weather now | days without rain, humidity, temperature, wind speed and direction |
| Weather next | rain forecast for 3 days |
| Dryness | Fire Weather Index |
| Land | peat depth, land cover, burned in the last 2 years |
| Season | month |

- **How it is trained:** each past day and cell becomes one example with its inputs and the true answer (did fire appear in the next 72 h?). Train on 2017–2024; test on 2025, a year the model never saw. Never split randomly, or the model "sees the future" and looks better than it is.
- **Imbalance:** most cells have no fire on most days, so fire examples get extra weight (`scale_pos_weight`); otherwise the model would learn to always say "no fire".
- **Calibration:** after training, chances are adjusted so that "70%" really means fire about 70 times in 100 (isotonic calibration).

### Model 2: 3-month prediction

- **The question:** how many hotspots (and what average FRP) will a province have in each of the next 3 months?
- **Inputs:** the last 3 months, the usual count for each coming month, how far this month is from normal, a seasonal rainfall outlook, and the El Niño (ENSO) index.
- **The answer:** a number per month, drawn as the dotted prediction line, with a shaded likely range.

### How we check the models

| Check | What it means | Must be |
| --- | --- | --- |
| Beat baseline 1: "burned yesterday → burns tomorrow" | the model must be smarter than copying yesterday | better |
| Beat baseline 2: "usual for this month" | the model must be smarter than the calendar | better |
| AUC | how well it ranks risky cells above safe ones (0.5 = guessing, 1.0 = perfect) | as high as possible, target > 0.85 |
| Hit rate | share of real fires it warned about | high |
| False alarm rate | share of warnings with no fire | low |
| Brier score | how close the chances are to what happened (0 = perfect) | low |

### How the System explains a chance (SHAP)

SHAP splits each prediction into the effect of each input, starting from the average cell (12%). Example for Pulang Pisau: no rain for 19 days **+21**, 112 hotspots nearby **+18**, Fire Weather Index 31 **+13**, deep peat **+8**, humidity 52% **+7**, month **+6**, burned in 2023 **−4**… = **86%**. These are the bars under "Why the System expects spreading".

## 3. How each status is defined

Every status comes from a number and a fixed band, so the same situation always gets the same label.

### Compared to normal (anomaly vs median)

**Anomaly % = (current count − usual count) ÷ usual count × 100**, where the usual count is the **median** of the same calendar window (same 24 h ±3 days, same 7 or 30 days,
same month so far, or Jan 1 to the same date) over the last 9 full years (2017–2025), never below a
floor of 10 fire cells. Up to +100% the value is shown as a percent ("+18%"); above that as a multiple ("3.2×"), capped at ">10×". The small line under it reads "vs usual · Unusual".

| Anomaly | Status |
| --- | --- |
| below +25% | Normal |
| +25% to +100% | Above average |
| above +100% | Unusual |

Example: a usual September has 1,170 hotspots; September 2026 has 2,340 → (2,340 − 1,170) ÷ 1,170 = **+100%** → Above average (right at the edge of Unusual).

### Chance words

| Chance of spreading | Word |
| --- | --- |
| 0–24% | Unlikely |
| 25–49% | Possible |
| 50–74% | Likely |
| 75–100% | Very likely |

### Risk score (0–100) and alert level

The score adds six parts, each with a maximum:

| Part | Max points | How points are given |
| --- | --- | --- |
| Chance of spreading (72 h) | 40 | chance × 40 |
| Compared to normal | 20 | 0% → 0, +300% or more → 20, in between in proportion |
| Intensity and growth | 10 | half from total FRP (1,000 MW = full), half from growth vs yesterday (+100% = full) |
| Fuel | 10 | no peat 0, shallow peat 5, deep peat 10 |
| People exposed | 15 | closer towns and more people within 30 km = more points |
| Haze across a border | 5 | 5 if smoke is forecast to reach another country within 3 days |

| Score | Level | Meaning |
| --- | --- | --- |
| 0–24 | Level 1 · Low | Monitor daily |
| 25–49 | Level 2 · Moderate | Verify on the ground within 24 h |
| 50–74 | Level 3 · High | Respond within 6 h |
| 75–100 | Level 4 · Critical | Respond within 2 h |

**Safety overrides:** a fire within 5 km of a town, hospital or airport, or with ≥ 50 hotspots in 24 h, is never below High. **Stability:** a level goes up at once, goes down only after 2 days in a row below the line, and the alert closes after 3 days with no hotspots.

### Rescue priority (Critical alerts only)

**Priority score = 0.5 × risk score + 0.3 × people exposure + 0.2 × growth**, where people exposure = 100 − 2.5 × km to the nearest town (0 at 40 km or more) and growth is % vs yesterday (max 100). The highest is **P1**. Each Critical alert's **share of rescue teams** = its priority ÷ the sum of all Critical priorities.

### Rescue risk status (Analysis page)

For an area, the status is the **highest alert level** inside it, and the score is the highest event score. It is explained with five inputs: Compared to normal, Chance of spreading, Recent direction, Fuel type and People nearby.

### Trend direction

| Week-on-week change over 3 weeks | Word |
| --- | --- |
| below −10% | Falling |
| −10% to +10% | Stable |
| above +10% | Rising |

### Worked example: Kapuas, 21 Sep 2026 (sample data)

Inputs: 41 hotspots in 24 h (+48%), +280% vs normal, 83% chance of spreading, total FRP 1,000 MW, deep peat, town 12 km away (exposure 0.7), smoke heading across the border.

| Part | Calculation | Points |
| --- | --- | --- |
| Chance | 0.83 × 40 | 33.2 |
| Compared to normal | 280 ÷ 300 × 20 | 18.7 |
| Intensity and growth | (0.5 × 1.0 + 0.5 × 0.48) × 10 | 7.4 |
| Fuel | deep peat | 10 |
| People exposed | 0.7 × 15 | 10.5 |
| Haze | crosses border | 5 |
| **Risk score** |  | **85 → Level 4 · Critical** |

Priority: 0.5 × 85 + 0.3 × 70 + 0.2 × 48 = **73** → highest of the 6 Critical alerts → **P1**, 73 ÷ 370 = **20% of rescue teams**.

## 4. How each prediction is defined

The System makes two kinds of prediction, and checks itself every day.

### 72-hour chance of spreading (alerts)

- **What is predicted:** the probability that a fire area gets **at least one new hotspot** in the next 72 hours (also 24 h and 48 h).
- **For a fire event:** the event's chance is the highest chance among the grid cells it covers.
- **Shown as:** a % plus a word (Unlikely, Possible, Likely, Very likely), labelled "72-hour system outlook".
- **Updated:** every day at 06:00 MYT, after the new satellite data arrives.
- **Reasons:** the top 6 SHAP effects, in percentage points, from the 12% starting point of an average cell.

### 3-month prediction (Analysis trend line)

- **What is predicted:** hotspots (or average FRP) for each of the next 3 months in the selected area.
- **Shown as:** a dotted line continuing the harmonized line past "now", inside a light orange zone.
- **Likely range:** a shaded band of ± 15% (next month), ± 25% (month 2) and ± 35% (month 3). It widens because the further ahead, the less certain.
- **Example:** if September is +100% above normal, October might be predicted around +55% above its usual, November +30%, December +15%, because unusual activity usually fades as the wet season starts. The model learns how fast it fades from past years.

### Next-day check (is the System right?)

Each day the System compares yesterday's 72-hour chance with what the satellites then saw:

| Yesterday said | Then the satellites saw | Result |
| --- | --- | --- |
| ≥ 50% | new hotspots | ✓ Correct |
| < 50% | no new hotspots | ✓ Correct |
| < 50% | new hotspots | ✗ Missed |
| ≥ 50% | no new hotspots | ✗ False alarm |

Every result is saved with its likely reason (for example "rain forecast was 4 mm but 22 mm fell"). Over 30 days these give the hit rate and false alarm rate, and they guide re-tuning of weights and thresholds.

## 5. Predefined terms on the website

Every label a user can see, and exactly what it means.

### Filters and summaries

| Label | Exact definition |
| --- | --- |
| Current / Now (last 24 h) | Hotspots from the latest 24 hours of satellite passes |
| 7 days, 30 days, 12 months, 5 years | Rolling window ending today |
| All (2017–2026) | The full 10-year window; 2026 is the current year, so it is partial |
| This month / This year | Calendar month / year to date (e.g. Jan–Sep 2026) |
| Yearly average | Mean of full years 2017–2025 (2026 in progress is excluded) |
| Average FRP | Mean Fire Radiative Power of hotspots in the area and period |
| Compared to normal | Anomaly vs median, in % (see section 3) |
| Most / Fewest hotspots | District ranking by harmonized hotspot count |

### Calendar

| Label | Exact definition |
| --- | --- |
| Usual | Median of the same month, 2017–2025 |
| Unusual month (outlined) | Month with ≥ 2× its usual count |
| Fire season | Months whose usual count ≥ 1.25× the average month |
| Season strength | Usual count of the peak month ÷ the quietest month |
| Record / quietest year | Full year with the most / fewest hotspots |
| 2026 so far vs 2025 | Jan–Sep 2026 compared with Jan–Sep 2025 |

### Analysis

| Label | Exact definition |
| --- | --- |
| MODIS raw / VIIRS raw | Each satellite's own fire cells before merging |
| Harmonized | Merged record (VIIRS + MODIS-only, gaps filled with k) |
| Prediction / likely range | 3-month model output and its ± 15/25/35% band |
| PAST / NOW / NEXT / DATA | Trend summary tags: history, current state, outlook, data note |
| Rescue risk status | Highest alert level in the area, with its score |
| Recent direction | Falling, Stable or Rising (week-on-week, 3 weeks) |
| Fuel type | No peat, Shallow peat (< 1 m), Deep peat (> 1 m) |
| People nearby | Fire events within 15 km of a town |
| Fit R² / average error | Quality of the harmonization check |

### Alerts

| Label | Exact definition |
| --- | --- |
| Level 1–4 (Low, Moderate, High, Critical) | Risk score band (section 3) |
| Directive | Fixed sentence per level, with its deploy-within time |
| Hotspots in 24 h / growth | Count in the event; % change vs the previous 24 h |
| Chance of spreading | 72-hour System outlook, with its word |
| Risk score | 0–100 rule score |
| Rescue priority P1, P2… / % of rescue teams | Rank and share among Critical alerts |
| Situation / Assessment / Recommendation | The three parts of the situation report |
| 0–2 h, 2–12 h, 12–72 h, Daily | Time window for each recommended action |
| Status: Notified, Team assigned, Monitoring | Where the alert is in its handling |
| Last check | Result of yesterday's prediction (correct, missed, false alarm) |
| Notify nearby teams | Sends the alert to the lead agency and teams within 50 km |
| System | Any result computed by EG FireTrack's models and rules |

## 6. Technical terms explained

Grouped by topic, each with a short example where it helps.

### Statistics

| Term | Explanation |
| --- | --- |
| Anomaly | How far a value is from what is normal. Here: (current − usual) ÷ usual. +150% means 2.5× the usual amount. |
| Mean (average) | Sum ÷ count. One extreme year (like 2019) pulls it up a lot. |
| Median | The middle value when sorted. For 9 Septembers it is the 5th. Extreme years barely move it, so it is a fairer "usual". |
| Percentile | Share of values below a number. "90th percentile" = higher than 90% of past values. |
| Quantile bins | Cutting all values into equal-sized groups; used for the 7 calendar colours so each colour appears fairly often. |
| Ratio / multiple (× usual) | Current ÷ usual. 2.0× = double. |
| Year to date (YTD) | From 1 January to today; used so 2026 is compared with the same months of past years. |
| Rolling window | A period that moves with today (last 7 or 30 days). |
| Linear trend | The straight line that best fits values over time; its slope shows rising or falling. |

### Satellites and fire

| Term | Explanation |
| --- | --- |
| Hotspot | A satellite pixel much hotter than its surroundings, usually a fire. |
| Pixel / resolution | The smallest square a sensor sees: MODIS 1 km, VIIRS 375 m. |
| Overpass | When a satellite flies over; Aqua and S-NPP pass at about 1:30 am and pm local solar time. |
| Swath gap | Areas between orbit strips that a satellite misses on a given pass. |
| Confidence | The algorithm's certainty that a hotspot is a real fire (low, nominal, high). |
| FRP | Fire Radiative Power, in MW: how fast the fire gives off heat. Measures intensity, not burned area. |
| Brightness temperature | How hot the pixel appears, in kelvin; above about 330 K is typical for active fire. |
| Static source | A heat source that never moves (gas flare, volcano, factory); removed with `type = 0`. |
| Near-real-time (NRT) | Data published within about 3 hours of the pass, before final processing. |
| Fire cell | A 1 km grid square with at least one detection that day; the unit we count. |
| Fire event | A cluster of ≥ 3 hotspots within 2 km over 48 h, treated as one fire. |
| Peat | Thick, carbon-rich wet soil. When drained and dry it burns underground for weeks and makes heavy haze. |
| Fire Weather Index (FWI) | A number from weather (temperature, humidity, wind, rain) showing how easily fires start and spread. |
| ENSO / El Niño | A Pacific climate cycle. El Niño years are drier in Borneo and have far more fires. |
| Transboundary haze | Smoke that drifts across country borders. |

### Machine learning

| Term | Explanation |
| --- | --- |
| Model | A formula learned from past examples that turns inputs into a prediction. |
| Feature / input | One piece of information the model uses, e.g. days without rain. |
| Label / target | The true answer the model learns, e.g. "fire in the next 72 h: yes or no". |
| Training / test data | Years the model learns from (2017–2024) / a year kept hidden to test it (2025). |
| Time split | Testing on a later period than training, so the model never sees the future. |
| Data leakage | When information from the future sneaks into training and makes results look too good. |
| Overfitting | When a model memorizes past examples instead of learning general patterns, so it fails on new data. |
| Class imbalance | When one answer is much rarer (fire days are rare); fixed with extra weight on fire examples. |
| Gradient boosting / LightGBM | Many small decision trees, each fixing the previous ones' errors; fast and accurate on tables. |
| Probability | A number from 0 to 1 (0% to 100%) saying how likely something is. |
| Calibration | Adjusting probabilities so "70%" really happens about 70 times in 100. |
| Baseline | A simple rule the model must beat to prove it adds value. |
| AUC | How well the model ranks risky cases above safe ones; 0.5 = coin flip, 1.0 = perfect. |
| Hit rate / False alarm rate | Share of real fires that were warned / share of warnings with no fire. |
| Brier score | Average squared gap between the predicted chance and what happened; lower is better. |
| SHAP | Splits a prediction into each input's push up or down, so people can see why. |
| Regression | A model that predicts a number (e.g. hotspots next month) instead of yes/no. |
| R² | How much of the real variation a prediction explains; 1.0 = perfect, 0 = no better than the average. |
| Leave-one-year-out | Testing by hiding each year in turn and predicting it from the others. |

### Rules and data handling

| Term | Explanation |
| --- | --- |
| Risk score | A 0–100 points total from six parts; sets the level. |
| Override | A safety rule that can raise the level regardless of score. |
| Hysteresis (level stability) | Going up fast but down slowly, so levels don't flip back and forth daily. |
| Exposure | How many people a fire could affect, from distance to towns and population. |
| Priority score | Risk, exposure and growth combined, used to rank Critical alerts. |
| DBSCAN | A clustering method: points close enough together become one group. |
| Haversine distance | Distance between two latitude/longitude points on the curved Earth. |
| Spatial join | Finding which boundary (state, district) a point falls inside. |
| Calibration factor (k) | VIIRS fire cells ÷ MODIS fire cells; puts MODIS on the VIIRS scale. |
| De-duplication | Removing repeated records of the same detection. |

## 7. Other technical logic

Rules not covered in the earlier docs that the real system also needs.

### Time and dates

- **Time zone:** FIRMS gives UTC. The System converts to Malaysia/Brunei time (UTC+8) for display; Kalimantan uses UTC+7 or +8 by province, shown in the alert. A "day" for counting is the local calendar day.
- **Partial current year:** 2026 is still running. It is never used in medians or yearly averages, and it is compared with past years only for the same months (Jan–Sep).
- **Rolling 10-year window:** at the start of each year the oldest year drops out and medians are recomputed, so "usual" always means the last 9 full years.

### Data quality

- **Missing passes:** if a satellite pass is missing or the download fails, the day is marked incomplete; counts use the calibration factor k to fill VIIRS gaps, and the UI shows "partial data".
- **Cloud cover:** clouds hide fires, so a quiet cloudy day is not proof of no fire. The forecast uses rain and humidity inputs; alerts never close on a single cloudy day (they need 3 days with no hotspots).
- **Duplicates:** the same detection can arrive twice (NRT then final data). Records are de-duplicated by sensor, satellite, location and time; final data replaces NRT when it arrives.
- **Several VIIRS satellites:** S-NPP, NOAA-20 and NOAA-21 can see the same fire within an hour. On the 1 km grid they count once per day, just like MODIS matching.
- **Static sources:** besides `type = 0`, any 1 km cell that shows heat on more than 60% of days in a year is masked as a likely industrial site.
- **Outliers:** a sudden jump of > 10× in one cell in one day is flagged for review before it can raise an alert to Critical.

### Models and rules over time

- **Retraining:** the 72-hour and monthly models are retrained once a year after the fire season, and whenever the 30-day hit rate drops below an agreed limit.
- **Versioning:** each forecast saves the model version and the rule-file version that produced it, so any past alert can be explained later.
- **Rule changes:** thresholds and weights live in config files; any change is reviewed, dated and logged.

### Accountability

- **Audit trail:** every alert keeps a history: when it was created, each level change and why, who was notified, when, and who acted.
- **Human decision:** the System recommends; the duty officer can change the level, the priority or the plan, and the change is logged with a reason.
- **Same rules for every country:** Sarawak, Sabah, Brunei and Kalimantan are scored with identical rules; only the responding agencies differ.
- **Honest labels:** sample or partial data is always marked on screen, and predictions are labelled as estimates, not guarantees.
