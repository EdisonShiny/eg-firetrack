# EG FireTrack – Project Overview

Nov 9, 2026 · @Edison

*Powered by EG Solution 2.0 Team*

## Introduction

EG FireTrack is a web app that turns the last **10 years (2017–2026)** of NASA satellite fire data into one consistent record for the whole of Borneo: Sarawak, Sabah, Brunei and Kalimantan. It is built for fire managers, emergency responders, land managers and scientists, for the NASA Space Apps 2026 challenge "Harmonization of MODIS and VIIRS Hot Spots".

**The problem.** Satellites have tracked fire hotspots since 2000, but the record comes from two sensors that cannot be compared directly:

- **MODIS** (Terra and Aqua): data since 2000, coarse 1 km pixels, now near the end of its life.
- **VIIRS** (S-NPP, NOAA-20/21): data since 2012, sharper 375 m pixels, so it detects about 2–3× more hotspots.

The archive goes back to 2000, but for this project we use only the **last 10 years**. Both sensors were working for the whole of that window, so every year can be cross-checked between them. Used raw, the two sensors disagree, and a manager cannot tell whether this year is truly unusual.

**Our solution.** We harmonize MODIS and VIIRS into one dataset, so the sensor no longer matters (see Data, below). On top of it, the app answers four questions:

1. **Where** are the fires? (Map)
2. **When** do fires usually happen? (Calendar)
3. **How** did activity move in the past, where is it now, and where is it going? (Analysis)
4. **What** should be done, and where first? (Alerts)

## The website at a glance

Four pages share one sticky top bar (Area, Place, Period, active alerts) that keeps the user's choices on every page.

| Page | Question it answers | What the user sees |
| --- | --- | --- |
| Map | Where are the fires? | Street or satellite map of Borneo with clickable hotspots; summaries for Whole Borneo and the selected area; top 5 districts with the most or fewest hotspots |
| Calendar | When do fires happen? | 10-year × 12-month heatmap (green to red), unusual months outlined, hotspots per year, the fire season and key seasonal facts |
| Analysis | How did it move, where is it now, where is it going? | MODIS, VIIRS and harmonized trend lines with a 3-month prediction; trend summary; rescue risk status with its reasons; harmonization check |
| Alerts | What to do, and where first? | Status counts and alert list; for each alert a situation report, the System's reasons, actions by time window, resources, coordination, and rescue priority for Critical alerts |

## How it works

&#91;embedded content: how EG FireTrack works · data to action\]

1. **Harmonize:** MODIS and VIIRS hotspots are put on one 1 km grid, matched, and merged into one record with no double counting.
2. **Forecast (machine learning):** a model estimates the chance of spreading in the next 72 hours, and a second one the next 3 months.
3. **Decide (fixed rules):** a 0–100 risk score sets the level (Low to Critical); Critical alerts get a rescue priority and share of teams; rules pick who responds, which resources and which actions.
4. **Act and learn:** nearby teams are notified and the duty officer decides; each day the System checks yesterday's forecast against what satellites saw.

## What makes it stand out

- **10 years of harmonized MODIS + VIIRS data**, with a visible check that the two satellites agree.
- **A top bar that never disappears**; picking a place sets its area automatically.
- **Whole-Borneo and selected-area summaries side by side**, plus district rankings.
- **Past → now → next in one chart**, with a 3-month prediction.
- **Rescue priority for Critical alerts:** which fire to reach first, and what share of teams each needs.
- **Professional situation reports** with time-windowed actions, resources and coordination.
- **Explainable:** every System result shows its reasons and uses fixed, published bands and wording.

## Limitations

- Clouds and thick haze can hide fires, and satellites pass over only a few times a day.
- The project uses a fixed 10-year window (2017–2026); older years can be added later.
- Score weights, thresholds and resource numbers are starting values that need calibration with fire agencies.
- Forecasts and rescue priority support decisions; they are not guarantees.
- All numbers in the prototype are sample values.

## Project documents

- [EG FireTrack – Visual Design Spec](visual.md): layout, colours, components and page-by-page behaviour.
- [EG FireTrack – Technical Logic & Build Guide](technical.md): data, harmonization, all logic and values, implementation and glossary.
- [EG FireTrack – Logic Explained](logic-explained.md): plain-language explanation of harmonization, machine learning, statuses, predictions and every term.
