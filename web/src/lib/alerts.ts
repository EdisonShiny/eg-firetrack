// Pure helpers for the Alerts page (tested in alerts.test.ts).
import { ALL_AREAS, type Filters } from "../store/filters";
import { fmtAtOffset } from "./format";
import type { AlertRecord, LevelCounts, PlacesDoc } from "./types";

/** Alerts inside the current Area / Place: preset place = its district; typed point or no place = the Area. */
export function alertsInSelection(alerts: AlertRecord[], f: Filters, places: PlacesDoc): AlertRecord[] {
  const preset = f.place ? places.places.find((p) => p.id === f.place) : undefined;
  if (preset) {
    const d = places.districts.find((x) => x.id === preset.district);
    return alerts.filter((a) => a.area === preset.area && (!d || a.district === d.name));
  }
  if (f.area === ALL_AREAS) return alerts;
  return alerts.filter((a) => a.area === f.area);
}

export function levelKey(name: string): keyof LevelCounts {
  return name.toLowerCase() as keyof LevelCounts;
}

export function countLevels(alerts: AlertRecord[]): LevelCounts {
  const c: LevelCounts = { critical: 0, high: 0, moderate: 0, low: 0 };
  for (const a of alerts) c[levelKey(a.level_name)] += 1;
  return c;
}

/** Order of the list: level (highest first), then rescue priority rank, then risk score. */
export function sortAlerts(alerts: AlertRecord[]): AlertRecord[] {
  return [...alerts].sort(
    (a, b) => b.level - a.level || (a.priority?.rank ?? 999) - (b.priority?.rank ?? 999) || b.score - a.score,
  );
}

/** "P1 · 20%" for Critical alerts; "Score 56" otherwise. */
export function priorityLabel(a: AlertRecord): { main: string; sub: string } {
  if (a.priority) return { main: `P${a.priority.rank} · ${a.priority.share_pct}%`, sub: "of rescue teams" };
  return { main: `Score ${a.score}`, sub: "risk score" };
}

/** Full text used in headers and exports: "P1 · 20% of rescue teams". */
export function priorityText(a: AlertRecord): string | null {
  return a.priority ? `P${a.priority.rank} · ${a.priority.share_pct}% of rescue teams` : null;
}

/** Local time zone label: Malaysia / Brunei = MYT; Indonesia UTC+7 = WIB, UTC+8 = WITA. */
export function tzLabel(country: string, offsetH: number): string {
  if (country === "Indonesia") return offsetH === 7 ? "WIB" : offsetH === 8 ? "WITA" : `UTC+${offsetH}`;
  return offsetH === 8 ? "MYT" : `UTC+${offsetH}`;
}

export function issuedText(a: AlertRecord): string {
  return `${fmtAtOffset(new Date(a.issued_utc), a.utc_offset_h)} ${tzLabel(a.country, a.utc_offset_h)}`;
}

/** "0-2 h" -> "0–2 h" plus its colour class (red / orange / yellow / green). */
export function timeBadge(when: string): { text: string; tone: "t0" | "t1" | "t2" | "t3" } {
  const text = when.replace(/(\d)-(\d)/, "$1–$2");
  const tone = when.startsWith("0-") ? "t0" : when.startsWith("2-") ? "t1" : when.startsWith("12-") ? "t2" : "t3";
  return { text, tone };
}

/** Reason bars: width in % of the largest effect; sign decides raise (orange) / lower (blue). */
export function reasonBars(reasons: { effect_pp: number }[]): { width: number; raises: boolean; text: string }[] {
  const max = Math.max(1e-9, ...reasons.map((r) => Math.abs(r.effect_pp)));
  return reasons.map((r) => {
    const v = Math.round(r.effect_pp);
    return {
      width: Math.max(2, (Math.abs(r.effect_pp) / max) * 100),
      raises: r.effect_pp >= 0,
      text: `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v)}%`,
    };
  });
}

export function growthText(a: AlertRecord): string {
  if (a.is_new) return "new since yesterday";
  const g = Math.round(a.growth_pct);
  return `${g > 0 ? "+" : g < 0 ? "−" : ""}${Math.abs(g)}% vs yesterday`;
}

/** "Last check: yesterday the System gave 42% → 4 hotspots observed today ✗ missed". */
export function lastCheckText(a: AlertRecord, words?: Record<string, string>): string {
  const w = words?.[a.last_check.result] ?? a.last_check.result.replace("_", " ");
  const saw = a.last_check.saw_new
    ? `${fmtCount(a.hotspots_24h)} hotspot${a.hotspots_24h === 1 ? "" : "s"} observed today`
    : "no new hotspots today";
  return `Last check: yesterday the System gave ${Math.round(a.last_check.said_24h_pct)}% (next 24 h) → ${saw} ${w}`;
}

function fmtCount(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

/** Rows for the Alerts CSV download. */
export function alertsCsvRows(alerts: AlertRecord[]): (string | number | null)[][] {
  const head = [
    "id", "level", "level_name", "status", "place", "district", "province", "country", "lat", "lon", "issued_utc",
    "hotspots_24h", "growth_pct", "compared_to_normal_pct", "chance_72h_pct", "chance_word", "risk_score",
    "rescue_priority", "team_share_pct", "lead_agency", "support", "also_inform", "nearest_town", "town_km",
    "fuel", "situation", "assessment", "recommendation",
  ];
  return [
    head,
    ...alerts.map((a) => [
      a.id, a.level, a.level_name, a.status, a.place, a.district, a.province, a.country, a.lat, a.lon, a.issued_utc,
      a.hotspots_24h, a.growth_pct, a.anomaly_pct, a.chance_72h_pct, a.chance_word, a.score,
      a.priority ? `P${a.priority.rank}` : null, a.priority?.share_pct ?? null, a.coordination.lead,
      a.coordination.support, a.coordination.also_inform.join("; "), a.town.name, a.town.km, a.fuel,
      a.report.situation, a.report.assessment, a.report.recommendation,
    ]),
  ];
}
