// Area / Place / Period: one shared store, mirrored in the URL (?area=&place=&period=).
// The pure functions below hold every rule (tested in filters.test.ts); the hook at the bottom
// only wires them to React and window.history.
import { useSyncExternalStore } from "react";

export type Period = "current" | "7d" | "30d" | "12m" | "5y" | "all";
export const PERIOD_IDS: Period[] = ["current", "7d", "30d", "12m", "5y", "all"];

export interface Filters {
  area: string; // area id, "borneo" = Whole Borneo
  place: string | null; // preset place id, "lat,lon" for a typed point, or null = all places in area
  period: Period;
}

export interface PlaceRef {
  id: string;
  area: string;
}

export interface FilterContext {
  areas: string[];
  places: PlaceRef[];
  /** Area id that contains a typed point, or null if the point is outside every area. */
  areaOfPoint?: (lat: number, lon: number) => string | null;
}

export const ALL_AREAS = "borneo";
export const DEFAULT_FILTERS: Filters = { area: ALL_AREAS, place: null, period: "30d" };

const POINT_RE = /^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/;

/** "1.55, 110.36" -> {lat, lon}; null if not a valid lat/lon pair. */
export function parsePoint(text: string | null | undefined): { lat: number; lon: number } | null {
  if (!text) return null;
  const m = POINT_RE.exec(text);
  if (!m) return null;
  const lat = Number(m[1]);
  const lon = Number(m[2]);
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}

export function formatPoint(lat: number, lon: number): string {
  return `${lat.toFixed(4)},${lon.toFixed(4)}`;
}

/** The area a place belongs to (preset or typed point), or null if unknown. */
export function areaOfPlace(place: string, ctx: FilterContext): string | null {
  const preset = ctx.places.find((p) => p.id === place);
  if (preset) return preset.area;
  const pt = parsePoint(place);
  if (pt && ctx.areaOfPoint) return ctx.areaOfPoint(pt.lat, pt.lon);
  return null;
}

/** Choosing a Place sets its Area automatically (Miri -> Sarawak). null = "All places in area". */
export function choosePlace(f: Filters, place: string | null, ctx: FilterContext): Filters {
  if (place === null) return { ...f, place: null };
  const pt = parsePoint(place);
  const id = pt ? formatPoint(pt.lat, pt.lon) : place;
  const area = areaOfPlace(id, ctx);
  if (!area) return f; // unknown place or point outside Borneo: ignore
  return { ...f, place: id, area };
}

/** Changing Area clears a Place outside it. Whole Borneo clears the place (it means "everything"). */
export function chooseArea(f: Filters, area: string, ctx: FilterContext): Filters {
  if (!ctx.areas.includes(area)) return f;
  const keep = f.place !== null && area !== ALL_AREAS && areaOfPlace(f.place, ctx) === area;
  return { ...f, area, place: keep ? f.place : null };
}

export function choosePeriod(f: Filters, period: Period): Filters {
  return PERIOD_IDS.includes(period) ? { ...f, period } : f;
}

/** Read filters from a query string; unknown values fall back to defaults, and a place forces its area. */
export function parseFilters(search: string, ctx: FilterContext): Filters {
  const q = new URLSearchParams(search);
  let f: Filters = { ...DEFAULT_FILTERS };
  const period = q.get("period") as Period | null;
  if (period) f = choosePeriod(f, period);
  const area = q.get("area");
  if (area) f = chooseArea(f, area, ctx);
  const place = q.get("place");
  if (place) f = choosePlace(f, place, ctx);
  return f;
}

/** Filters -> "?area=…&place=…&period=…" (place left out when null). */
export function serializeFilters(f: Filters): string {
  const q = new URLSearchParams();
  q.set("area", f.area);
  if (f.place) q.set("place", f.place);
  q.set("period", f.period);
  return "?" + q.toString().replace(/%2C/gi, ",");
}

// ---------------------------------------------------------------- React store

let state: Filters = { ...DEFAULT_FILTERS };
let context: FilterContext | null = null;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

function writeUrl(f: Filters) {
  if (typeof window === "undefined") return;
  const next = serializeFilters(f);
  if (window.location.search !== next) {
    window.history.replaceState(window.history.state, "", window.location.pathname + next + window.location.hash);
  }
}

function set(next: Filters) {
  if (next.area === state.area && next.place === state.place && next.period === state.period) return;
  state = next;
  writeUrl(state);
  emit();
}

/** Called once places.json (and boundaries) are loaded: reads the URL and starts syncing. */
export function initFilters(ctx: FilterContext) {
  context = ctx;
  state = parseFilters(window.location.search, ctx);
  writeUrl(state);
  emit();
}

if (typeof window !== "undefined") {
  window.addEventListener("popstate", () => {
    if (!context) return;
    state = parseFilters(window.location.search, context);
    emit();
  });
}

export const filterActions = {
  setArea: (area: string) => context && set(chooseArea(state, area, context)),
  setPlace: (place: string | null) => context && set(choosePlace(state, place, context)),
  setPeriod: (period: Period) => set(choosePeriod(state, period)),
  /** For callers that need to know whether a typed point was accepted. */
  tryPlace: (place: string): boolean => {
    if (!context) return false;
    const next = choosePlace(state, place, context);
    if (next === state) return false;
    set(next);
    return true;
  },
};

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useFilters(): Filters {
  return useSyncExternalStore(subscribe, () => state, () => state);
}
