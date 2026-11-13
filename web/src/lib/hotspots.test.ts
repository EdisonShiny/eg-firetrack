import { describe, expect, it } from "vitest";
import { frpClass, pointsPeriod, selectPoints } from "./hotspots";
import type { Hotspots, Meta, Place } from "./types";

const meta = {
  data_through_utc: "2026-11-08T00:00:00Z",
  periods_days: { current: 1, "7d": 7, "30d": 30, "12m": 365, "5y": 1826 },
} as unknown as Meta;

// base 2026-10-09 00:00 UTC; t in minutes
const day = 1440;
const h = {
  days: 30,
  base_time_utc: "2026-10-09T00:00:00Z",
  areas: ["sarawak", "sabah"],
  districts: ["miri", "kuching", "sandakan"],
  lat: [4.4, 1.55, 5.84, 4.41],
  lon: [114.0, 110.36, 118.1, 114.0],
  t: [29.5 * day, 25 * day, 20 * day, 5 * day],
  area: [0, 0, 1, 0],
  district: [0, 1, 2, 0],
} as unknown as Hotspots;
const places = [{ id: "miri", area: "sarawak", district: "miri" }] as Place[];

describe("selectPoints", () => {
  it("filters by period window ending at the latest data", () => {
    expect(selectPoints(h, { area: "borneo", place: null, period: "current" }, meta, places, 25)).toEqual([0]);
    expect(selectPoints(h, { area: "borneo", place: null, period: "7d" }, meta, places, 25)).toEqual([0, 1]);
    expect(selectPoints(h, { area: "borneo", place: null, period: "30d" }, meta, places, 25)).toEqual([0, 1, 2, 3]);
  });
  it("filters by area and by the place's district", () => {
    expect(selectPoints(h, { area: "sabah", place: null, period: "30d" }, meta, places, 25)).toEqual([2]);
    expect(selectPoints(h, { area: "sarawak", place: "miri", period: "30d" }, meta, places, 25)).toEqual([0, 3]);
  });
  it("a typed point keeps hotspots within the radius", () => {
    expect(selectPoints(h, { area: "sarawak", place: "1.6,110.4", period: "30d" }, meta, places, 25)).toEqual([1]);
  });
});

describe("helpers", () => {
  it("raw points only for windows up to 30 days", () => {
    expect(pointsPeriod("30d", meta, 30)).toBe(true);
    expect(pointsPeriod("12m", meta, 30)).toBe(false);
    expect(pointsPeriod("all", meta, 30)).toBe(false);
  });
  it("FRP dot classes use the band edges", () => {
    const s = { small_below: 10, large_above: 50 };
    expect([frpClass(9.9, s), frpClass(10, s), frpClass(50, s), frpClass(50.1, s)]).toEqual([0, 1, 1, 2]);
  });
});
