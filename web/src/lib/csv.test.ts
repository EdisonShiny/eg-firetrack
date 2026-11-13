import { describe, expect, it } from "vitest";
import { alertsCsvRows } from "./alerts";
import { alert } from "./fixtures";
import { csvField, csvFileName, hotspotRows, pageOf, toCsv } from "./csv";
import { DEFAULT_FILTERS } from "../store/filters";
import type { Hotspots } from "./types";

describe("csv", () => {
  it("quotes only when needed and escapes quotes", () => {
    expect(csvField("Kapuas")).toBe("Kapuas");
    expect(csvField("Kapuas, Central Kalimantan")).toBe('"Kapuas, Central Kalimantan"');
    expect(csvField('say "hi"')).toBe('"say ""hi"""');
    expect(csvField("a\nb")).toBe('"a\nb"');
    expect(csvField(null)).toBe("");
    expect(csvField(-2.35)).toBe("-2.35");
  });

  it("never lets Excel run a formula", () => {
    expect(csvField("=HYPERLINK(1)")).toBe(`"'=HYPERLINK(1)"`);
    expect(csvField("+48%")).toBe(`"'+48%"`);
  });

  it("is Excel friendly: BOM + CRLF", () => {
    const t = toCsv([["a", "b"], [1, 2]]);
    expect(t.startsWith("﻿")).toBe(true);
    expect(t).toBe("﻿a,b\r\n1,2\r\n");
  });

  it("file names and page detection", () => {
    expect(csvFileName("map", { ...DEFAULT_FILTERS, area: "sarawak" }, "2026-11-08")).toBe(
      "eg-firetrack-map-sarawak-30d-2026-11-08.csv",
    );
    expect(csvFileName("map", { ...DEFAULT_FILTERS, place: "1.5500,110.3600" }, "d")).toBe(
      "eg-firetrack-map-1.5500_110.3600-30d-d.csv",
    );
    expect(pageOf("/alerts")).toBe("alerts");
    expect(pageOf("/calendar")).toBe("calendar");
    expect(pageOf("/")).toBe("map");
  });

  it("alerts rows carry P-rank and share for Critical", () => {
    const rows = alertsCsvRows([alert(), alert({ id: "x", level: 3, level_name: "High", priority: null })]);
    const h = rows[0];
    expect(rows[1][h.indexOf("rescue_priority")]).toBe("P1");
    expect(rows[1][h.indexOf("team_share_pct")]).toBe(20);
    expect(rows[2][h.indexOf("rescue_priority")]).toBeNull();
    expect(rows.every((r) => r.length === h.length)).toBe(true);
  });

  it("hotspot rows decode the columnar file", () => {
    const h = {
      base_time_utc: "2026-11-01T00:00:00Z", satellites: ["NOAA-20"], sensor_of_satellite: { "NOAA-20": "VIIRS" },
      confidence: ["nominal", "high"], areas: ["sarawak"], districts: ["miri"],
      lat: [4.4], lon: [114], t: [90], sat: [0], frp: [12.5], conf: [1], bright: [330], area: [0], district: [0],
    } as unknown as Hotspots;
    const rows = hotspotRows(h, [0]);
    expect(rows[1]).toEqual([4.4, 114, "2026-11-01 01:30", "NOAA-20", "VIIRS", 12.5, "high", 330, "sarawak", "miri"]);
  });
});
