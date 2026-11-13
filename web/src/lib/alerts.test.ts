import { describe, expect, it } from "vitest";
import {
  alertsInSelection,
  countLevels,
  growthText,
  lastCheckText,
  priorityLabel,
  priorityText,
  reasonBars,
  sortAlerts,
  timeBadge,
  tzLabel,
  issuedText,
} from "./alerts";
import { alert } from "./fixtures";
import type { PlacesDoc } from "./types";
import { DEFAULT_FILTERS } from "../store/filters";

const places = {
  areas: [], custom_point_radius_km: 25,
  places: [{ id: "palangka-raya", name: "Palangka Raya", area: "central-kalimantan", district: "palangka-raya", lat: -2.2, lon: 113.9 }],
  districts: [{ id: "palangka-raya", name: "Palangka Raya", province: "central-kalimantan", bbox: [0, 0, 0, 0] }],
} as unknown as PlacesDoc;

describe("alerts list", () => {
  const list = [
    alert(),
    alert({ id: "b", level: 3, level_name: "High", priority: null, score: 60, district: "Palangka Raya" }),
    alert({ id: "c", level: 4, level_name: "Critical", priority: { rank: 2, priority: 70, share_pct: 19 } }),
    alert({ id: "d", level: 2, level_name: "Moderate", priority: null, score: 30, area: "sarawak", province: "Sarawak" }),
  ];

  it("filters by area and by a preset place's district", () => {
    expect(alertsInSelection(list, DEFAULT_FILTERS, places)).toHaveLength(4);
    expect(alertsInSelection(list, { ...DEFAULT_FILTERS, area: "sarawak" }, places).map((a) => a.id)).toEqual(["d"]);
    const pr = alertsInSelection(list, { ...DEFAULT_FILTERS, area: "central-kalimantan", place: "palangka-raya" }, places);
    expect(pr.map((a) => a.id)).toEqual(["b"]);
  });

  it("counts levels and sorts by level, then P-rank, then score", () => {
    expect(countLevels(list)).toEqual({ critical: 2, high: 1, moderate: 1, low: 0 });
    expect(sortAlerts([list[3], list[1], list[2], list[0]]).map((a) => a.id)).toEqual([
      "EV-20260921-001", "c", "b", "d",
    ]);
  });
});

describe("labels", () => {
  it("Critical shows P-rank and team share, others the risk score", () => {
    expect(priorityLabel(alert())).toEqual({ main: "P1 · 20%", sub: "of rescue teams" });
    expect(priorityText(alert())).toBe("P1 · 20% of rescue teams");
    expect(priorityLabel(alert({ priority: null, score: 56 }))).toEqual({ main: "Score 56", sub: "risk score" });
    expect(priorityText(alert({ priority: null }))).toBeNull();
  });

  it("local time zones", () => {
    expect(tzLabel("Indonesia", 7)).toBe("WIB");
    expect(tzLabel("Indonesia", 8)).toBe("WITA");
    expect(tzLabel("Malaysia", 8)).toBe("MYT");
    expect(issuedText(alert())).toBe("21 Sep 2026, 12:42 WIB");
  });

  it("time badges by window", () => {
    expect(timeBadge("0-2 h")).toEqual({ text: "0–2 h", tone: "t0" });
    expect(timeBadge("2-12 h").tone).toBe("t1");
    expect(timeBadge("12-72 h")).toEqual({ text: "12–72 h", tone: "t2" });
    expect(timeBadge("Daily").tone).toBe("t3");
  });

  it("reason bars scale to the largest effect and keep the sign", () => {
    const b = reasonBars([{ effect_pp: 24 }, { effect_pp: 12 }, { effect_pp: -1.2 }]);
    expect(b[0]).toEqual({ width: 100, raises: true, text: "+24%" });
    expect(b[1].width).toBe(50);
    expect(b[2]).toMatchObject({ raises: false, text: "−1%" });
  });

  it("growth and last check", () => {
    expect(growthText(alert())).toBe("+48% vs yesterday");
    expect(growthText(alert({ is_new: true }))).toBe("new since yesterday");
    expect(lastCheckText(alert(), { correct: "✓ correct" })).toBe(
      "Last check: yesterday the System gave 77% (next 24 h) → 41 hotspots observed today ✓ correct",
    );
    expect(lastCheckText(alert({ last_check: { said_24h_pct: 60, saw_new: false, result: "false_alarm" } }))).toContain(
      "no new hotspots today false alarm",
    );
  });
});
