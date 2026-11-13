const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtInt(n: number | null | undefined): string {
  return n === null || n === undefined ? "–" : Math.round(n).toLocaleString("en-US");
}

export function fmtNum(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined ? "–" : n.toFixed(digits);
}

export function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(Math.round(n))}%`;
}

/** Small line under every "Compared to normal" value: "vs usual · Unusual". */
export function vsUsualNote(status: string | null | undefined): string {
  return status ? `vs usual · ${status}` : "vs usual";
}

/** 2.659 -> "2.659° N"; -2.659 -> "2.659° S". */
export function fmtLat(lat: number, digits = 3): string {
  return `${Math.abs(lat).toFixed(digits)}° ${lat >= 0 ? "N" : "S"}`;
}
export function fmtLon(lon: number, digits = 3): string {
  return `${Math.abs(lon).toFixed(digits)}° ${lon >= 0 ? "E" : "W"}`;
}
export function fmtLatLon(lat: number, lon: number, digits = 3): string {
  return `${fmtLat(lat, digits)}, ${fmtLon(lon, digits)}`;
}

/** "2026-11-08 14:24" (MYT text from meta.json) -> "8 Nov 2026, 14:24". */
export function fmtMytText(s: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(s);
  if (!m) return s;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}, ${m[4]}:${m[5]}`;
}

/** A Date shown at a fixed UTC offset (hours) -> "21 Sep 2026, 13:42". */
export function fmtAtOffset(d: Date, offsetH: number): string {
  const x = new Date(d.getTime() + offsetH * 3600_000);
  const hh = String(x.getUTCHours()).padStart(2, "0");
  const mm = String(x.getUTCMinutes()).padStart(2, "0");
  return `${x.getUTCDate()} ${MONTHS[x.getUTCMonth()]} ${x.getUTCFullYear()}, ${hh}:${mm}`;
}

/** UTC offset (h) of MYT, read from meta.json's paired UTC/MYT timestamps. */
export function mytOffsetHours(utc: string, myt: string): number {
  const u = Date.parse(utc);
  const l = Date.parse(myt.replace(" ", "T") + ":00Z");
  return Number.isFinite(u) && Number.isFinite(l) ? Math.round((l - u) / 3600_000) : 0;
}

export function monthName(m: number): string {
  return MONTHS[m - 1] ?? "";
}

/** "Sabah" -> "Sabah"; "Central Kalimantan" -> "C. Kalimantan" (ranking rows). */
export function shortProvince(name: string): string {
  const m = /^(West|Central|South|East|North) Kalimantan$/.exec(name);
  return m ? `${m[1][0]}. Kalimantan` : name;
}
