// Top-bar "Data status": which dot colour and label to show (pure, tested in dataStatus.test.ts).
import type { Meta } from "./types";

export type StatusTone = "green" | "amber" | "red" | "grey";

export interface DataStatus {
  tone: StatusTone;
  /** Hours since the last successful FIRMS fetch, or null if there was none. */
  ageHours: number | null;
}

const DEFAULT_FRESH_HOURS = 26;

/** grey = sample data; red = the last fetch failed (or none ever succeeded);
 *  green = the last good fetch is younger than api_fresh_hours; amber = older. */
export function dataStatus(meta: Meta, now: Date): DataStatus {
  const t = meta.api_last_success ? Date.parse(meta.api_last_success) : NaN;
  const ageHours = Number.isFinite(t) ? (now.getTime() - t) / 3600_000 : null;
  if (meta.is_sample) return { tone: "grey", ageHours };
  if (meta.api_ok === false || ageHours === null) return { tone: "red", ageHours };
  const fresh = meta.api_fresh_hours ?? DEFAULT_FRESH_HOURS;
  return { tone: ageHours < fresh ? "green" : "amber", ageHours };
}
