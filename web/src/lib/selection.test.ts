import { describe, expect, it } from "vitest";
import { selectionDoc } from "./selection";
import type { PlacesDoc } from "./types";

const places = {
  areas: [
    { id: "borneo", name: "Whole Borneo", country: null, bbox: [0, 0, 0, 0] },
    { id: "sarawak", name: "Sarawak", country: "Malaysia", bbox: [0, 0, 0, 0] },
  ],
  places: [{ id: "miri", name: "Miri", area: "sarawak", district: "miri", lat: 4.4, lon: 114 }],
  districts: [],
  custom_point_radius_km: 25,
} as PlacesDoc;

describe("calendar/analysis selection", () => {
  it("area, place and typed point pick the right file", () => {
    expect(selectionDoc({ area: "borneo", place: null, period: "30d" }, places).file).toBe("area/borneo.json");
    expect(selectionDoc({ area: "sarawak", place: null, period: "30d" }, places)).toMatchObject({
      file: "area/sarawak.json",
      name: "Sarawak",
      note: null,
    });
    expect(selectionDoc({ area: "sarawak", place: "miri", period: "30d" }, places)).toMatchObject({
      file: "area/miri.json",
      name: "Miri",
    });
    const pt = selectionDoc({ area: "sarawak", place: "3.1000,113.0000", period: "30d" }, places);
    expect(pt.file).toBe("area/sarawak.json");
    expect(pt.note).toContain("3.10° N");
  });
  it("unknown area falls back to Whole Borneo", () => {
    expect(selectionDoc({ area: "nowhere", place: null, period: "30d" }, places).file).toBe("area/borneo.json");
  });
});
