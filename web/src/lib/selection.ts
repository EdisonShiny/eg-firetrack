// Which area/{id}.json file the Calendar and Analysis pages show for the current Area / Place.
import { ALL_AREAS, type Filters, parsePoint } from "../store/filters";
import { fmtLatLon } from "./format";
import type { PlacesDoc } from "./types";

export interface Selection {
  file: string;
  /** Name in page titles ("Central Kalimantan", "Miri"). */
  name: string;
  /** Small grey note under the title, or null. */
  note: string | null;
}

/** Preset place -> its own file; typed point -> the province it falls in; else the Area (Whole Borneo by default). */
export function selectionDoc(f: Filters, places: PlacesDoc): Selection {
  const preset = f.place ? places.places.find((p) => p.id === f.place) : undefined;
  if (preset) {
    const area = places.areas.find((a) => a.id === preset.area);
    return {
      file: `area/${preset.id}.json`,
      name: preset.name,
      note: `District around ${preset.name}${area ? `, ${area.name}` : ""}`,
    };
  }
  const area = places.areas.find((a) => a.id === f.area) ?? places.areas.find((a) => a.id === ALL_AREAS);
  const id = area?.id ?? ALL_AREAS;
  const name = area?.name ?? "Whole Borneo";
  const pt = f.place ? parsePoint(f.place) : null;
  return {
    file: `area/${id}.json`,
    name,
    note: pt ? `History of ${name}, the area that contains ${fmtLatLon(pt.lat, pt.lon, 2)}` : null,
  };
}
