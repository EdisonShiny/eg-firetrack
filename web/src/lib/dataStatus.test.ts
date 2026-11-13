import { describe, expect, it } from "vitest";
import { dataStatus } from "./dataStatus";
import type { Meta } from "./types";

const base = {
  is_sample: false,
  api_ok: true,
  api_last_success: "2026-11-09T12:00:00Z",
  api_fresh_hours: 26,
} as Meta;
const at = (iso: string) => new Date(iso);

describe("dataStatus", () => {
  it("green when the last good fetch is under 26 h old", () => {
    expect(dataStatus(base, at("2026-11-09T15:00:00Z")).tone).toBe("green");
    expect(dataStatus(base, at("2026-11-10T13:59:00Z")).tone).toBe("green");
  });
  it("amber at 26 h and later", () => {
    expect(dataStatus(base, at("2026-11-10T14:00:00Z")).tone).toBe("amber");
    expect(dataStatus(base, at("2026-11-12T00:00:00Z")).tone).toBe("amber");
  });
  it("red when the last fetch failed, even if an older one succeeded", () => {
    expect(dataStatus({ ...base, api_ok: false }, at("2026-11-09T15:00:00Z")).tone).toBe("red");
  });
  it("red when no fetch ever succeeded", () => {
    expect(dataStatus({ ...base, api_last_success: null, api_ok: null }, at("2026-11-09T15:00:00Z")).tone).toBe("red");
  });
  it("grey for sample data, whatever the fetch state", () => {
    expect(dataStatus({ ...base, is_sample: true, api_ok: false }, at("2026-11-09T15:00:00Z")).tone).toBe("grey");
  });
  it("uses api_fresh_hours from meta.json", () => {
    expect(dataStatus({ ...base, api_fresh_hours: 2 }, at("2026-11-09T15:00:00Z")).tone).toBe("amber");
  });
  it("reports the age in hours", () => {
    expect(dataStatus(base, at("2026-11-09T18:30:00Z")).ageHours).toBe(6.5);
  });
});
