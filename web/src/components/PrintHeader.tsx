// Shown only when printing ("PDF report"): what the report covers, when, and how honest the data is.
import { useLocation } from "react-router-dom";
import { useAppData } from "../lib/appData";
import { pageOf } from "../lib/csv";
import { fmtMytText } from "../lib/format";
import { selectionDoc } from "../lib/selection";
import { useFilters } from "../store/filters";

const PAGE_TITLE = {
  map: "Map · where are the fires?",
  calendar: "Calendar · when do fires happen?",
  analysis: "Analysis · past → now → next",
  alerts: "Alerts · what to do, where first",
};
const PERIOD = { current: "Current (24 h)", "7d": "7 days", "30d": "30 days", "12m": "12 months", "5y": "5 years", all: "All" };

export function PrintHeader() {
  const { meta } = useAppData();
  const { places } = useAppData();
  const f = useFilters();
  const page = pageOf(useLocation().pathname);
  const sel = selectionDoc(f, places);
  return (
    <div className="print-header" aria-hidden="true">
      <img src="/brand/logo-full.jpg" alt="" className="print-logo" />
      <div className="print-title">EG FireTrack report · {PAGE_TITLE[page]}</div>
      <div>
        Selection: <b>{sel.name}</b>
        {sel.note ? ` (${sel.note})` : ""} · Period: {PERIOD[f.period]} · Data through {fmtMytText(meta.data_through_myt)}{" "}
        MYT · Printed {new Date().toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}
      </div>
      <div className="print-note">
        {meta.is_sample ? "SAMPLE DATA: synthetic detections, not real fires. " : ""}
        Results labelled System come from EG FireTrack's models and fixed rules; the agency in charge decides.
        Powered by EG Solution 2.0 Team · NASA FIRMS (MODIS, VIIRS).
      </div>
    </div>
  );
}
