// Shared test fixture: the Kapuas worked example as an alert record.
import type { AlertRecord } from "./types";

export function alert(over: Partial<AlertRecord> = {}): AlertRecord {
  return {
    id: "EV-20260921-001", level: 4, level_name: "Critical", directive: "Immediate response required.",
    status: "Notified", score: 85, overrides: [], outlier_review: false,
    province: "Central Kalimantan", district: "Kapuas", country: "Indonesia", place: "Kapuas, Central Kalimantan",
    area: "central-kalimantan", lat: -2.35, lon: 114.35, issued_utc: "2026-09-21T05:42:00Z",
    updated_utc: "2026-09-21T06:00:00Z", utc_offset_h: 7, hotspots_24h: 41, prev_24h: 27.7, growth_pct: 48,
    is_new: false, frp_sum_24h: 1000, chance_24h_pct: 70, chance_48h_pct: 78, chance_72h_pct: 83,
    chance_word: "Very likely", chance_source: "model", reasons: [], anomaly_pct: 280, anomaly_status: "Unusual",
    peat: "deep", fuel: "Deep peat (> 1 m)", town: { name: "Kuala Kapuas", km: 12 }, road_km: null,
    score_parts: {}, haze: { to_border: true, country: "Malaysia" }, weather: null,
    last_check: { said_24h_pct: 77, saw_new: true, result: "correct" }, days_without_hotspots: 0,
    priority: { rank: 1, priority: 73, share_pct: 20 }, actions: [],
    resources: { level: "Critical", rows: [], arrive_within_h: 2, notes: [] },
    coordination: { lead: "BPBD Central Kalimantan", support: "Manggala Agni", also_inform: ["BNPB"],
      duty_officer: null, country: "Indonesia", channel: "SMS", if_no_response: "none", deploy_within_h: 2 },
    nearby_teams: [], report: { situation: "s", assessment: "a", recommendation: "r" },
    ...over,
  };
}

