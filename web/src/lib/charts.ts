// Pure helpers behind the Calendar and Analysis charts (tested in charts.test.ts).
import type { Period } from "../store/filters";
import { fmtInt, monthName } from "./format";
import type { AnalysisData, CalendarCell, SeriesData } from "./types";

/** "2019-09" -> "Sep 2019". */
export function monthLabel(ym: string): string {
  const m = /^(\d{4})-(\d{2})/.exec(ym);
  return m ? `${monthName(Number(m[2]))} ${m[1]}` : ym;
}

/** 3.237 -> "3.2×". */
export function fmtRatio(r: number): string {
  return `${r.toFixed(1)}×`;
}

/** Calendar hover text, e.g. "Sep 2019: 1,612 hotspots (3.2× usual)". month = 1..12. */
export function cellTooltip(month: number, year: number, cell: CalendarCell | null): string {
  const when = `${monthName(month)} ${year}`;
  if (!cell) return `${when}: no data yet`;
  const n = `${fmtInt(cell.count)} ${cell.count === 1 ? "hotspot" : "hotspots"}`;
  const vs = cell.ratio === null ? "usual is 0" : `${fmtRatio(cell.ratio)} usual`;
  const flag = cell.unusual ? " · unusual month" : "";
  return `${when}${cell.partial ? " so far" : ""}: ${n} (${vs})${flag}`;
}

export type TrendWindow = "12m" | "5y" | "10y";
export type TrendMetric = "count" | "frp";
export const TREND_MONTHS: Record<TrendWindow, number> = { "12m": 12, "5y": 60, "10y": 120 };

/** The top-bar Period picks the first trend window; short periods start on 5 years (as in analysis.png). */
export function windowForPeriod(p: Period): TrendWindow {
  return p === "12m" ? "12m" : p === "all" ? "10y" : "5y";
}

export interface TrendView {
  /** "YYYY-MM" labels: the window, then the predicted months. */
  months: string[];
  /** Index of the current month ("now") in months. */
  now: number;
  modis: (number | null)[];
  viirs: (number | null)[];
  harmonized: (number | null)[];
  /** Dotted line: starts at the now value, then the predicted values. */
  prediction: (number | null)[];
  /** Likely range as a stacked band: low, then (high - low). */
  low: (number | null)[];
  band: (number | null)[];
}

/** Slice the monthly series to the window ending now and append the 3-month prediction. */
export function trendView(a: AnalysisData, win: TrendWindow, metric: TrendMetric): TrendView {
  const end = a.now_index;
  const start = Math.max(0, end + 1 - TREND_MONTHS[win]);
  const pred = a.prediction[metric];
  const pad: null[] = pred.map(() => null);
  const take = (s: SeriesData): (number | null)[] => [...s[metric].slice(start, end + 1), ...pad];
  const harmonized = take(a.series.harmonized);
  const now = end - start;
  const nowVal = harmonized[now] ?? null;
  const lead = (v: number | null): (number | null)[] => [...Array<number | null>(now).fill(null), v];
  return {
    months: [...a.months.slice(start, end + 1), ...pred.map((p) => p.month)],
    now,
    modis: take(a.series.modis_raw),
    viirs: take(a.series.viirs_raw),
    harmonized,
    prediction: [...lead(nowVal), ...pred.map((p) => p.value)],
    low: [...lead(nowVal), ...pred.map((p) => p.low)],
    band: [...lead(nowVal === null ? null : 0), ...pred.map((p) => +(p.high - p.low).toFixed(2))],
  };
}
