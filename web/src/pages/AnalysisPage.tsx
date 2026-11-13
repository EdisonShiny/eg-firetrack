// Analysis: past → now → next. Trend chart + trend summary, rescue risk status, harmonization check.
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { CHART_TEXT, EChart, type EChartsOption, TOOLTIP_STYLE } from "../components/EChart";
import { Card, SegmentedControl, Skeleton } from "../components/ui";
import { useAppData } from "../lib/appData";
import { usePrintMode } from "../lib/printMode";
import { monthLabel, type TrendMetric, trendView, type TrendWindow, windowForPeriod } from "../lib/charts";
import { useJSON } from "../lib/data";
import { fmtInt, fmtMytText, fmtNum, fmtPct, monthName, vsUsualNote } from "../lib/format";
import { selectionDoc } from "../lib/selection";
import type { AnalysisData, AreaDoc, Level } from "../lib/types";
import { useFilters } from "../store/filters";

const C = { modis: "#9CA3AF", viirs: "#2563EB", harm: "#C2410C", zone: "rgba(255,241,235,0.85)", range: "#FBD3BC" };

export function AnalysisPage() {
  const f = useFilters();
  const { places } = useAppData();
  const sel = selectionDoc(f, places);
  const { data, error } = useJSON<AreaDoc>(sel.file);
  const a = data?.analysis;
  const { search } = useLocation();

  return (
    <main className="analysis">
      <header className="page-head">
        <h1 className="page-title">Fire activity analysis · {sel.name}</h1>
        <p className="page-sub">
          Past → now → next: how fire activity moved, where it stands today, and where the System expects it to go
          {sel.note && <span className="data-note"> · {sel.note}</span>}
        </p>
      </header>
      {error && <p className="error-box">Could not load the analysis ({error}).</p>}
      <div className="analysis-row">
        {a && data ? <TrendCard a={a} partialMonth={data.calendar.partial_month} /> : <Skeleton height={520} />}
        {a ? <TrendSummary a={a} /> : <Skeleton height={520} />}
      </div>
      {a && data ? <RiskBand a={a} doc={data} search={search} /> : <Skeleton height={280} />}
      {a ? <HarmonizationCard a={a} /> : <Skeleton height={300} />}
    </main>
  );
}

/** PDF report: trend for hotspots and for FRP, trend summary, rescue risk status, harmonization check. */
export function AnalysisReport() {
  const f = useFilters();
  const { places } = useAppData();
  const sel = selectionDoc(f, places);
  const { data, error } = useJSON<AreaDoc>(sel.file);
  const a = data?.analysis;
  if (error) return <p className="error-box">Could not load the analysis ({error}).</p>;
  if (!a || !data) return <Skeleton height={900} />;
  return (
    <>
      {sel.note && <p className="data-note">{sel.note}</p>}
      <TrendCard a={a} partialMonth={data.calendar.partial_month} fixedMetric="count" />
      <TrendCard a={a} partialMonth={data.calendar.partial_month} fixedMetric="frp" />
      <TrendSummary a={a} />
      <PredictionTable a={a} />
      <RiskBand a={a} doc={data} search="" />
      <HarmonizationCard a={a} />
    </>
  );
}

/** The 3-month prediction as numbers (the chart shows it as a dotted line with a band). */
function PredictionTable(props: { a: AnalysisData }) {
  const { a } = props;
  const rows = a.prediction.count.map((p, i) => ({ month: p.month, count: p, frp: a.prediction.frp[i] }));
  return (
    <Card title="Prediction · next 3 months" labelledBy="rpt-pred-title" meta="System prediction with likely range">
      <table className="pred-table">
        <thead>
          <tr>
            <th scope="col">Month</th>
            <th scope="col">Hotspots</th>
            <th scope="col">Likely range</th>
            <th scope="col">Average FRP</th>
            <th scope="col">Likely range</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.month}>
              <td>{monthLabel(r.month)}</td>
              <td className="mono">{fmtInt(r.count.value)}</td>
              <td className="mono">
                {fmtInt(r.count.low)} – {fmtInt(r.count.high)} (±{r.count.range_pct}%)
              </td>
              <td className="mono">{r.frp ? `${fmtNum(r.frp.value)} MW` : "–"}</td>
              <td className="mono">
                {r.frp ? `${fmtNum(r.frp.low)} – ${fmtNum(r.frp.high)} MW (±${r.frp.range_pct}%)` : "–"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="card-foot">{a.prediction.method}</p>
    </Card>
  );
}

function TrendCard(props: { a: AnalysisData; partialMonth: string | null; fixedMetric?: TrendMetric }) {
  const { a } = props;
  const { period } = useFilters();
  const { meta } = useAppData();
  const [pickedMetric, setMetric] = useState<TrendMetric>("count");
  const metric = props.fixedMetric ?? pickedMetric;
  const [win, setWin] = useState<TrendWindow>(windowForPeriod(period));
  useEffect(() => setWin(windowForPeriod(period)), [period]);

  const v = useMemo(() => trendView(a, win, metric), [a, win, metric]);
  const pred = a.prediction[metric];
  const partial = props.partialMonth === a.months[a.now_index];
  const unit = metric === "count" ? "hotspots" : "MW";
  const fmtV = (x: number | null | undefined) => (x === null || x === undefined ? "–" : metric === "count" ? fmtInt(x) : `${fmtNum(x)} MW`);

  const option = useMemo<EChartsOption>(() => {
    const last = v.months.length - 1;
    const isJan = (m: string) => m.endsWith("-01");
    const harm = v.harmonized.map((x, i) =>
      i === v.now && partial ? { value: x, symbol: "emptyCircle", symbolSize: 8 } : x,
    );
    return {
      animation: false,
      grid: { left: 52, right: 16, top: 30, bottom: 34 },
      tooltip: {
        ...TOOLTIP_STYLE,
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: "#9CA3AF" } },
        formatter: (ps: { dataIndex: number }[]) => {
          const i = ps[0]?.dataIndex ?? 0;
          const m = v.months[i];
          if (i > v.now) {
            const p = pred[i - v.now - 1];
            return `<b>${monthLabel(m)}</b> · predicted<br/>Prediction: ${fmtV(p.value)}<br/>Likely range: ${fmtV(
              p.low,
            )} – ${fmtV(p.high)} (±${p.range_pct}%)`;
          }
          const so = i === v.now && partial ? ` so far (to ${fmtMytText(meta.data_through_myt).replace(/, .*$/, "")})` : "";
          const name = metric === "count" ? "hotspots" : "average FRP";
          return `<b>${monthLabel(m)}</b>${so}<br/>Harmonized: <b>${fmtV(v.harmonized[i])}</b> ${
            metric === "count" ? name : ""
          }<br/>VIIRS raw: ${fmtV(v.viirs[i])}<br/>MODIS raw: ${fmtV(v.modis[i])}`;
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: v.months,
        axisLine: { lineStyle: { color: "#E3E6EA" } },
        axisTick: { show: false },
        axisLabel: {
          ...CHART_TEXT,
          interval: 0,
          formatter: (m: string, i: number) => {
            if (i === v.now) return "{now|now}";
            if (win === "12m") return isJan(m) ? `${monthName(Number(m.slice(5)))}\n${m.slice(0, 4)}` : monthName(Number(m.slice(5)));
            return isJan(m) && i < v.now - 2 ? m.slice(0, 4) : "";
          },
          rich: { now: { ...CHART_TEXT, color: "#111827", fontWeight: 600 } },
        },
      },
      yAxis: {
        type: "value",
        name: unit,
        nameTextStyle: { ...CHART_TEXT, align: "right" },
        axisLabel: { ...CHART_TEXT, formatter: (x: number) => fmtInt(x) },
        splitLine: { lineStyle: { color: "#EEF0F3" } },
      },
      series: [
        { name: "MODIS raw", type: "line", data: v.modis, symbol: "none", lineStyle: { color: C.modis, width: 1.6 }, itemStyle: { color: C.modis } },
        { name: "VIIRS raw", type: "line", data: v.viirs, symbol: "none", lineStyle: { color: C.viirs, width: 1.6 }, itemStyle: { color: C.viirs } },
        {
          name: "range-low",
          type: "line",
          data: v.low,
          stack: "range",
          symbol: "none",
          lineStyle: { opacity: 0 },
          silent: true,
          tooltip: { show: false },
        },
        {
          name: "Likely range",
          type: "line",
          data: v.band,
          stack: "range",
          symbol: "none",
          lineStyle: { opacity: 0 },
          areaStyle: { color: C.range, opacity: 0.75 },
          silent: true,
        },
        {
          name: "Harmonized",
          type: "line",
          data: harm,
          symbol: "none",
          z: 5,
          lineStyle: { color: C.harm, width: 3 },
          itemStyle: { color: C.harm },
          markLine: {
            silent: true,
            symbol: "none",
            label: { show: false },
            lineStyle: { color: "#6B7280", type: "dashed", width: 1 },
            data: [{ xAxis: v.months[v.now] }],
          },
          markArea: {
            silent: true,
            itemStyle: { color: C.zone },
            label: { show: true, position: "insideTopRight", ...CHART_TEXT, color: C.harm, fontWeight: 600 },
            data: [[{ xAxis: v.months[v.now], name: "prediction" }, { xAxis: v.months[last] }]],
          },
        },
        {
          name: "Prediction",
          type: "line",
          data: v.prediction,
          symbol: "none",
          z: 6,
          lineStyle: { color: C.harm, width: 2.5, type: [3, 4] },
          itemStyle: { color: C.harm },
        },
      ],
    };
  }, [v, win, metric, partial, pred, unit, meta.data_through_myt]);

  return (
    <Card
      labelledBy="trend-title"
      className="trend-card"
      title={`Trend · ${metric === "count" ? "hotspots per month" : "average fire intensity (FRP) per month"}`}
      meta={
        props.fixedMetric ? (
          `${win === "12m" ? "12 months" : win === "5y" ? "5 years" : "10 years"} + 3-month prediction`
        ) : (
        <div className="trend-switches">
          <SegmentedControl
            small
            label="Measure"
            value={metric}
            onChange={setMetric}
            options={[
              { id: "count", label: "Hotspots" },
              { id: "frp", label: "FRP" },
            ]}
          />
          <SegmentedControl
            small
            label="Time span"
            value={win}
            onChange={setWin}
            options={[
              { id: "12m", label: "12 months" },
              { id: "5y", label: "5 years" },
              { id: "10y", label: "10 years" },
            ]}
          />
        </div>
        )
      }
    >
      <EChart option={option} height={props.fixedMetric ? 320 : 380} label={`Line chart: ${metric === "count" ? "hotspots" : "average FRP"} per month with a 3-month prediction`} />
      <div className="chart-legend">
        <span className="legend-key">
          <i className="key-line" style={{ background: C.modis }} /> MODIS raw (1 km)
        </span>
        <span className="legend-key">
          <i className="key-line" style={{ background: C.viirs }} /> VIIRS raw (375 m)
        </span>
        <span className="legend-key">
          <i className="key-line thick" style={{ background: C.harm }} /> Harmonized (used everywhere)
        </span>
        <span className="legend-key">
          <i className="key-dots" /> Prediction, next 3 months
        </span>
        <span className="legend-key">
          <i className="key-box" style={{ background: C.range }} /> likely range
        </span>
      </div>
      <p className="card-foot">
        {metric === "frp" ? "FRP = average fire radiative power per hotspot (MW). " : ""}
        {partial ? "The hollow point is the current month so far. " : ""}
        {a.prediction.method}
      </p>
    </Card>
  );
}

const TAG_CLASS: Record<string, string> = { PAST: "past", NOW: "now", NEXT: "next", DATA: "data" };

function TrendSummary(props: { a: AnalysisData }) {
  const { bands } = useAppData();
  const tags = bands.texts?.tags ?? {};
  const cls = (t: string) => {
    const key = Object.entries(tags).find(([, v]) => v === t)?.[0];
    return key ?? TAG_CLASS[t] ?? "past";
  };
  return (
    <Card title="Trend summary" labelledBy="summary-title">
      <ul className="trend-list">
        {props.a.trend_summary.map((r, i) => (
          <li key={i}>
            <span className={`trend-tag ${cls(r.tag)}`}>{r.tag}</span>
            <div>
              <div className="trend-head">{r.title}</div>
              <div className="trend-text">{r.text}</div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function levelRange(levels: Level[], i: number): string {
  const lo = i === 0 ? 0 : levels[i - 1].max + 1;
  return `${lo}–${levels[i].max}`;
}

function RiskBand(props: { a: AnalysisData; doc: AreaDoc; search: string }) {
  const { bands } = useAppData();
  const print = usePrintMode();
  const r = props.a.rescue_risk;
  const levels = bands.levels;
  const lvl = r.level !== null ? levels.find((l) => l.level === r.level) : undefined;
  const colour = lvl?.colour ?? "#C2410C";
  const t = r.tiles;
  const s = props.doc.summary;
  const cmpMonth = s.compared_to_normal.basis?.match(/^[A-Z][a-z]{2}[^v]*?\d{4}/)?.[0];
  const tone = (x: number | null | undefined) => (x === null || x === undefined || x === 0 ? "" : x > 0 ? "up" : "down");

  return (
    <section className="risk-band" style={{ borderLeftColor: colour }} aria-labelledby="risk-title">
      <div className="risk-head">
        <div>
          <div className="risk-kicker">PREDICTION · RESCUE RISK STATUS</div>
          <h2 className="risk-title" id="risk-title">
            {props.doc.name}:{" "}
            {lvl ? (
              <>
                <span style={{ color: lvl.colour === "#FACC15" ? "#A16207" : lvl.colour }}>{lvl.name}</span> · score{" "}
                {r.score} / 100
              </>
            ) : (
              <span className="risk-pending">level not computed yet</span>
            )}
          </h2>
          <p className="risk-directive">{lvl ? (r.note ?? r.directive ?? lvl.directive) : r.note}</p>
          {r.mode && (
            <p className={`risk-mode ${r.mode === "model" ? "" : "fallback"}`}>
              {r.mode === "model"
                ? "Chance of spreading: 72-hour System model."
                : "Compared-to-normal fallback: the 72-hour System model did not beat both baselines, so the chance of spreading comes from compared to normal."}
            </p>
          )}
        </div>
        {!print && (
          <Link className="btn btn-critical" to={{ pathname: "/alerts", search: props.search }}>
            Open alerts →
          </Link>
        )}
      </div>

      <div className="scale" role="img" aria-label={r.score === null ? "Risk scale, no score yet" : `Risk score ${r.score} of 100`}>
        <div className="scale-bar">
          {levels.map((l, i) => (
            <span key={l.level} style={{ background: l.colour, flexGrow: l.max - (i === 0 ? -1 : levels[i - 1].max) }} />
          ))}
          {r.score !== null && (
            <b className="scale-marker" style={{ left: `${Math.min(100, Math.max(0, r.score))}%` }}>
              <em>{r.score}</em>
            </b>
          )}
        </div>
        <div className="scale-labels">
          {levels.map((l, i) => (
            <span key={l.level} style={{ flexGrow: l.max - (i === 0 ? -1 : levels[i - 1].max) }}>
              {l.name} {levelRange(levels, i)}
              {l.short ? ` · ${l.short}` : ""}
            </span>
          ))}
        </div>
      </div>

      <div className="risk-tiles">
        <RiskTile
          label="Compared to normal"
          value={t.compared_to_normal.label ?? fmtPct(t.compared_to_normal.pct)}
          tone={tone(t.compared_to_normal.pct)}
          tech={vsUsualNote(t.compared_to_normal.status)}
          meaning={
            t.compared_to_normal.status
              ? `${t.compared_to_normal.status}${cmpMonth ? ` for ${cmpMonth}` : ""}.`
              : "Not enough history."
          }
        />
        <RiskTile
          label="Chance of spreading"
          value={t.chance_of_spreading.pct === null ? "–" : `${Math.round(t.chance_of_spreading.pct)}%`}
          tone={t.chance_of_spreading.pct === null ? "" : "up"}
          tech="72-hour system outlook"
          meaning={
            t.chance_of_spreading.word
              ? `${t.chance_of_spreading.word} to grow in the next 3 days${
                  t.chance_of_spreading.source === "fallback" ? " (from compared to normal)" : ""
                }.`
              : "No fire activity to score."
          }
        />
        <RiskTile
          label="Recent direction"
          value={fmtPct(t.recent_direction.pct)}
          tone={tone(t.recent_direction.pct)}
          tech="week-on-week change, 3 weeks"
          meaning={
            t.recent_direction.word
              ? `${t.recent_direction.word}; rising in ${t.recent_direction.rising_weeks} of the last 3 weeks.`
              : "Not enough data."
          }
        />
        <RiskTile
          label="Fuel type"
          value={t.fuel_type?.value ?? "–"}
          tech="peat under the fire events"
          meaning={t.fuel_type?.note ?? "Not available yet."}
        />
        <RiskTile
          label="People nearby"
          value={t.people_nearby?.value ?? "–"}
          tech="fire events near a town"
          meaning={t.people_nearby?.note ?? "Not available yet."}
        />
      </div>
    </section>
  );
}

function RiskTile(props: { label: string; value: string; tone?: string; tech: string; meaning: ReactNode }) {
  return (
    <div className="risk-tile">
      <div className="risk-tile-label">{props.label}</div>
      <div className={`risk-tile-value ${props.tone ?? ""}`}>{props.value}</div>
      <div className="risk-tile-tech">{props.tech}</div>
      <div className="risk-tile-meaning">{props.meaning}</div>
    </div>
  );
}

function HarmonizationCard(props: { a: AnalysisData }) {
  const { meta } = useAppData();
  const h = props.a.harmonization_check;
  const [y0, y1] = meta.data_window.median_years;
  const first = h.years[0];
  const last = h.years[h.years.length - 1];

  const option = useMemo<EChartsOption>(
    () => ({
      animation: false,
      grid: { left: 8, right: 16, top: 16, bottom: 28, containLabel: true },
      tooltip: {
        ...TOOLTIP_STYLE,
        trigger: "axis",
        formatter: (ps: { dataIndex: number }[]) => {
          const i = ps[0]?.dataIndex ?? 0;
          return `<b>${h.span} ${h.years[i]}</b><br/>Harmonized: <b>${fmtInt(h.harmonized[i])}</b><br/>VIIRS raw: ${fmtInt(
            h.viirs_raw[i],
          )}<br/>MODIS raw: ${fmtInt(h.modis_raw[i])}`;
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: h.years.map(String),
        axisLine: { lineStyle: { color: "#E3E6EA" } },
        axisTick: { show: false },
        axisLabel: { ...CHART_TEXT, fontFamily: "JetBrains Mono, Consolas, monospace" },
      },
      yAxis: {
        type: "value",
        axisLabel: { ...CHART_TEXT, formatter: (x: number) => fmtInt(x) },
        splitLine: { lineStyle: { color: "#EEF0F3" } },
      },
      series: [
        { name: "MODIS raw", type: "line", data: h.modis_raw, symbol: "none", lineStyle: { color: C.modis, width: 2, type: "dashed" }, itemStyle: { color: C.modis } },
        { name: "VIIRS raw", type: "line", data: h.viirs_raw, symbol: "none", lineStyle: { color: C.viirs, width: 2 }, itemStyle: { color: C.viirs } },
        { name: "Harmonized", type: "line", data: h.harmonized, symbol: "none", z: 5, lineStyle: { color: C.harm, width: 3 }, itemStyle: { color: C.harm } },
      ],
    }),
    [h],
  );

  return (
    <section className="card harm-card" aria-labelledby="harm-title">
      <div>
        <div className="card-head">
          <h2 className="card-title" id="harm-title">
            Harmonization check · {h.span} of each year, {first}–{last}
          </h2>
          <div className="card-meta">
            Fit: <b>R² = {fmtNum(h.r2, 2)}</b> · average error ±{fmtNum(h.avg_error_pct, 0)}%
          </div>
        </div>
        <EChart option={option} height={240} label={`Line chart: ${h.span} totals per year for MODIS raw, VIIRS raw and harmonized`} />
        <div className="chart-legend">
          <span className="legend-key">
            <i className="key-dash" /> MODIS raw
          </span>
          <span className="legend-key">
            <i className="key-line" style={{ background: C.viirs }} /> VIIRS raw
          </span>
          <span className="legend-key">
            <i className="key-line thick" style={{ background: C.harm }} /> Harmonized
          </span>
        </div>
        {h.check_scope && (
          <p className="card-foot">
            Fit checked by leaving one year out ({y0}–{y1}) for {h.check_scope}. Same months each year so {last} compares fairly.
          </p>
        )}
      </div>
      <div className="harm-steps">
        <h3>How the two satellites are combined</h3>
        <ol>
          <li>Keep vegetation fires with nominal or high confidence.</li>
          <li>Snap both sensors to the same 1 km grid; one fire cell counts once per day.</li>
          <li>Match MODIS to VIIRS: same cell (±1 km) and same overpass (±1 h) = same fire, counted once.</li>
          <li>Keep MODIS-only fires (VIIRS missed them, e.g. cloud edge or gap).</li>
          <li>
            Fit the VIIRS ÷ MODIS ratio (≈ {fmtNum(h.k)}) on {y0}–{y1} to fill days VIIRS has no data.
          </li>
        </ol>
      </div>
    </section>
  );
}
