import { MapView } from "../components/MapView";
import { RankingCard } from "../components/RankingCard";
import { SummaryCard } from "../components/SummaryCard";
import { Card } from "../components/ui";
import { useAppData } from "../lib/appData";
import { fmtLatLon } from "../lib/format";
import type { PlacesDoc } from "../lib/types";
import { ALL_AREAS, type Filters, parsePoint, useFilters } from "../store/filters";

/** Which file the "Summary · Selected" card shows: preset place -> its own file; typed point -> its province. */
export function selectedSummary(f: Filters, places: PlacesDoc): { file: string; title: string; meta: string } | null {
  const area = places.areas.find((a) => a.id === f.area);
  const preset = f.place ? places.places.find((p) => p.id === f.place) : undefined;
  const pt = !preset && f.place ? parsePoint(f.place) : null;
  if (preset) return { file: `area/${preset.id}.json`, title: `Summary · Selected: ${preset.name}`, meta: "from Area / Place" };
  if (pt && area) {
    return { file: `area/${area.id}.json`, title: `Summary · Selected: ${fmtLatLon(pt.lat, pt.lon, 2)}`, meta: `numbers for ${area.name}` };
  }
  if (area && area.id !== ALL_AREAS) return { file: `area/${area.id}.json`, title: `Summary · Selected: ${area.name}`, meta: "from Area / Place" };
  return null;
}

export function MapPage() {
  const f = useFilters();
  const { places } = useAppData();
  const selected = selectedSummary(f, places);

  return (
    <main className="page">
      <MapView filters={f} />
      <div className="side">
        <SummaryCard id="sum-borneo" file="area/borneo.json" title="Summary · Whole Borneo" period={f.period} showAsOf />
        {selected ? (
          <SummaryCard
            id="sum-selected"
            file={selected.file}
            title={selected.title}
            meta={selected.meta}
            period={f.period}
            highlight
          />
        ) : (
          <Card title="Summary · Selected area" labelledBy="sum-selected" highlight meta="from Area / Place" metaAccent>
            <p className="hint">Choose an Area or a Place above to compare it with the whole of Borneo.</p>
          </Card>
        )}
        <RankingCard area={f.area} />
      </div>
    </main>
  );
}
