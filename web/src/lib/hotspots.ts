// Which map dots to draw for the current Area / Place / Period (pure, tested).
import { ALL_AREAS, type Filters, parsePoint } from "../store/filters";
import { distanceKm } from "./geo";
import type { Grid, Hotspots, Meta, Place } from "./types";

/** Periods with raw points (hotspots_30d.json); longer ones use the 0.1° grids. */
export function pointsPeriod(period: Filters["period"], meta: Meta, pointsDays: number): boolean {
  const d = meta.periods_days[period];
  return d !== undefined && d <= pointsDays;
}

export function gridFile(period: Filters["period"]): string {
  return period === "all" ? "grid_all.json" : period === "5y" ? "grid_5y.json" : "grid_12m.json";
}

interface Scope {
  areaIdx: number | null; // index into doc.areas, null = every area
  districtIdx: number | null; // preset place = its district
  point: { lat: number; lon: number } | null; // typed point
}

function scopeOf(doc: { areas: string[]; districts: string[] }, f: Filters, places: Place[]): Scope {
  const areaIdx = f.area === ALL_AREAS ? null : doc.areas.indexOf(f.area);
  const preset = f.place ? places.find((p) => p.id === f.place) : undefined;
  const districtIdx = preset ? doc.districts.indexOf(preset.district) : null;
  const point = !preset && f.place ? parsePoint(f.place) : null;
  return { areaIdx, districtIdx, point };
}

function inScope(s: Scope, area: number, district: number, lat: number, lon: number, radiusKm: number) {
  if (s.areaIdx !== null && area !== s.areaIdx) return false;
  if (s.districtIdx !== null && district !== s.districtIdx) return false;
  if (s.point && distanceKm(s.point.lat, s.point.lon, lat, lon) > radiusKm) return false;
  return true;
}

/** Indices of hotspots inside the selection and the period window (ending at the latest data). */
export function selectPoints(h: Hotspots, f: Filters, meta: Meta, places: Place[], radiusKm: number): number[] {
  const days = meta.periods_days[f.period] ?? h.days;
  const base = Date.parse(h.base_time_utc);
  const through = Date.parse(meta.data_through_utc);
  const minT = (through - base) / 60_000 - days * 1440;
  const s = scopeOf(h, f, places);
  const out: number[] = [];
  for (let i = 0; i < h.lat.length; i++) {
    if (h.t[i] < minT) continue;
    if (inScope(s, h.area[i], h.district[i], h.lat[i], h.lon[i], radiusKm)) out.push(i);
  }
  return out;
}

/** Indices of grid cells inside the selection. */
export function selectCells(g: Grid, f: Filters, places: Place[], radiusKm: number): number[] {
  const s = scopeOf(g, f, places);
  const out: number[] = [];
  for (let i = 0; i < g.lat.length; i++) {
    if (inScope(s, g.area[i], g.district[i], g.lat[i], g.lon[i], radiusKm)) out.push(i);
  }
  return out;
}

/** Dot radius (px) by FRP class: < small, small–large, > large (bands.json frp_dot_sizes_mw). */
export function frpClass(frp: number, sizes: { small_below: number; large_above: number }): 0 | 1 | 2 {
  return frp < sizes.small_below ? 0 : frp > sizes.large_above ? 2 : 1;
}
