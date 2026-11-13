# data/sample/
**Synthetic, illustrative data, not real detections.** Used only when no FIRMS archive is in
`data/raw/firms/` or FIRMS is unreachable; the site then shows a "sample data" badge.

- `firms/fire_archive_M-C61_sample.csv.gz`: MODIS C6.1 (Terra + Aqua), FIRMS archive columns
- `firms/fire_archive_SV-C2_sample.csv.gz`: VIIRS S-NPP 375 m (ends 2 Nov 2026)
- `firms/fire_archive_J1V-C2_sample.csv.gz`: VIIRS NOAA-20 375 m (from Apr 2018)

Covers 1 Jan 2017 to 8 Nov 2026 for the Borneo box. Fires cluster in peat districts, the season
peaks Aug-Oct, and 2019 and 2023 (El Niño) are large. Includes a few static sources and
low-confidence rows that cleaning removes.

Regenerate (fixed seed, needs data/processed/boundaries.geojson): `python -m pipeline.make_sample`
