// "Download CSV": built in the browser from the same JSON the page shows, for the current
// Area / Place / Period. Excel-friendly: UTF-8 with BOM, CRLF line ends, quoted fields.
import { type Filters } from "../store/filters";
import { alertsCsvRows, alertsInSelection, sortAlerts } from "./alerts";
import { loadJSON } from "./data";
import { gridFile, pointsPeriod, selectCells, selectPoints } from "./hotspots";
import { selectionDoc } from "./selection";
import type { AreaDoc, Alerts, Grid, Hotspots, Meta, PlacesDoc } from "./types";

export type Cell = string | number | boolean | null | undefined;

export function csvField(v: Cell): string {
  if (v === null || v === undefined) return "";
  const s = typeof v === "number" ? (Number.isFinite(v) ? String(v) : "") : String(v);
  // Quote when needed; a leading = + - @ is prefixed with ' so Excel never runs it as a formula.
  const safe = /^[=+\-@]/.test(s) && typeof v !== "number" ? `'${s}` : s;
  return /[",\r\n;]/.test(safe) || safe !== s ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function toCsv(rows: Cell[][]): string {
  return "﻿" + rows.map((r) => r.map(csvField).join(",")).join("\r\n") + "\r\n";
}

export function csvFileName(page: string, f: Filters, day: string): string {
  const where = (f.place ?? f.area).replace(/[^a-z0-9.-]+/gi, "_");
  return `eg-firetrack-${page}-${where}-${f.period}-${day}.csv`;
}

export type PageKind = "map" | "calendar" | "analysis" | "alerts";

export function pageOf(pathname: string): PageKind {
  if (pathname.startsWith("/calendar")) return "calendar";
  if (pathname.startsWith("/analysis")) return "analysis";
  if (pathname.startsWith("/alerts")) return "alerts";
  return "map";
}

/** Hotspot rows (raw points for periods <= 30 days, else 0.1° grid cells). */
export function hotspotRows(h: Hotspots, idx: number[]): Cell[][] {
  const base = Date.parse(h.base_time_utc);
  return [
    ["lat", "lon", "detected_utc", "satellite", "sensor", "frp_mw", "confidence", "brightness_k", "area", "district"],
    ...idx.map((i) => {
      const sat = h.satellites[h.sat[i]];
      return [
        h.lat[i], h.lon[i], new Date(base + h.t[i] * 60_000).toISOString().slice(0, 16).replace("T", " "),
        sat, h.sensor_of_satellite[sat], h.frp[i], h.confidence[h.conf[i]], h.bright[i],
        h.areas[h.area[i]], h.districts[h.district[i]] ?? "",
      ];
    }),
  ];
}

export function gridRows(g: Grid, idx: number[]): Cell[][] {
  return [
    ["cell_lat", "cell_lon", "cell_deg", "harmonized_hotspots", "frp_mean_mw", "area", "district"],
    ...idx.map((i) => [g.lat[i], g.lon[i], g.cell_deg, g.count[i], g.frp[i], g.areas[g.area[i]], g.districts[g.district[i]] ?? ""]),
  ];
}

/** Monthly series of one area file (Calendar / Analysis). */
export function monthlyRows(doc: AreaDoc): Cell[][] {
  const a = doc.analysis;
  const s = a.series;
  const rows: Cell[][] = [
    ["area", "month", "modis_raw", "viirs_raw", "harmonized", "harmonized_frp_mean_mw", "note"],
  ];
  a.months.forEach((m, i) =>
    rows.push([doc.name, m, s.modis_raw.count[i], s.viirs_raw.count[i], s.harmonized.count[i], s.harmonized.frp[i],
      i === a.now_index ? "so far" : ""]),
  );
  for (const p of a.prediction.count) rows.push([doc.name, p.month, null, null, p.value, null, `prediction (${p.low}–${p.high})`]);
  return rows;
}

/** Builds the CSV for the page the user is on. */
export async function buildCsv(page: PageKind, f: Filters, meta: Meta, places: PlacesDoc): Promise<string> {
  if (page === "alerts") {
    const doc = await loadJSON<Alerts>("alerts.json");
    return toCsv(alertsCsvRows(sortAlerts(alertsInSelection(doc.alerts ?? [], f, places))));
  }
  if (page === "calendar" || page === "analysis") {
    const doc = await loadJSON<AreaDoc>(selectionDoc(f, places).file);
    return toCsv(monthlyRows(doc));
  }
  const radius = places.custom_point_radius_km;
  const h = await loadJSON<Hotspots>("hotspots_30d.json");
  if (pointsPeriod(f.period, meta, h.days)) {
    return toCsv(hotspotRows(h, selectPoints(h, f, meta, places.places, radius)));
  }
  const g = await loadJSON<Grid>(gridFile(f.period));
  return toCsv(gridRows(g, selectCells(g, f, places.places, radius)));
}

/** Hands the text to the browser as a file download. */
export function saveText(text: string, name: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
