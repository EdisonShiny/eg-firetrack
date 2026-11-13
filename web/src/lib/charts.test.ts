import { describe, expect, it } from "vitest";
import { cellTooltip, monthLabel, trendView, windowForPeriod } from "./charts";
import type { AnalysisData } from "./types";

describe("calendar tooltip", () => {
  it("shows month, count and × usual", () => {
    expect(cellTooltip(9, 2019, { count: 1612, bin: 6, ratio: 3.24, unusual: true, partial: false })).toBe(
      "Sep 2019: 1,612 hotspots (3.2× usual) · unusual month",
    );
    expect(cellTooltip(2, 2020, { count: 15, bin: 0, ratio: 1, unusual: false, partial: false })).toBe(
      "Feb 2020: 15 hotspots (1.0× usual)",
    );
  });
  it("handles partial, future and zero-usual months", () => {
    expect(cellTooltip(11, 2026, { count: 16, bin: 0, ratio: 0.28, unusual: false, partial: true })).toBe(
      "Nov 2026 so far: 16 hotspots (0.3× usual)",
    );
    expect(cellTooltip(12, 2026, null)).toBe("Dec 2026: no data yet");
    expect(cellTooltip(1, 2018, { count: 1, bin: 0, ratio: null, unusual: false, partial: false })).toBe(
      "Jan 2018: 1 hotspot (usual is 0)",
    );
  });
});

function analysis(n: number): AnalysisData {
  const months = Array.from(
    { length: n },
    (_, i) => `${2017 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}`,
  );
  const s = (f: number) => ({ count: months.map((_, i) => i * f), frp: months.map(() => 10) });
  const p = (month: string, value: number) => ({ month, value, low: value - 1, high: value + 1, range_pct: 15 });
  return {
    months,
    now_index: n - 1,
    series: { modis_raw: s(1), viirs_raw: s(3), harmonized: s(2) },
    series_note: "",
    prediction: {
      method: "",
      count: [p("x1", 50), p("x2", 40), p("x3", 30)],
      frp: [p("x1", 5), p("x2", 5), p("x3", 5)],
    },
    trend_summary: [],
    harmonization_check: {} as AnalysisData["harmonization_check"],
    rescue_risk: {} as AnalysisData["rescue_risk"],
  };
}

describe("trend view", () => {
  it("12 months = last 12 months + 3 predicted, now line on the current month", () => {
    const v = trendView(analysis(119), "12m", "count");
    expect(v.months.length).toBe(15);
    expect(v.months[0]).toBe("2025-12");
    expect(v.months[11]).toBe("2026-11");
    expect(v.months.slice(12)).toEqual(["x1", "x2", "x3"]);
    expect(v.now).toBe(11);
    expect(v.harmonized[11]).toBe(236);
    expect(v.harmonized[12]).toBeNull();
    // the dotted prediction starts at the now value so it joins the harmonized line
    expect(v.prediction.slice(10)).toEqual([null, 236, 50, 40, 30]);
    expect(v.low.slice(11)).toEqual([236, 49, 39, 29]);
    expect(v.band.slice(11)).toEqual([0, 2, 2, 2]);
  });
  it("switches change the window and metric", () => {
    expect(trendView(analysis(119), "5y", "count").months.length).toBe(63);
    expect(trendView(analysis(119), "10y", "count").months.length).toBe(122); // all 119 months
    expect(trendView(analysis(119), "12m", "frp").prediction.slice(12)).toEqual([5, 5, 5]);
  });
  it("month labels and default window", () => {
    expect(monthLabel("2019-09")).toBe("Sep 2019");
    expect(windowForPeriod("30d")).toBe("5y");
    expect(windowForPeriod("12m")).toBe("12m");
    expect(windowForPeriod("all")).toBe("10y");
  });
});
