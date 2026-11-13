import { describe, expect, it } from "vitest";
import { fmtLatLon, fmtMytText, fmtPct, mytOffsetHours, shortProvince, vsUsualNote } from "./format";
import { distanceKm, inLatLngRing } from "./geo";

describe("format", () => {
  it("formats coordinates like the popup", () => {
    expect(fmtLatLon(-2.659, 114.202)).toBe("2.659° S, 114.202° E");
  });
  it("signs percentages", () => {
    expect(fmtPct(111)).toBe("+111%");
    expect(fmtPct(-46)).toBe("−46%");
    expect(fmtPct(null)).toBe("–");
  });
  it("writes the compared-to-normal small line", () => {
    expect(vsUsualNote("Unusual")).toBe("vs usual · Unusual");
    expect(vsUsualNote(null)).toBe("vs usual");
  });
  it("reads the MYT offset from meta.json", () => {
    expect(mytOffsetHours("2026-11-08T06:24:00Z", "2026-11-08 14:24")).toBe(8);
    expect(fmtMytText("2026-09-21 13:42")).toBe("21 Sep 2026, 13:42");
  });
  it("shortens Kalimantan provinces", () => {
    expect(shortProvince("Central Kalimantan")).toBe("C. Kalimantan");
    expect(shortProvince("Sarawak")).toBe("Sarawak");
  });
});

describe("geo", () => {
  it("measures distance in km", () => {
    expect(distanceKm(0, 110, 0, 111)).toBeCloseTo(111.2, 0);
  });
  it("tests a drawn ring", () => {
    const ring: [number, number][] = [[0, 0], [0, 2], [2, 2], [2, 0]];
    expect(inLatLngRing(1, 1, ring)).toBe(true);
    expect(inLatLngRing(3, 1, ring)).toBe(false);
  });
});
