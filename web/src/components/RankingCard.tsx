import { useState } from "react";
import { useAppData } from "../lib/appData";
import { useJSON } from "../lib/data";
import { fmtInt, shortProvince } from "../lib/format";
import type { Ranking, RankingRow } from "../lib/types";
import { ALL_AREAS } from "../store/filters";
import { Card, SegmentedControl, Skeleton } from "./ui";

type Order = "most" | "fewest";
export type When = "now" | "month" | "year";

const RANKING_TITLES: Record<When, string> = {
  now: "Current Time Hotspot Ranking",
  month: "This Month Hotspot Ranking",
  year: "This Year Hotspot Ranking",
};

/** Top 5 districts for the order/period switches, within the selected area. */
export function topDistricts(rows: RankingRow[], area: string, order: Order, when: When, n = 5): RankingRow[] {
  const inArea = area === ALL_AREAS ? rows : rows.filter((r) => r.province === area);
  const sign = order === "most" ? -1 : 1;
  return [...inArea].sort((a, b) => sign * (a[when] - b[when]) || a.name.localeCompare(b.name)).slice(0, n);
}

/** fixedWhen (PDF report): one period, most hotspots, no switches. */
export function RankingCard(props: { area: string; fixedWhen?: When }) {
  const { places } = useAppData();
  const { data, error } = useJSON<Ranking>("ranking.json");
  const [order, setOrder] = useState<Order>("most");
  const [pickedWhen, setWhen] = useState<When>("now");
  const when = props.fixedWhen ?? pickedWhen;
  const areaName = places.areas.find((a) => a.id === props.area)?.name ?? "";

  let body;
  if (error) body = <p className="hint">Could not load the ranking ({error}).</p>;
  else if (!data) body = <Skeleton height={230} />;
  else {
    const rows = topDistricts(data.districts, props.area, order, when);
    const max = Math.max(1, ...rows.map((r) => r[when]));
    body =
      rows.length === 0 ? (
        <p className="hint">No districts in this area.</p>
      ) : (
        <ol className={`rank-list ${order}`}>
          {rows.map((r, i) => (
            <li key={r.district} className="rank-row">
              <span className="rank-badge">{i + 1}</span>
              <span style={{ minWidth: 0 }}>
                <div className="rank-name">{r.name}</div>
                <div className="rank-prov">{shortProvince(r.province_name)}</div>
              </span>
              <span className="rank-bar" aria-hidden="true">
                <span style={{ width: `${(100 * r[when]) / max}%` }} />
              </span>
              <span className="rank-count">{fmtInt(r[when])}</span>
            </li>
          ))}
        </ol>
      );
  }

  const whenWords = data ? data.periods[when] : "";
  return (
    <Card
      title={RANKING_TITLES[when]}
      meta="top 5 districts"
      labelledBy="ranking-title"
      foot={
        data &&
        `${order === "most" ? "Most" : "Fewest"} hotspots by district · ${whenWords} · ${
          props.area === ALL_AREAS ? "whole Borneo" : areaName
        }`
      }
    >
      {!props.fixedWhen && (
      <div className="ranking-switches">
        <SegmentedControl
          small
          label="Ranking order"
          value={order}
          onChange={setOrder}
          options={[
            { id: "most", label: "Most hotspots" },
            { id: "fewest", label: "Fewest hotspots" },
          ]}
        />
        <SegmentedControl
          small
          label="Ranking period"
          value={when}
          onChange={setWhen}
          options={[
            { id: "now", label: "Current" },
            { id: "month", label: "This month" },
            { id: "year", label: "This year" },
          ]}
        />
      </div>
      )}
      {body}
    </Card>
  );
}
