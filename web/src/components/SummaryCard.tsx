import type { ReactNode } from "react";
import { useAppData } from "../lib/appData";
import { useJSON } from "../lib/data";
import { fmtInt, fmtMytText, fmtNum, fmtPct, monthName, vsUsualNote } from "../lib/format";
import type { AreaDoc } from "../lib/types";
import type { Period } from "../store/filters";
import { Card, Skeleton, StatTile } from "./ui";

const PERIOD_WORDS: Record<Period, string> = {
  current: "last 24 h",
  "7d": "last 7 days",
  "30d": "last 30 days",
  "12m": "last 12 months",
  "5y": "last 5 years",
  all: "all years",
};

/** Which calendar window "Compared to normal" measured (bands.yaml compared_to_normal_rule). */
const WINDOW_WORDS: Record<string, string> = {
  current: "last 24 h",
  "7d": "last 7 days",
  "30d": "last 30 days",
  month: "this month",
  year: "this year",
};

/** Six summary tiles for one area/place file (area/{id}.json). */
export function SummaryCard(props: {
  file: string;
  title: ReactNode;
  meta?: ReactNode;
  highlight?: boolean;
  period: Period;
  showAsOf?: boolean;
  id: string;
}) {
  const { meta, bands } = useAppData();
  const { data, error } = useJSON<AreaDoc>(props.file);
  const through = /^(\d{4})-(\d{2})/.exec(meta.data_through_myt);
  const year = through ? Number(through[1]) : meta.data_window.current_year;
  const mon = through ? monthName(Number(through[2])) : "";
  const [y0, y1] = meta.data_window.median_years;

  let body: ReactNode;
  if (error) body = <p className="hint">Could not load the summary ({error}).</p>;
  else if (!data) body = <Skeleton height={172} />;
  else {
    const s = data.summary;
    const win = bands.compared_to_normal_rule?.map_period_window?.[props.period] ?? "month";
    const cmp = s.compared_to_normal_by_window?.[win] ?? s.compared_to_normal;
    const tone =
      cmp.pct === null ? undefined : cmp.pct < 0 ? "down" : cmp.status && cmp.status !== "Normal" ? "up" : undefined;
    const frp = s.avg_frp_by_period?.[props.period] ?? s.avg_frp;
    body = (
      <div className="tiles">
        <StatTile label="Now (last 24 h)" value={fmtInt(s.now)} note="latest pass" />
        <StatTile label="This month" value={fmtInt(s.month)} note={`${mon} ${year}`} />
        <StatTile label="This year" value={fmtInt(s.year)} note={`Jan–${mon} ${year}`} />
        <StatTile
          label="Yearly average"
          value={fmtInt(s.yearly_avg)}
          note={`full years ${y0}–${y1} · ${year} in progress`}
        />
        <StatTile
          label="Average FRP"
          value={frp === null ? "–" : `${fmtNum(frp)} MW`}
          note={`fire intensity · ${PERIOD_WORDS[props.period]}`}
        />
        <div title={`${WINDOW_WORDS[cmp.window ?? "month"] ?? ""}: ${cmp.basis ?? ""}`}>
          <StatTile
            label="Compared to normal"
            value={cmp.label ?? fmtPct(cmp.pct)}
            tone={tone}
            note={vsUsualNote(cmp.status)}
          />
        </div>
      </div>
    );
  }

  return (
    <Card
      title={props.title}
      labelledBy={props.id}
      highlight={props.highlight}
      metaAccent={props.highlight}
      meta={props.meta ?? (props.showAsOf ? `as of ${fmtMytText(meta.data_through_myt)}` : undefined)}
    >
      {body}
    </Card>
  );
}
