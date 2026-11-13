// Calendar: when do fires happen? Heatmap 10 years × 12 months, yearly bars, seasonal summary, selected year.
import { useMemo, useState } from "react";
import { type ChartEvent, CHART_MONO, CHART_TEXT, EChart, type EChartsOption, TOOLTIP_STYLE } from "../components/EChart";
import { Card, Skeleton, StatTile } from "../components/ui";
import { useAppData } from "../lib/appData";
import { usePrintMode } from "../lib/printMode";
import { cellTooltip, fmtRatio } from "../lib/charts";
import { useJSON } from "../lib/data";
import { fmtInt, fmtPct, monthName } from "../lib/format";
import { selectionDoc } from "../lib/selection";
import type { AreaDoc, CalendarData } from "../lib/types";
import { useFilters } from "../store/filters";

const CELL_ROW = 34; // 30 px cell + 4 px gap (visual.md)
const OUTLINE = "#111827";
const SELECTED_ROW = "#FFF1EB";
const FUTURE_BORDER = "#C5CAD1";

export function CalendarPage() {
  const f = useFilters();
  const { places } = useAppData();
  const sel = selectionDoc(f, places);
  const { data, error } = useJSON<AreaDoc>(sel.file);
  const [picked, setPicked] = useState<number | null>(null);

  const cal = data?.calendar;
  const year =
    cal && picked !== null && cal.years.includes(picked)
      ? picked
      : (cal?.facts.record_year?.year ?? cal?.years[cal.years.length - 1] ?? null);

  return (
    <main className="page">
      <div className="main-col">
        <Card
          labelledBy="cal-title"
          className="cal-card"
          title={
            <span className="page-card-title">
              Burning activity calendar · {sel.name}
            </span>
          }
        >
          <p className="card-sub">
            Harmonized hotspots per month, last 10 years ({cal ? `${cal.years[0]}–${cal.years[cal.years.length - 1]}` : "…"}) · click
            a year to see its details · hover a cell for its total
            {sel.note && <span className="data-note"> · {sel.note}</span>}
          </p>
          {error ? (
            <p className="hint">Could not load the calendar ({error}).</p>
          ) : !cal ? (
            <Skeleton height={470} />
          ) : (
            <Heatmap cal={cal} year={year} onYear={setPicked} />
          )}
        </Card>
        <Card title="Hotspots per year" labelledBy="bars-title">
          {!cal ? <Skeleton height={260} /> : <YearBars cal={cal} year={year} onYear={setPicked} />}
        </Card>
      </div>
      <div className="side">
        {!cal ? (
          <>
            <Skeleton height={520} />
            <Skeleton height={160} />
          </>
        ) : (
          <>
            <SeasonCard cal={cal} />
            {year !== null && <SelectedYearCard cal={cal} year={year} />}
          </>
        )}
      </div>
    </main>
  );
}

/** PDF report: the same heatmap, yearly bars and seasonal summary, without year selection. */
export function CalendarReport() {
  const f = useFilters();
  const { places } = useAppData();
  const sel = selectionDoc(f, places);
  const { data, error } = useJSON<AreaDoc>(sel.file);
  const cal = data?.calendar;
  const noop = () => {};
  if (error) return <p className="error-box">Could not load the calendar ({error}).</p>;
  return (
    <>
      <Card labelledBy="rpt-cal-title" className="cal-card" title={`Burning activity calendar · ${sel.name}`}>
        <p className="card-sub">
          Harmonized hotspots per month, last 10 years ({cal ? `${cal.years[0]}–${cal.years[cal.years.length - 1]}` : "…"})
          {sel.note && <span className="data-note"> · {sel.note}</span>}
        </p>
        {!cal ? <Skeleton height={470} /> : <Heatmap cal={cal} year={null} onYear={noop} />}
      </Card>
      <Card title="Hotspots per year" labelledBy="rpt-bars-title">
        {!cal ? <Skeleton height={260} /> : <YearBars cal={cal} year={null} onYear={noop} />}
      </Card>
      {!cal ? <Skeleton height={420} /> : <SeasonCard cal={cal} />}
    </>
  );
}

function Heatmap(props: { cal: CalendarData; year: number | null; onYear: (y: number) => void }) {
  const { bands, meta } = useAppData();
  const print = usePrintMode();
  const { cal, year } = props;
  const ramp = bands.calendar_ramp;
  const [y0, y1] = cal.usual_years ?? meta.data_window.median_years;
  const nYears = cal.years.length;
  const rows = [...cal.years.map(String), " ", "Usual"];
  const usualRow = nYears + 1;

  const option = useMemo<EChartsOption>(() => {
    const items: object[] = [];
    const selRow = year === null ? -1 : cal.years.indexOf(year);
    if (selRow >= 0) items.push({ value: [0, selRow, 0, 0, 0, 4] }); // tint behind the selected year
    cal.rows.forEach((r, yi) =>
      r.cells.forEach((c, mi) =>
        items.push({
          value: [mi, yi, c?.count ?? 0, c?.bin ?? 0, c?.unusual ? 1 : 0, c ? 0 : 2],
          tip: cellTooltip(mi + 1, r.year, c),
        }),
      ),
    );
    items.push({ value: [0, nYears, 0, 0, 0, 3] }); // divider above the Usual row
    cal.usual.forEach((u, mi) =>
      items.push({
        value: [mi, usualRow, u.count, u.bin, 0, 0],
        tip: `Usual ${monthName(mi + 1)}: ${fmtInt(u.count)} hotspots (median ${y0}–${y1})`,
      }),
    );
    const totals = [...cal.rows.map((r) => fmtInt(r.total)), "", "median"];
    const isSel = (v: string) => year !== null && v === String(year);
    return {
      animation: false,
      grid: { left: 50, right: 62, top: 26, bottom: 2 },
      tooltip: { ...TOOLTIP_STYLE, formatter: (p: { data: { tip?: string } }) => p.data?.tip ?? "" },
      xAxis: {
        type: "category",
        position: "top",
        data: cal.months,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { ...CHART_TEXT, margin: 8 },
      },
      yAxis: [
        {
          type: "category",
          inverse: true,
          z: 10,
          data: rows,
          triggerEvent: true,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            align: "left",
            margin: 46,
            formatter: (v: string) => (isSel(v) ? `{sel|${v}}` : v === "Usual" ? `{usual|${v}}` : `{yr|${v}}`),
            rich: {
              yr: { ...CHART_MONO, color: "#111827" },
              sel: { ...CHART_MONO, color: "#C2410C", fontWeight: 700 },
              usual: { ...CHART_TEXT, color: "#111827", fontWeight: 700 },
            },
          },
        },
        {
          type: "category",
          inverse: true,
          z: 10,
          position: "right",
          data: rows,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            formatter: (_: string, i: number) => totals[i] ?? "",
            align: "right",
            margin: 60,
            ...CHART_MONO,
            fontSize: 12.5,
            rich: {},
          },
        },
      ],
      series: [
        {
          type: "custom",
          z: 1,
          data: items,
          renderItem: (
            params: { coordSys: { x: number; width: number } },
            api: { value: (i: number) => number; coord: (v: number[]) => number[]; size: (v: number[]) => number[] },
          ) => {
            const [cx, cy] = api.coord([api.value(0), api.value(1)]);
            const state = api.value(5);
            const [w, h] = api.size([1, 1]);
            if (state === 3 || state === 4) {
              const { x, width } = params.coordSys;
              return state === 3
                ? {
                    type: "line",
                    silent: true,
                    shape: { x1: x - 46, y1: cy, x2: x + width + 60, y2: cy },
                    style: { stroke: "#E3E6EA", lineWidth: 1 },
                  }
                : {
                    type: "rect",
                    silent: true,
                    shape: { x: x - 50, y: cy - h / 2, width: width + 112, height: h, r: 4 },
                    style: { fill: SELECTED_ROW },
                  };
            }
            const gap = 4;
            const shape = { x: cx - w / 2 + gap / 2, y: cy - h / 2 + gap / 2, width: w - gap, height: h - gap, r: 3 };
            if (state === 2) {
              return { type: "rect", shape, style: { fill: "#FFFFFF", stroke: FUTURE_BORDER, lineWidth: 1, lineDash: [4, 3] } };
            }
            const unusual = api.value(4) === 1;
            return {
              type: "rect",
              shape,
              style: {
                fill: ramp[Math.min(ramp.length - 1, Math.max(0, api.value(3)))],
                stroke: unusual ? OUTLINE : null,
                lineWidth: unusual ? 2 : 0,
              },
            };
          },
        },
      ],
    };
  }, [cal, year, ramp, nYears, usualRow, y0, y1]);

  const onClick = (e: ChartEvent) => {
    const y = Number(e.componentType === "yAxis" ? e.value : cal.years[e.data?.value?.[1]]);
    if (cal.years.includes(y)) props.onYear(y);
  };

  return (
    <>
      {!print && <p className="hint phone-only">Swipe sideways to see all 12 months →</p>}
      <div className="chart-scroll">
        <div style={{ minWidth: 640 }}>
          <EChart
            option={option}
            height={26 + rows.length * CELL_ROW + 4}
            label={`Calendar heatmap of hotspots per month, ${cal.years[0]} to ${cal.years[nYears - 1]}`}
            onClick={onClick}
          />
        </div>
      </div>
      {!print && (
        <div className="cal-years" role="group" aria-label="Choose a year">
          {cal.years.map((y) => (
            <button key={y} type="button" aria-pressed={y === year} onClick={() => props.onYear(y)}>
              {y}
            </button>
          ))}
        </div>
      )}
      <div className="cal-legend">
        <span>Low</span>
        <span className="ramp" aria-hidden="true">
          {ramp.map((c) => (
            <i key={c} style={{ background: c }} />
          ))}
        </span>
        <span>Extreme</span>
        <span className="legend-key">
          <i className="key-outline" aria-hidden="true" /> outlined = unusual (≥ {bands.unusual_month_ratio}× usual)
        </span>
        <span className="legend-key">
          <i className="key-future" aria-hidden="true" /> no data yet
        </span>
      </div>
    </>
  );
}

function YearBars(props: { cal: CalendarData; year: number | null; onYear: (y: number) => void }) {
  const { bands } = useAppData();
  const { cal, year } = props;
  const ramp = bands.calendar_ramp;
  const record = ramp[ramp.length - 1];
  const normal = ramp[ramp.length - 3];
  const perYear = new Map(cal.per_year.map((p) => [p.year, p]));

  const option = useMemo<EChartsOption>(
    () => ({
      animation: false,
      grid: { left: 4, right: 4, top: 26, bottom: 24 },
      tooltip: {
        ...TOOLTIP_STYLE,
        trigger: "item",
        formatter: (p: { dataIndex: number }) => {
          const t = cal.yearly_totals[p.dataIndex];
          const vs = perYear.get(t.year)?.vs_avg_pct;
          return `${t.year}${t.so_far ? " so far" : ""}: ${fmtInt(t.total)} hotspots${
            vs === null || vs === undefined || t.so_far ? "" : ` (${fmtPct(vs)} vs average year)`
          }${t.record ? " · record year" : ""}`;
        },
      },
      xAxis: {
        type: "category",
        data: cal.yearly_totals.map((t) => (t.so_far ? `${t.year}*` : String(t.year))),
        axisLine: { lineStyle: { color: "#E3E6EA" } },
        axisTick: { show: false },
        axisLabel: { ...CHART_TEXT, color: "#111827", fontSize: 12.5 },
      },
      yAxis: { type: "value", show: false },
      series: [
        {
          type: "bar",
          barCategoryGap: "10%",
          label: { show: true, position: "top", ...CHART_MONO, color: "#374151", formatter: (p: { value: number }) => fmtInt(p.value) },
          data: cal.yearly_totals.map((t) => {
            const picked = t.year === year;
            const base = t.so_far
              ? { color: "rgba(244,135,75,0.18)", borderColor: normal, borderType: "dashed", borderWidth: 1 }
              : { color: t.record ? record : normal };
            return {
              value: t.total,
              itemStyle: picked ? { ...base, borderColor: OUTLINE, borderWidth: 2, borderType: "solid" } : base,
            };
          }),
        },
      ],
    }),
    [cal, year, record, normal],
  );

  return (
    <EChart
      option={option}
      height={260}
      label="Bar chart of hotspots per year"
      onClick={(e) => e.dataIndex !== undefined && props.onYear(cal.yearly_totals[e.dataIndex].year)}
    />
  );
}

function SeasonCard(props: { cal: CalendarData }) {
  const { cal } = props;
  const fs = cal.fire_season;
  const fx = cal.facts;
  const [y0, y1] = cal.usual_years;
  const so = fx.so_far_vs_prev;
  return (
    <Card title="Seasonal summary" labelledBy="season-title">
      <div className="season-box">
        <div className="season-kicker">FIRE SEASON</div>
        <div className="season-label">{fs.label ?? "No clear season"}</div>
        <div className="season-text">
          {fs.label && fs.share_pct !== null
            ? `${Math.round(fs.share_pct)}% of each year's hotspots fall in these months`
            : "No month stands out from the rest of the year."}
        </div>
      </div>
      <div className="tiles tiles-2">
        <StatTile
          label="Record year"
          value={fx.record_year ? `${fx.record_year.year} · ${fmtInt(fx.record_year.total)}` : "–"}
          note="most hotspots"
          tone="up"
        />
        <StatTile
          label="Quietest year"
          value={fx.quietest_year ? `${fx.quietest_year.year} · ${fmtInt(fx.quietest_year.total)}` : "–"}
          note="fewest hotspots"
          tone="down"
        />
        <StatTile
          label="Peak month"
          value={fx.peak_month ? monthName(fx.peak_month.month) : "–"}
          note={fx.peak_month ? `usual ${fmtInt(fx.peak_month.usual)} hotspots` : undefined}
        />
        <StatTile
          label="Quietest month"
          value={fx.quietest_month ? monthName(fx.quietest_month.month) : "–"}
          note={fx.quietest_month ? `usual ${fmtInt(fx.quietest_month.usual)} hotspots` : undefined}
        />
        <StatTile
          label="Average per year"
          value={fmtInt(fx.average_per_year)}
          note={`full years ${y0}–${y1} · ${y1 + 1} in progress`}
        />
        <StatTile
          label={so ? `${so.year} so far vs ${so.prev}` : "This year so far"}
          value={fmtPct(so?.pct)}
          note={so ? `${so.span}, same months` : undefined}
          tone={so?.pct ? (so.pct > 0 ? "up" : "down") : undefined}
        />
        <StatTile
          label="Unusual months"
          value={fmtInt(fx.unusual_months.count)}
          note={fx.unusual_months.latest ? `latest: ${fx.unusual_months.latest}` : "none"}
        />
        <StatTile
          label="Peak vs quiet month"
          value={fx.season_strength === null ? "–" : fmtRatio(fx.season_strength)}
          note={fx.season_strength === null ? "quietest usual month is 0" : "how strong the season is"}
        />
      </div>
    </Card>
  );
}

function SelectedYearCard(props: { cal: CalendarData; year: number }) {
  const p = props.cal.per_year.find((x) => x.year === props.year);
  if (!p) return null;
  return (
    <Card title={`Selected year · ${p.year}${p.so_far ? " (so far)" : ""}`} labelledBy="year-title" highlight>
      <div className="year-grid">
        <div>
          <div className="tile-label">Total hotspots</div>
          <div className="year-big">{fmtInt(p.total)}</div>
        </div>
        <div>
          <div className="tile-label">vs average year</div>
          <div className={`year-big ${p.vs_avg_pct === null ? "" : p.vs_avg_pct > 0 ? "up" : "down"}`}>
            {fmtPct(p.vs_avg_pct)}
          </div>
        </div>
        <div>
          <div className="tile-label">Peak month</div>
          <div className="year-small">{p.peak_month ? monthName(p.peak_month) : "–"}</div>
        </div>
        <div>
          <div className="tile-label">Unusual months</div>
          <div className="year-small">{p.unusual_months}</div>
        </div>
      </div>
    </Card>
  );
}
