import { useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useAppData } from "../lib/appData";
import { buildCsv, csvFileName, pageOf, saveText } from "../lib/csv";
import { useJSON } from "../lib/data";
import { fmtLatLon } from "../lib/format";
import type { Alerts, LevelCounts } from "../lib/types";
import {
  type Period,
  filterActions,
  parsePoint,
  serializeFilters,
  useFilters,
} from "../store/filters";
import { DataStatusButton } from "./DataStatus";
import { IntroLauncher } from "./IntroCard";
import { SampleBadge, SegmentedControl } from "./ui";

const TABS = [
  { to: "/", label: "Map" },
  { to: "/calendar", label: "Calendar" },
  { to: "/analysis", label: "Analysis" },
  { to: "/alerts", label: "Alerts" },
];

const ENTER_POINT = "__point__";

/** The full report for the current Area / Place / Period opens in a new tab and prints itself. */
function openReport(search: string) {
  const url = `/report${search}`;
  if (!window.open(url, "_blank")) window.location.assign(url); // pop-up blocked: open it here
}

export function TopBar() {
  const { meta, places, bands } = useAppData();
  const f = useFilters();
  const alerts = useJSON<Alerts>("alerts.json");
  const search = serializeFilters(f);
  const pointPlace = f.place ? parsePoint(f.place) : null;
  const [typing, setTyping] = useState(false);
  const [pointText, setPointText] = useState("");
  const [pointError, setPointError] = useState<string | null>(null);
  const [csvState, setCsvState] = useState<"idle" | "busy" | "error">("idle");
  const location = useLocation();
  const page = pageOf(location.pathname);

  async function downloadCsv() {
    setCsvState("busy");
    try {
      const text = await buildCsv(page, f, meta, places);
      saveText(text, csvFileName(page, f, meta.data_through_myt.slice(0, 10)));
      setCsvState("idle");
    } catch {
      setCsvState("error");
    }
  }

  const w = meta.data_window;
  const periods: { id: Period; label: string }[] = [
    { id: "current", label: "Current" },
    { id: "7d", label: "7 days" },
    { id: "30d", label: "30 days" },
    { id: "12m", label: "12 months" },
    { id: "5y", label: "5 years" },
    { id: "all", label: `All (${w.first_year}–${w.current_year})` },
  ];

  const placeValue = typing ? ENTER_POINT : pointPlace ? f.place! : (f.place ?? "");

  function onPlace(v: string) {
    setPointError(null);
    if (v === ENTER_POINT) {
      setTyping(true);
      setPointText(f.place && pointPlace ? f.place : "");
      return;
    }
    setTyping(false);
    filterActions.setPlace(v === "" ? null : v);
  }

  function submitPoint(e: React.FormEvent) {
    e.preventDefault();
    const pt = parsePoint(pointText);
    if (!pt) return setPointError("Type lat, lon, e.g. 1.55, 110.36");
    if (!filterActions.tryPlace(pointText)) return setPointError("That point is outside Borneo.");
    setTyping(false);
    setPointError(null);
  }

  const counts: LevelCounts | undefined = alerts.data?.counts[f.area];
  const levels = [...bands.levels].sort((a, b) => b.level - a.level);
  const textOn: Record<string, string> = {
    critical: "var(--critical-text)",
    high: "var(--high-text)",
    moderate: "var(--moderate-text)",
    low: "var(--low-text)",
  };
  const areaName = places.areas.find((a) => a.id === f.area)?.name ?? "";

  return (
    <header className="topbar">
      <div className="topbar-row">
        <Link to={{ pathname: "/", search }} className="brand" aria-label="EG FireTrack home">
          <img src="/brand/logo-mark.png" alt="" className="brand-logo" width={36} height={36} />
          <span>
            <span className="brand-name">EG FireTrack</span>
            {meta.is_sample && <SampleBadge note={meta.sample_note} />}
            <br />
            <span className="brand-sub">powered by EG Solution 2.0 Team</span>
          </span>
        </Link>
        <div className="topbar-nav">
          <IntroLauncher />
          <nav className="tabs" aria-label="Pages">
            {TABS.map((t) => (
              <NavLink
                key={t.to}
                to={{ pathname: t.to, search }}
                end={t.to === "/"}
                className={({ isActive }) => `tab${isActive ? " active" : ""}`}
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="topbar-actions">
          <DataStatusButton />
          <button
            type="button"
            className="btn"
            onClick={downloadCsv}
            disabled={csvState === "busy"}
            title={
              page === "map"
                ? "Hotspots in the current Area / Place / Period (0.1° cells for periods over 30 days)"
                : page === "alerts"
                  ? "Active alerts in the current Area / Place"
                  : "Monthly hotspots of the current Area / Place, with the 3-month prediction"
            }
          >
            {csvState === "busy" ? "Preparing…" : csvState === "error" ? "CSV failed – retry" : "Download CSV"}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => openReport(search)}
            title="Opens the full report (all four pages) and the print dialog: choose “Save as PDF”"
          >
            PDF report
          </button>
        </div>
      </div>

      <div className="topbar-row">
        <label className="field tb-area">
          <span className="field-label">Area</span>
          <select className="select" value={f.area} onChange={(e) => filterActions.setArea(e.target.value)}>
            {places.areas.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>

        <div className={`field tb-place${typing ? " typing" : ""}`}>
          <label className="field-label" htmlFor="place-select">
            Place (town or district)
          </label>
          <select id="place-select" className="select" value={placeValue} onChange={(e) => onPlace(e.target.value)}>
            <option value="">All places in area</option>
            {places.places.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
            {pointPlace && !typing && <option value={f.place!}>Point {fmtLatLon(pointPlace.lat, pointPlace.lon, 3)}</option>}
            <option value={ENTER_POINT}>Enter lat, lon…</option>
          </select>
          {typing && (
            <form className="place-point" onSubmit={submitPoint}>
              <label className="visually-hidden" htmlFor="place-point">
                Latitude, longitude
              </label>
              <input
                id="place-point"
                className="text-input"
                placeholder="1.55, 110.36"
                value={pointText}
                autoFocus
                onChange={(e) => setPointText(e.target.value)}
              />
              <button className="btn" type="submit">
                Go
              </button>
              <button className="btn" type="button" onClick={() => (setTyping(false), setPointError(null))}>
                Cancel
              </button>
            </form>
          )}
          {pointError && (
            <span className="field-error" role="alert">
              {pointError}
            </span>
          )}
        </div>

        <div className="field tb-period">
          <span className="field-label" id="period-label">
            Period
          </span>
          <SegmentedControl label="Period" options={periods} value={f.period} onChange={filterActions.setPeriod} />
        </div>

        <Link
          to={{ pathname: "/alerts", search }}
          className="alerts-bar"
          aria-label={`Active alerts in ${areaName}: open Alerts`}
          title={
            alerts.data?.is_stub
              ? "Alerts are not computed yet (sample stub)."
              : alerts.data?.mode && alerts.data.mode !== "model"
                ? "Compared-to-normal fallback: the 72-hour System model did not beat both baselines."
                : alerts.data?.note
          }
        >
          <span className="alerts-bar-long">Active alerts</span>
          <span className="alerts-bar-short">Alerts</span>
          {levels.map((lv) => {
            const key = lv.name.toLowerCase() as keyof LevelCounts;
            return (
              <span key={lv.level} className="level-chip" style={{ background: lv.colour, color: textOn[key] }}>
                {lv.name} {counts ? counts[key] : "–"}
              </span>
            );
          })}
          <span className="alerts-bar-arrow" aria-hidden="true">
            →
          </span>
        </Link>
      </div>
    </header>
  );
}
