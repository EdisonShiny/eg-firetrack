import { describe, expect, it } from "vitest";
import {
  DEFAULT_FILTERS,
  type FilterContext,
  chooseArea,
  choosePeriod,
  choosePlace,
  parseFilters,
  parsePoint,
  serializeFilters,
} from "./filters";

const ctx: FilterContext = {
  areas: ["borneo", "sarawak", "sabah", "brunei", "central-kalimantan"],
  places: [
    { id: "miri", area: "sarawak" },
    { id: "kuching", area: "sarawak" },
    { id: "kota-kinabalu", area: "sabah" },
    { id: "palangka-raya", area: "central-kalimantan" },
  ],
  // crude test boxes instead of real borders
  areaOfPoint: (lat, lon) => (lat > 0.8 && lat < 5 && lon < 115 ? "sarawak" : lat > 5 ? "sabah" : null),
};

describe("Place -> Area", () => {
  it("choosing Miri sets Area to Sarawak", () => {
    const f = choosePlace(DEFAULT_FILTERS, "miri", ctx);
    expect(f).toEqual({ area: "sarawak", place: "miri", period: "30d" });
  });

  it("choosing a place in another area moves the area", () => {
    const f = choosePlace({ area: "sarawak", place: "miri", period: "7d" }, "kota-kinabalu", ctx);
    expect(f.area).toBe("sabah");
    expect(f.period).toBe("7d");
  });

  it("a typed lat, lon sets the area that contains it", () => {
    const f = choosePlace(DEFAULT_FILTERS, " 1.5535 , 110.3593 ", ctx);
    expect(f.place).toBe("1.5535,110.3593");
    expect(f.area).toBe("sarawak");
  });

  it("an unknown place or a point outside Borneo is ignored", () => {
    expect(choosePlace(DEFAULT_FILTERS, "atlantis", ctx)).toBe(DEFAULT_FILTERS);
    expect(choosePlace(DEFAULT_FILTERS, "-40,10", ctx)).toBe(DEFAULT_FILTERS);
  });

  it("All places in area keeps the area", () => {
    const f = choosePlace({ area: "sarawak", place: "miri", period: "30d" }, null, ctx);
    expect(f).toEqual({ area: "sarawak", place: null, period: "30d" });
  });
});

describe("changing Area", () => {
  const miri = { area: "sarawak", place: "miri", period: "30d" as const };

  it("clears a place outside the new area", () => {
    expect(chooseArea(miri, "sabah", ctx)).toEqual({ area: "sabah", place: null, period: "30d" });
  });

  it("keeps a place inside the area", () => {
    expect(chooseArea(miri, "sarawak", ctx).place).toBe("miri");
  });

  it("Whole Borneo clears the place", () => {
    expect(chooseArea(miri, "borneo", ctx).place).toBeNull();
  });

  it("clears a typed point outside the new area", () => {
    const pt = choosePlace(DEFAULT_FILTERS, "1.55,110.36", ctx);
    expect(chooseArea(pt, "sabah", ctx).place).toBeNull();
  });

  it("ignores an unknown area", () => {
    expect(chooseArea(miri, "mars", ctx)).toBe(miri);
  });
});

describe("URL", () => {
  it("round-trips through the query string", () => {
    const f = { area: "sarawak", place: "miri", period: "12m" as const };
    expect(serializeFilters(f)).toBe("?area=sarawak&place=miri&period=12m");
    expect(parseFilters(serializeFilters(f), ctx)).toEqual(f);
  });

  it("a place in the URL wins over a wrong area", () => {
    expect(parseFilters("?area=sabah&place=miri&period=7d", ctx)).toEqual({
      area: "sarawak",
      place: "miri",
      period: "7d",
    });
  });

  it("bad values fall back to defaults", () => {
    expect(parseFilters("?area=mars&place=nowhere&period=1h", ctx)).toEqual(DEFAULT_FILTERS);
    expect(parseFilters("", ctx)).toEqual(DEFAULT_FILTERS);
  });

  it("keeps a typed point readable", () => {
    const f = choosePlace(DEFAULT_FILTERS, "1.55,110.36", ctx);
    expect(serializeFilters(f)).toBe("?area=sarawak&place=1.5500,110.3600&period=30d");
    expect(parseFilters(serializeFilters(f), ctx)).toEqual(f);
  });

  it("period only accepts known ids", () => {
    expect(choosePeriod(DEFAULT_FILTERS, "5y").period).toBe("5y");
    expect(choosePeriod(DEFAULT_FILTERS, "1h" as never)).toBe(DEFAULT_FILTERS);
  });

  it("parsePoint rejects junk and out-of-range values", () => {
    expect(parsePoint("1.5, 110")).toEqual({ lat: 1.5, lon: 110 });
    expect(parsePoint("abc")).toBeNull();
    expect(parsePoint("95,10")).toBeNull();
  });
});
