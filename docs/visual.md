# EG FireTrack – Visual Design Spec

Nov 9, 2026 · @Edison

What every page of EG FireTrack looks like and how it behaves. This doc is the written spec for every page; the live site is at https://REPLACE-ME.vercel.app.

## Layout

All four pages share one frame: a two-row sticky top bar, then a wide main panel on the left and a narrower side column on the right. Desktop design width is 1440 px.

&#91;embedded content: app shell wireframe · top bar, main panel, side column\]

On Analysis the rescue risk band and harmonization check run across the full width below the chart row.

## Look and feel

A clean, light, map-first dashboard: white cards on a light grey page, one orange brand accent, and strong red–orange–yellow–green colours used **only** for fire levels.

### Colours

| Role | Hex | Used for |
| --- | --- | --- |
| Page background | #F6F7F9 | Behind all cards |
| Card / surface | #FFFFFF | Cards, top bar, popups |
| Border | #E3E6EA | Card borders, dividers |
| Text | #111827 | Headings, numbers |
| Secondary text | #5B6472 | Labels, notes (passes 4.5:1 on white) |
| Brand accent | #C2410C (light tint #FFF1EB) | Active tab, primary button, harmonized line, selected states |
| Logo flame | #E4572E | Logo only |
| Hotspot dot | #D7301F | Map hotspots |
| Map sea / land (street) | #AAD3DF / #F2EFE9 | OpenStreetMap style |
| VIIRS line / MODIS line | #2563EB / #9CA3AF | Analysis charts |

### Level colours (always shown with the word)

| Level | Fill | Text on it |
| --- | --- | --- |
| Critical (Level 4) | #DC2626 | #FFFFFF |
| High (Level 3) | #F97316 | #1A0F06 |
| Moderate (Level 2) | #FACC15 | #1A1500 |
| Low (Level 1) | #22C55E | #052E16 |

### Calendar ramp (low → extreme)

\#D9F0D3 → #A6DBA0 → #FFE08A → #FDB863 → #F4874B → #E0452E → #A50F15. Lightness falls as activity rises, so the order is readable without colour vision. Unusual months get a 2 px dark outline.

### Typography

| Use | Font | Size / weight |
| --- | --- | --- |
| Logo, page titles, big numbers | Space Grotesk | 19–44 px, 700 |
| Body, labels, buttons | Inter | 12–15 px, 400–600 |
| Coordinates, IDs, counts in tables | JetBrains Mono | 12–13 px |

### Spacing and shape

- Page padding 28 px; gap between cards 16–20 px; card padding 16–20 px.
- Corner radius: cards 12–14 px, buttons 8–10 px, badges 4–6 px.
- Touch targets at least 44 px for map and icon buttons; segmented buttons 32 px tall inside a 38–40 px control.

### Accessibility

- Text contrast at least 4.5:1; colour never carries meaning alone (level words, outlines, numbers).
- Real buttons, links and labelled inputs; icon-only buttons have labels ("Zoom in").
- Wording: computed results are labelled **System**, never "AI".

## Shared top bar

The top bar sits above every page and stays fixed at the top while scrolling (sticky, about 132 px tall). It keeps the user's choices when switching pages.

**Row 1: toolbar**

| Left | Middle | Right |
| --- | --- | --- |
| Flame logo, **EG FireTrack**, "powered by EG Solution 2.0 Team" | Tabs: Map · Calendar · Analysis · Alerts (active tab: orange tint + bold) | **Download CSV** (outline) · **PDF report** (orange, primary; opens the full /report print route: cover + all four pages, A4) |

**Row 2: filters and alerts (one line, wraps on small screens)**

| Control | Options | Behaviour |
| --- | --- | --- |
| Area | Whole Borneo, Sarawak, Sabah, Brunei, West / Central / South / East / North Kalimantan | Filters every number, chart and map |
| Place (town or district) | All places in area, Kuching, Miri, Sibu, Bintulu, Mukah, Kota Kinabalu, Sandakan, Tawau, Bandar Seri Begawan, Pontianak, Ketapang, Palangka Raya, Pulang Pisau, Banjarmasin, Samarinda, Balikpapan, Tarakan, Enter lat, lon… | **Choosing a place sets Area automatically** (Miri → Sarawak); changing Area clears a place outside it |
| Period | Current · 7 days · 30 days · 12 months · 5 years · All (2017–2026) | Segmented control; selected = white chip with shadow |
| Active alerts bar (right) | Critical n · High n · Moderate n · Low n → | Coloured count chips; click opens Alerts |

The selection is also written into the page address, so refreshing or sharing a link reopens the same view.

## Page specs

### 1. Map: where are the fires?

**Layout:** large map on the left (≈ 65% width, 760 px tall); summary column on the right (360–440 px).

- **Map:** Borneo with lat/lon grid lines and labels, rivers, city names, dashed country borders. A note says Borneo is the competition view and the system can run globally.
  - Top left: **Street / Satellite** switch.
  - Top right: zoom in, zoom out, reset view, draw area (44 px buttons).
  - Bottom left: FRP legend (dot size: < 10 MW, 10–50, > 50 MW with outline).
  - Bottom right: cursor lat/lon and map credit.
  - **Hotspot popup** on click: lat/lon, detected time, sensor, FRP, confidence, brightness; close button.
- **Summary · Whole Borneo:** 3 × 2 tiles: Now (last 24 h), This month, This year, Yearly average, Average FRP, Compared to normal (big value "+18%", "3.2×" or ">10×"; small line under it: "vs usual · Unusual"; never overflows the tile).
- **Summary · Selected area:** same 6 tiles with an orange border and warm tint so it reads as "your selection".
- **Hotspot ranking:** title follows the period switch ("Current Time Hotspot Ranking", "This Month Hotspot Ranking", "This Year Hotspot Ranking") with small subtitle "top 5 districts"; two switches (Most / Fewest hotspots; Current / This month / This year); rows with rank badge, district + province, bar, count. Orange for most, green for fewest.

### 2. Calendar: when do fires happen?

**Layout:** heatmap card and yearly bar chart on the left; seasonal summary and selected-year card on the right.

- **Heatmap:** 10 rows (2017–2026) × 12 months + total column; 30 px cells, 4 px gaps; "Usual" median row below a divider; future months of 2026 shown as dashed empty cells.
- **Interactions:** hover a cell for "Sep 2019: 1,612 hotspots (3.2× usual)"; click a year to highlight its row and update the selected-year card.
- **Legend:** green → red ramp, outlined = unusual, dashed = no data yet.
- **Hotspots per year:** 10 bars; record year dark red; 2026 dashed and marked "so far".
- **Seasonal summary:** highlighted fire-season box (e.g. "Aug – Oct", share of yearly hotspots) and 8 fact tiles: record year, quietest year, peak month, quietest month, average per year, 2026 so far vs 2025, unusual months, season strength.
- **Selected year card:** total, vs average year, peak month, unusual months.

### 3. Analysis: past → now → next

**Layout:** trend chart (wide) + trend summary (narrow) on top; rescue risk status band across the page; harmonization check at the bottom.

- **Trend chart:** monthly lines: MODIS raw (grey), VIIRS raw (blue), **harmonized** (thick orange); the future 3 months in a light orange zone with a dotted orange prediction and shaded range; dashed "now" line. Switches: Hotspots / FRP; 12 months / 5 years / 10 years.
- **Trend summary:** 6 rows tagged PAST (grey), NOW (orange), NEXT (red), DATA (blue), each with a bold headline and one explaining line.
- **Prediction · Rescue risk status:** red left border; title "Central Kalimantan: Critical · score 81/100" and a directive; a 4-colour scale bar with a black marker at the score; five tiles: Compared to normal, Chance of spreading, Recent direction, Fuel type, People nearby. Each tile: plain label, big value, technical name, one-line meaning. Button "Open alerts →".
- **Harmonization check:** Jan–Sep totals 2017–2026 for MODIS raw (dashed grey), VIIRS raw (blue), harmonized (orange); fit R² and error; the 5-step method beside it.

### 4. Alerts: what to do, where first

**Layout:** alert detail on the left (wide); status summary and alert list on the right.

- **Right column:** Status summary 2 × 2 tiles (Critical, High, Moderate, Low with counts; click filters; "Show all" button). Active alerts list below: level badge, place, province, coordinates; Critical items show **"P1 · 20% of rescue teams"**, others their risk score.
- **Alert header:** coloured top border; "LEVEL 4 · CRITICAL" badge, alert ID, status; place and province as the title; coordinates and issue time; the level's directive in level colour; one red button **Notify nearby teams**.
- **Four number tiles:** Hotspots in 24 h; Compared to normal (small: vs usual · status); Chance of spreading + word (small: 72-hour system outlook); Rescue priority (Critical, red tint) or Risk score (others).
- **Situation report:** three labelled rows: Situation, Assessment, Recommendation.
- **Why the System expects spreading:** bar rows (input, its value, bar, + / − %) with orange = raises, blue = lowers; last check line.
- **Recommended actions:** table with time badges (0–2 h red, 2–12 h orange, 12–72 h yellow, Daily green), action, reason.
- **Resources to deploy** (name, quantity, arrive within) and **Coordination** (jurisdiction, lead, support, also inform, duty officer, notification channel) side by side.
- Footnote (exact): "Forecasts come from the System's machine-learning model. Recommendations currently follow response rules and are designed to be generated by AI in the full version. The agency in charge makes the final decision."

## Component library

Build these once and reuse them on every page.

| Component | Looks like | States |
| --- | --- | --- |
| Card | White, 1 px #E3E6EA border, 12–14 px radius, 16–20 px padding | default; highlighted (orange border) for "selected area" |
| Stat tile | Grey #F6F7F9 box: small label, big number, small note | normal; red number when above normal, green when below |
| Segmented control | Grey track, white selected chip with shadow | default, selected, hover |
| Level badge | Coloured pill with level word (and "LEVEL n" in headers) | Critical, High, Moderate, Low |
| Status tile (Alerts) | Tinted box: colour square, level word, big count | default; selected (2 px dark border) |
| Alert list item | Badge + place, province + coordinates, right-side priority or score | default; selected (2 px dark border) |
| Ranking row | Rank circle, name + province, bar, count | Most (orange) or Fewest (green) |
| Reason bar | Label, value, bar, signed % | raises (orange), lowers (blue) |
| Time badge | Small coloured pill: 0–2 h, 2–12 h, 12–72 h, Daily | red, orange, yellow, green |
| Scale bar | 4 coloured segments with a marker and labels underneath | marker position = score |
| Map button | 44 px white square, shadow, icon | default, hover, pressed |
| Hotspot dot | Red circle, size by FRP, white ring; large ones dark ring | default; selected (thick dark ring) |
| Popup | White card with shadow, title, close button, label/value grid | open, closed |
| Primary / secondary button | Orange filled / white outlined, 40–48 px tall | default, hover, disabled |

## Interaction and responsive rules

- **Filters:** any change in Area, Place or Period refreshes every card, chart and the map on the current page and stays in place when the user opens another tab.
- **Hover:** calendar cells, bars and chart points show a tooltip with the exact value and its meaning (e.g. "× usual").
- **Selection:** the selected item (hotspot, year, alert, filter tile) always gets a 2–3 px dark outline; only one is selected at a time per list.
- **Loading:** show grey skeleton blocks the size of the final card; never a blank page.
- **Empty results:** a short line in the card, e.g. "No hotspots in Brunei in the last 24 h", plus a suggestion ("Try 7 days").
- **Data notes:** small grey text for "2026 so far", "sample data" or "Borneo view for this competition".
- **Phone width:** the top bar rows wrap; the right-hand column moves under the main content; tables scroll sideways inside their card; the map keeps at least 420 px height.
- **Wording:** plain words first, technical name second and smaller ("Compared to normal" / "vs usual").
