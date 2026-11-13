// Top-bar "Data status": coloured dot + "Live data · updated HH:MM" (MYT); click for where the data comes from.
// Every value comes from meta.json (written by the pipeline). The FIRMS key is never in meta.json: "API key active"
// only means the last fetch with it succeeded.
import { useEffect, useId, useRef, useState } from "react";
import { useAppData } from "../lib/appData";
import { dataStatus, type StatusTone } from "../lib/dataStatus";
import { fmtAtOffset, fmtInt } from "../lib/format";

const SOURCE_NAMES: Record<string, string> = {
  VIIRS_NOAA20_NRT: "VIIRS NOAA-20",
  VIIRS_NOAA21_NRT: "VIIRS NOAA-21",
  VIIRS_SNPP_NRT: "VIIRS S-NPP",
  MODIS_NRT: "MODIS (Terra, Aqua)",
};
const TONE_WORDS: Record<StatusTone, string> = {
  green: "up to date",
  amber: "last update is old",
  red: "last fetch failed",
  grey: "sample data",
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2017-01-01" -> "1 Jan 2017". */
function fmtDay(d: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : d;
}

export function DataStatusButton() {
  const { meta, mytOffset } = useAppData();
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const wrap = useRef<HTMLDivElement>(null);
  const popId = useId();

  // Re-check the age every minute so green turns amber without a reload.
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => wrap.current && !wrap.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const s = dataStatus(meta, now);
  const myt = (iso: string | null | undefined) => (iso ? `${fmtAtOffset(new Date(iso), mytOffset)} MYT` : "–");
  const hhmm = meta.api_last_success ? fmtAtOffset(new Date(meta.api_last_success), mytOffset).slice(-5) : null;
  const long = meta.is_sample ? "Sample data" : hhmm ? `Live data · updated ${hhmm}` : "Live data · not updated yet";
  const short = meta.is_sample ? "Sample" : "Live";
  const rows = Object.entries(meta.api_rows_by_source ?? {});
  const range = meta.archive_range;

  return (
    <div className="data-status" ref={wrap}>
      <button
        type="button"
        className="btn data-status-btn"
        aria-expanded={open}
        aria-controls={popId}
        aria-label={`Data status: ${long}, ${TONE_WORDS[s.tone]}`}
        onClick={() => setOpen((o) => !o)}
      >
        <i className={`status-dot ${s.tone}`} aria-hidden="true" />
        <span className="data-status-long">{long}</span>
        <span className="data-status-short">{short}</span>
      </button>
      {open && (
        <div className="data-status-pop" id={popId} role="dialog" aria-label="Data status">
          <section>
            <h3>10-year archive</h3>
            <dl>
              <dt>Dates</dt>
              <dd>
                {range ? `${fmtDay(range[0])} – ${fmtDay(range[1])}` : "–"}
                {range && meta.archive_through && meta.archive_through < range[1] && (
                  <small className="hint">
                    {" "}
                    (science-quality to {fmtDay(meta.archive_through)}, near-real-time after)
                  </small>
                )}
              </dd>
              <dt>Detections</dt>
              <dd className="mono">{fmtInt(meta.archive_rows)}</dd>
              <dt>Source</dt>
              <dd>
                {meta.archive_is_real ? (
                  <span className="ok">✓ real NASA FIRMS archive files</span>
                ) : (
                  <span className="fail">✗ sample data, not the real archive</span>
                )}
              </dd>
            </dl>
          </section>
          <section>
            <h3>Live NASA FIRMS</h3>
            <dl>
              <dt>Last fetch</dt>
              <dd>
                {myt(meta.api_last_attempt)}{" "}
                {meta.api_ok === true ? (
                  <span className="ok">✓ API key active</span>
                ) : meta.api_ok === false ? (
                  <span className="fail">✗ failed</span>
                ) : null}
              </dd>
              {meta.api_ok === false && meta.api_error && (
                <>
                  <dt>Reason</dt>
                  <dd className="fail">{meta.api_error}</dd>
                </>
              )}
              {meta.api_ok === false && (
                <>
                  <dt>Last success</dt>
                  <dd>{myt(meta.api_last_success)}</dd>
                </>
              )}
              <dt>New detections</dt>
              <dd>
                {rows.length ? (
                  <ul className="data-status-rows">
                    {rows.map(([src, n]) => (
                      <li key={src}>
                        {SOURCE_NAMES[src] ?? src} <b className="mono">{fmtInt(n)}</b>
                      </li>
                    ))}
                  </ul>
                ) : (
                  "–"
                )}
              </dd>
            </dl>
            {meta.api_note && <p className="hint small">{meta.api_note}</p>}
          </section>
          <section>
            <h3>Newest detection</h3>
            <p>{myt(meta.newest_detection)}</p>
          </section>
          <section>
            <h3>Data sources</h3>
            <ul className="data-status-sources">
              {meta.sources.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}
