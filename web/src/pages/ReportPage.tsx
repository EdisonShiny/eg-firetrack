// /report: the "PDF report" print route. Full detail of all four pages for the current Area / Place / Period,
// A4 portrait, one section per page, charts as images. Opens the print dialog once everything has loaded
// (add #noprint to the URL to just preview it).
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RankingCard } from "../components/RankingCard";
import { StaticMap } from "../components/StaticMap";
import { SummaryCard } from "../components/SummaryCard";
import { Card, SampleBadge } from "../components/ui";
import { useAppData } from "../lib/appData";
import { fmtAtOffset, fmtLatLon, fmtMytText } from "../lib/format";
import { PrintModeContext } from "../lib/printMode";
import { selectionDoc } from "../lib/selection";
import { type Period, parsePoint, serializeFilters, useFilters } from "../store/filters";
import { AlertsReport } from "./AlertsPage";
import { AnalysisReport } from "./AnalysisPage";
import { CalendarReport } from "./CalendarPage";
import { selectedSummary } from "./MapPage";

export const REPORT_PERIOD: Record<Period, string> = {
  current: "Current (last 24 h)",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  "12m": "Last 12 months",
  "5y": "Last 5 years",
  all: "All years",
};

/** Report is ready when nothing in it is still loading (skeletons, charts not yet drawn, images). */
function reportReady(root: HTMLElement): boolean {
  if (root.querySelector(".skeleton, [data-chart-pending]")) return false;
  return Array.from(root.querySelectorAll("img")).every((im) => im.complete);
}

export function ReportPage() {
  const f = useFilters();
  const { meta, places, mytOffset } = useAppData();
  const [generated] = useState(() => fmtAtOffset(new Date(), mytOffset));
  const [ready, setReady] = useState(false);
  const autoPrint = !/noprint/.test(window.location.hash);

  const areaName = places.areas.find((a) => a.id === f.area)?.name ?? "Whole Borneo";
  const preset = f.place ? places.places.find((p) => p.id === f.place) : undefined;
  const pt = !preset && f.place ? parsePoint(f.place) : null;
  const placeName = preset ? preset.name : pt ? `Point ${fmtLatLon(pt.lat, pt.lon, 3)}` : "All places in area";
  const sel = selectionDoc(f, places);
  const selected = selectedSummary(f, places);
  const search = serializeFilters(f);

  // File name suggested by "Save as PDF".
  useEffect(() => {
    const old = document.title;
    document.title = `EG FireTrack report - ${sel.name} - ${REPORT_PERIOD[f.period]} - ${meta.data_through_myt.slice(0, 10)}`;
    return () => {
      document.title = old;
    };
  }, [sel.name, f.period, meta.data_through_myt]);

  // Wait until every section has loaded (two quiet checks in a row), then print once.
  useEffect(() => {
    setReady(false);
    let quiet = 0;
    let done = false;
    const id = window.setInterval(() => {
      const root = document.querySelector<HTMLElement>(".rpt");
      if (!root || done) return;
      quiet = reportReady(root) ? quiet + 1 : 0;
      if (quiet < 2) return;
      done = true;
      window.clearInterval(id);
      setReady(true);
      if (autoPrint) document.fonts.ready.then(() => window.setTimeout(() => window.print(), 300));
    }, 250);
    return () => window.clearInterval(id);
  }, [f.area, f.place, f.period, autoPrint]);

  return (
    <PrintModeContext.Provider value={true}>
      <div className="rpt">
        <div className="rpt-toolbar" role="toolbar" aria-label="Report">
          <Link to={{ pathname: "/", search }} className="btn">
            ← Back to the site
          </Link>
          <span className="rpt-status" role="status">
            {ready ? "Report ready: choose “Save as PDF” in the print dialog." : "Preparing the report…"}
          </span>
          <button type="button" className="btn btn-primary" disabled={!ready} onClick={() => window.print()}>
            Print / Save as PDF
          </button>
        </div>

        {/* ------------------------------------------------------------ cover */}
        <section className="rpt-sheet rpt-cover" aria-labelledby="rpt-cover-title">
          <img src="/brand/logo-full.jpg" alt="EG FireTrack, powered by EG Solution 2.0 Team" className="rpt-cover-logo" />
          <h1 className="rpt-cover-title" id="rpt-cover-title">
            EG FireTrack report
          </h1>
          <p className="rpt-cover-sub">Wildfire hotspots in Borneo · where, when, what next, and what to do</p>
          {meta.is_sample && (
            <p className="mode-banner">
              <SampleBadge note={meta.sample_note} /> Sample data: synthetic detections, not real fires.
            </p>
          )}
          <dl className="rpt-facts">
            <dt>Area</dt>
            <dd>{areaName}</dd>
            <dt>Place</dt>
            <dd>
              {placeName}
              {sel.note && <span className="data-note"> · {sel.note}</span>}
            </dd>
            <dt>Period</dt>
            <dd>{REPORT_PERIOD[f.period]}</dd>
            <dt>Generated</dt>
            <dd>{generated} MYT</dd>
            <dt>Data through</dt>
            <dd>{fmtMytText(meta.data_through_myt)} MYT</dd>
            <dt>Data sources</dt>
            <dd>
              <ul className="rpt-sources">
                {meta.sources.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </dd>
          </dl>
          <h2 className="rpt-contents-title">Contents</h2>
          <ol className="rpt-contents">
            <li>Map · where are the fires?</li>
            <li>Calendar · when do fires happen?</li>
            <li>Analysis · past → now → next</li>
            <li>Alerts · what to do, where first</li>
          </ol>
          <p className="rpt-cover-note">
            Harmonized hotspots combine MODIS (1 km) and VIIRS (375 m) so each fire counts once. Medians and averages use
            full years {meta.data_window.median_years[0]}–{meta.data_window.median_years[1]}. Results labelled System come
            from EG FireTrack's models and fixed rules; the agency in charge makes the final decision.
          </p>
          <p className="rpt-cover-foot">Powered by EG Solution 2.0 Team · NASA Space Apps 2026</p>
        </section>

        {/* ------------------------------------------------------------ 1 map */}
        <section className="rpt-sheet" aria-labelledby="rpt-map-h">
          <SectionHead id="rpt-map-h" n={1} title="Map · where are the fires?" sub={`${sel.name} · ${REPORT_PERIOD[f.period]}`} />
          <StaticMap filters={f} />
          <div className="rpt-stack">
            <SummaryCard id="rpt-sum-borneo" file="area/borneo.json" title="Summary · Whole Borneo" period={f.period} showAsOf />
            {selected ? (
              <SummaryCard
                id="rpt-sum-selected"
                file={selected.file}
                title={selected.title}
                meta={selected.meta}
                period={f.period}
                highlight
              />
            ) : (
              <Card title="Summary · Selected area" labelledBy="rpt-sum-selected" highlight>
                <p className="hint">Whole Borneo is selected, so the summary above covers the selection.</p>
              </Card>
            )}
            <div className="rpt-rankings">
              <RankingCard area={f.area} fixedWhen="now" />
              <RankingCard area={f.area} fixedWhen="month" />
              <RankingCard area={f.area} fixedWhen="year" />
            </div>
          </div>
        </section>

        {/* ------------------------------------------------------------ 2 calendar */}
        <section className="rpt-sheet" aria-labelledby="rpt-cal-h">
          <SectionHead id="rpt-cal-h" n={2} title="Calendar · when do fires happen?" sub={sel.name} />
          <div className="rpt-stack">
            <CalendarReport />
          </div>
        </section>

        {/* ------------------------------------------------------------ 3 analysis */}
        <section className="rpt-sheet" aria-labelledby="rpt-ana-h">
          <SectionHead id="rpt-ana-h" n={3} title="Analysis · past → now → next" sub={sel.name} />
          <div className="rpt-stack">
            <AnalysisReport />
          </div>
        </section>

        {/* ------------------------------------------------------------ 4 alerts */}
        <section className="rpt-sheet" aria-labelledby="rpt-alerts-h">
          <SectionHead id="rpt-alerts-h" n={4} title="Alerts · what to do, where first" sub={sel.name} />
          <div className="rpt-stack">
            <AlertsReport />
          </div>
        </section>
      </div>
    </PrintModeContext.Provider>
  );
}

function SectionHead(props: { id: string; n: number; title: string; sub: string }) {
  const { meta } = useAppData();
  return (
    <header className="rpt-head">
      <img src="/brand/logo-mark.png" alt="" className="rpt-head-mark" width={28} height={28} />
      <div>
        <h2 className="rpt-h" id={props.id}>
          {props.n} · {props.title}
        </h2>
        <div className="rpt-head-sub">
          {props.sub} · data through {fmtMytText(meta.data_through_myt)} MYT{meta.is_sample ? " · sample data" : ""}
        </div>
      </div>
    </header>
  );
}
