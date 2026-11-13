// Files every page needs, loaded once in App and shared through context.
import { createContext, useContext } from "react";
import type { Bands, Boundaries, Meta, PlacesDoc } from "./types";

export interface AppData {
  meta: Meta;
  bands: Bands;
  places: PlacesDoc;
  boundaries: Boundaries;
  /** MYT offset from UTC in hours (read from meta.json). */
  mytOffset: number;
}

export const AppDataContext = createContext<AppData | null>(null);

export function useAppData(): AppData {
  const d = useContext(AppDataContext);
  if (!d) throw new Error("useAppData outside AppDataContext");
  return d;
}
