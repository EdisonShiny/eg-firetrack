import type { Boundaries, BoundaryFeature } from "./types";

function inRing(lat: number, lon: number, ring: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function inPolygon(lat: number, lon: number, rings: number[][][]): boolean {
  if (!inRing(lat, lon, rings[0])) return false;
  for (let i = 1; i < rings.length; i++) if (inRing(lat, lon, rings[i])) return false;
  return true;
}

export function inFeature(lat: number, lon: number, f: BoundaryFeature): boolean {
  const g = f.geometry;
  return g.type === "Polygon" ? inPolygon(lat, lon, g.coordinates) : g.coordinates.some((p) => inPolygon(lat, lon, p));
}

/** First boundary feature of the given level that contains the point. */
export function featureAt(b: Boundaries, lat: number, lon: number, level: "province" | "district") {
  return b.features.find((f) => f.properties.level === level && inFeature(lat, lon, f)) ?? null;
}

/** Point-in-polygon for an arbitrary [lat, lon] ring (used for a drawn area). */
export function inLatLngRing(lat: number, lon: number, ring: [number, number][]): boolean {
  return inRing(lat, lon, ring.map(([la, lo]) => [lo, la]));
}

export function distanceKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const r = Math.PI / 180;
  const a =
    Math.sin(((lat2 - lat1) * r) / 2) ** 2 +
    Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(((lon2 - lon1) * r) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}
