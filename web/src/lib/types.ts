// Shapes of the JSON files written by `python -m pipeline.run_daily --export web/public/data`.
import type { Period } from "../store/filters";

export interface Meta {
  generated_at: string;
  data_through_utc: string;
  data_through_myt: string;
  is_sample: boolean;
  sample_note?: string;
  data_window: { first_year: number; current_year: number; median_years: [number, number] };
  /** Rolling window per period, ending at data_through_utc ("all" = everything). */
  periods_days: Partial<Record<Period, number>>;
  sources: string[];
  // Data status button (written by pipeline/export.py; never contains the FIRMS key)
  archive_range?: [string, string] | null;
  archive_rows?: number;
  archive_is_real?: boolean;
  /** Last day of science-quality archive rows; later days come from near-real-time (NRT) files. */
  archive_through?: string | null;
  /** ISO UTC times of the last FIRMS API fetch attempt / last successful one. */
  api_last_attempt?: string | null;
  api_last_success?: string | null;
  api_ok?: boolean | null;
  api_rows_by_source?: Record<string, number>;
  /** Short reason the last fetch failed, e.g. "FIRMS_MAP_KEY missing" or "HTTP 403" (never the key). */
  api_error?: string | null;
  /** Green while the last good fetch is younger than this (config/data.yaml firms.status_fresh_hours). */
  api_fresh_hours?: number;
  api_note?: string | null;
  newest_detection?: string | null;
}

export interface Level {
  max: number;
  level: number;
  name: string;
  /** One-word action under the scale bar ("monitor", "act now"). */
  short?: string;
  directive: string;
  colour: string;
}

export interface Bands {
  levels: Level[];
  frp_dot_sizes_mw: { small_below: number; large_above: number };
  compared_to_normal: { max: number | null; status: string }[];
  compared_to_normal_rule?: {
    floor_cells: number;
    show_pct_up_to: number;
    cap_ratio: number;
    map_period_window: Record<string, string>;
  };
  calendar_ramp: string[];
  unusual_month_ratio: number;
  fire_season_ratio: number;
  texts?: { tags?: Record<string, string> };
  check_words?: Record<string, string>;
}

export interface Area {
  id: string;
  name: string;
  country: string | null;
  bbox: [number, number, number, number];
}
export interface Place {
  id: string;
  name: string;
  area: string;
  district: string;
  lat: number;
  lon: number;
}
export interface District {
  id: string;
  name: string;
  province: string;
  bbox: [number, number, number, number];
}
export interface PlacesDoc {
  areas: Area[];
  places: Place[];
  districts: District[];
  custom_point_radius_km: number;
}

export interface Hotspots {
  is_sample: boolean;
  days: number;
  count: number;
  base_time_utc: string;
  satellites: string[];
  sensor_of_satellite: Record<string, string>;
  confidence: string[];
  areas: string[];
  districts: string[];
  lat: number[];
  lon: number[];
  t: number[];
  sat: number[];
  frp: number[];
  conf: number[];
  bright: number[];
  area: number[];
  district: number[];
}

export interface Grid {
  is_sample: boolean;
  cell_deg: number;
  days: number | null;
  areas: string[];
  districts: string[];
  lat: number[];
  lon: number[];
  count: number[];
  frp: number[];
  area: number[];
  district: number[];
}

export interface RankingRow {
  district: string;
  name: string;
  province: string;
  province_name: string;
  now: number;
  month: number;
  year: number;
}
export interface Ranking {
  periods: { now: string; month: string; year: string };
  districts: RankingRow[];
}

export type LevelCounts = { critical: number; high: number; moderate: number; low: number };
export type ForecastMode = "model" | "compared-to-normal fallback";
export interface Reason {
  feature: string;
  label: string;
  value: number | string;
  effect_pp: number;
}
export interface AlertAction {
  when: string;
  action: string;
  why: string;
  rule?: string;
}
export interface AlertRecord {
  id: string;
  level: number;
  level_name: string;
  directive: string;
  status: string;
  score: number;
  overrides: string[];
  outlier_review: boolean;
  province: string;
  district: string;
  country: string;
  place: string;
  area: string;
  lat: number;
  lon: number;
  issued_utc: string;
  updated_utc: string;
  utc_offset_h: number;
  hotspots_24h: number;
  prev_24h: number;
  growth_pct: number;
  is_new: boolean;
  frp_sum_24h: number;
  chance_24h_pct: number;
  chance_48h_pct: number;
  chance_72h_pct: number;
  chance_word: string | null;
  chance_source: "model" | "fallback";
  reasons: Reason[];
  anomaly_pct: number | null;
  anomaly_status: string | null;
  /** Display text for anomaly_pct ("+18%", "3.2×", ">10×"). */
  anomaly_label?: string;
  peat: "none" | "shallow" | "deep";
  fuel: string;
  town: { name: string; km: number };
  road_km: number | null;
  score_parts: Record<string, number>;
  haze: { to_border: boolean; country: string | null };
  weather: { dry_days: number | null; rain_next_mm: number | null; cloud_pct: number | null } | null;
  last_check: { said_24h_pct: number; saw_new: boolean; result: "correct" | "missed" | "false_alarm" };
  days_without_hotspots: number;
  priority: { rank: number; priority: number; share_pct: number } | null;
  actions: AlertAction[];
  resources: {
    level: string;
    rows: { name: string; qty: string }[];
    arrive_within_h: number | null;
    notes: string[];
  };
  coordination: {
    lead: string;
    support: string;
    also_inform: string[];
    duty_officer: string | null;
    country: string;
    channel: string;
    if_no_response: string;
    deploy_within_h: number | null;
  };
  nearby_teams: { town: string; km: number; team: string }[];
  report: { situation: string; assessment: string; recommendation: string };
}
export interface Alerts {
  is_stub?: boolean;
  is_sample?: boolean;
  mode?: ForecastMode;
  note?: string;
  weather_note?: string | null;
  generated_at?: string;
  as_of_day?: string;
  counts: Record<string, LevelCounts>;
  watch?: number;
  alerts?: AlertRecord[];
}

export interface Summary {
  now: number;
  month: number;
  year: number;
  yearly_avg: number | null;
  avg_frp: number | null;
  avg_frp_by_period: Record<Period, number | null>;
  count_by_period: Record<Period, number>;
  /** This month so far (Analysis risk band / alerts). */
  compared_to_normal: CompareToNormal;
  /** Every window: current, 7d, 30d, month, year (pipeline/stats.py compare_to_normal). */
  compared_to_normal_by_window?: Record<string, CompareToNormal>;
}
export interface CompareToNormal {
  pct: number | null;
  status: string | null;
  basis: string;
  /** Display text: "+18%", "3.2×" or ">10×". */
  label?: string;
  ratio?: number | null;
  current?: number;
  usual?: number | null;
  median?: number | null;
  floored?: boolean;
  window?: string;
}
export interface AreaDoc {
  id: string;
  name: string;
  kind: "borneo" | "area" | "place";
  province: string | null;
  district: string | null;
  data_through_myt: string;
  summary: Summary;
  calendar: CalendarData;
  analysis: AnalysisData;
}

export interface CalendarCell {
  count: number;
  /** Ramp colour index 0..6 (quantile bin). */
  bin: number;
  /** count / usual (median) month, null when usual = 0. */
  ratio: number | null;
  unusual: boolean;
  /** Month still running (the current month). */
  partial: boolean;
}
export interface CalendarData {
  years: number[];
  months: string[];
  /** One row per year; null cell = month not reached yet. */
  rows: { year: number; cells: (CalendarCell | null)[]; total: number; so_far: boolean }[];
  usual: { count: number; bin: number }[];
  usual_years: [number, number];
  bin_edges: number[];
  yearly_totals: { year: number; total: number; so_far: boolean; record: boolean }[];
  fire_season: {
    months: number[];
    run: number[];
    label: string | null;
    share_pct: number | null;
    average_month: number;
    ratio: number;
  };
  season_strength: number | null;
  facts: {
    record_year: { year: number; total: number } | null;
    quietest_year: { year: number; total: number } | null;
    peak_month: { month: number; usual: number } | null;
    quietest_month: { month: number; usual: number } | null;
    average_per_year: number | null;
    so_far_vs_prev: {
      year: number;
      prev: number;
      span: string;
      current: number;
      previous: number;
      pct: number | null;
    } | null;
    unusual_months: { count: number; latest: string | null };
    season_strength: number | null;
  };
  per_year: {
    year: number;
    total: number;
    so_far: boolean;
    vs_avg_pct: number | null;
    peak_month: number | null;
    unusual_months: number;
  }[];
  last_data_month: string;
  partial_month: string | null;
}

export interface SeriesData {
  count: number[];
  frp: (number | null)[];
}
export interface PredictionPoint {
  month: string;
  value: number;
  low: number;
  high: number;
  range_pct: number;
}
export interface AnalysisData {
  /** "YYYY-MM", 2017-01 → the current (maybe partial) month. */
  months: string[];
  now_index: number;
  series: { modis_raw: SeriesData; viirs_raw: SeriesData; harmonized: SeriesData };
  series_note: string;
  prediction: {
    is_stub?: boolean;
    count_method?: "model" | "usual";
    frp_method?: "model" | "usual";
    method: string;
    count: PredictionPoint[];
    frp: PredictionPoint[];
  };
  trend_summary: { tag: string; title: string; text: string }[];
  harmonization_check: {
    span: string;
    span_months: number[];
    years: number[];
    modis_raw: number[];
    viirs_raw: number[];
    harmonized: number[];
    r2: number | null;
    avg_error_pct: number | null;
    k: number | null;
    check_scope: string;
  };
  rescue_risk: {
    is_stub?: boolean;
    /** "model" = 72-hour System model; otherwise the chance comes from compared to normal. */
    mode?: ForecastMode;
    note?: string | null;
    events?: number;
    level: number | null;
    level_name: string | null;
    score: number | null;
    directive: string | null;
    tiles: {
      compared_to_normal: { pct: number | null; status: string | null; label?: string; basis?: string };
      chance_of_spreading: { pct: number | null; word: string | null; source?: "model" | "fallback" };
      recent_direction: { pct: number | null; word: string | null; rising_weeks: number };
      fuel_type: { value: string; note?: string } | null;
      people_nearby: { value: string; note?: string } | null;
    };
  };
}

/** A Feature from boundaries.json (simplified GADM provinces + districts). */
export interface BoundaryFeature {
  type: "Feature";
  properties: { level: "province" | "district"; id: string; name: string; area: string; country: string };
  geometry: { type: "Polygon"; coordinates: number[][][] } | { type: "MultiPolygon"; coordinates: number[][][][] };
}
export interface Boundaries {
  type: "FeatureCollection";
  features: BoundaryFeature[];
}
