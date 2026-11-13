// Alerts: what to do, where first (docs/visual.md page 4, docs/screens/alerts.png).
import { useEffect, useMemo, useState } from "react";
import { Card, Skeleton } from "../components/ui";
import {
  alertsInSelection,
  countLevels,
  growthText,
  issuedText,
  lastCheckText,
  levelKey,
  priorityLabel,
  reasonBars,
  sortAlerts,
  timeBadge,
} from "../lib/alerts";
import { useAppData } from "../lib/appData";
import { useJSON } from "../lib/data";
import { fmtLatLon, fmtPct, vsUsualNote } from "../lib/format";
import type { AlertRecord, Alerts, Level, LevelCounts } from "../lib/types";
import { usePrintMode } from "../lib/printMode";
import { selectionDoc } from "../lib/selection";
import { filterActions, useFilters } from "../store/filters";

const TEXT_ON: Record<keyof LevelCounts, string> = {
  critical: "var(--critical-text)",
  high: "var(--high-text)",
  moderate: "var(--moderate-text)",
  low: "var(--low-text)",
};
/** Level colour as text on white (yellow needs a darker shade for 4.5:1). */
const TEXT_COLOUR: Record<keyof LevelCounts, string> = {
  critical: "#b91c1c",
  high: "#c2410c",
  moderate: "#854d0e",
  low: "#15803d",
};

function LevelBadge(props: { level: Level; long?: boolean }) {
  const k = levelKey(props.level.name);
  return (
    <span className="level-badge" style={{ background: props.level.colour, color: TEXT_ON[k] }}>
      {props.long ? `LEVEL ${props.level.level} · ${props.level.name.toUpperCase()}` : props.level.name.toUpperCase()}
    </span>
  );
}

export function AlertsPage() {
  const { places, bands } = useAppData();
  const f = useFilters();
  const doc = useJSON<Alerts>("alerts.json");
  const [levelFilter, setLevelFilter] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const inArea = useMemo(
    () => sortAlerts(alertsInSelection(doc.data?.alerts ?? [], f, places)),
    [doc.data, f, places],
  );
  const shown = levelFilter === null ? inArea : inArea.filter((a) => a.level === levelFilter);
  const selected = shown.find((a) => a.id === selectedId) ?? shown[0] ?? null;
  const counts = countLevels(inArea);
  const levels = [...bands.levels].sort((a, b) => b.level - a.level);
  const where = selectionDoc(f, places).name;

  useEffect(() => setLevelFilter(null), [f.area, f.place]);

  if (doc.error) return <main className="page"><div className="error-box">Could not load alerts: {doc.error}</div></main>;
  if (!doc.data) {
    return (
      <main className="page" aria-busy="true">
        <div className="main-col">
          <Skeleton height={150} />
          <Skeleton height={120} />
          <Skeleton height={420} />
        </div>
        <div className="side">
          <Skeleton height={230} />
          <Skeleton height={400} />
        </div>
      </main>
    );
  }
  const filterName = levelFilter === null ? null : levels.find((l) => l.level === levelFilter)?.name;

  return (
    <main className="page alerts-page">
      <div className="main-col">
        {doc.data.mode && doc.data.mode !== "model" && (
          <p className="mode-banner">
            Compared-to-normal fallback: the 72-hour System model did not beat both baselines, so the chance of
            spreading comes from compared to normal.
          </p>
        )}
        {selected ? (
          <AlertDetail a={selected} levels={levels} />
        ) : (
          <Card title={`No active alerts in ${where}`} labelledBy="no-alerts">
            <p className="hint">
              {levelFilter !== null
                ? `No ${filterName} alerts here. Tap the highlighted level again to see every level.`
                : f.area !== "borneo" || f.place
                  ? "Nothing in this selection needs action now. Try Whole Borneo, or check the Map for Watch hotspots."
                  : "No fire events need action now. Isolated hotspots are on the Map as Watch."}
            </p>
            {(f.area !== "borneo" || f.place) && (
              <button type="button" className="btn" style={{ marginTop: 12 }} onClick={() => filterActions.setArea("borneo")}>
                Show Whole Borneo
              </button>
            )}
          </Card>
        )}
        {doc.data.is_sample ? <p className="foot-note">Sample data: synthetic detections, not real fires.</p> : null}
      </div>

      <div className="side">
        <Card title="Status summary · tap to filter" labelledBy="status-title">
          <div className="status-tiles">
            {levels.map((l) => {
              const k = levelKey(l.name);
              const on = levelFilter === l.level;
              return (
                <button
                  key={l.level}
                  type="button"
                  className={`status-tile ${k}${on ? " selected" : ""}`}
                  aria-pressed={on}
                  onClick={() => setLevelFilter(on ? null : l.level)}
                >
                  <i style={{ background: l.colour }} aria-hidden="true" />
                  <span>{l.name}</span>
                  <b>{counts[k]}</b>
                </button>
              );
            })}
          </div>
        </Card>

        <section aria-labelledby="list-title">
          <h2 className="list-title" id="list-title">
            Active alerts · {filterName ?? "all levels"} · ranked by rescue priority
          </h2>
          {shown.length === 0 ? (
            <p className="hint">No alerts in this list.</p>
          ) : (
            <ul className="alert-list">
              {shown.map((a) => {
                const l = levels.find((x) => x.level === a.level)!;
                const p = priorityLabel(a);
                const isSel = selected?.id === a.id;
                return (
                  <li key={a.id}>
                    <button
                      type="button"
                      className={`alert-item${isSel ? " selected" : ""}`}
                      aria-pressed={isSel}
                      onClick={() => setSelectedId(a.id)}
                    >
                      <span className="alert-item-main">
                        <span className="alert-item-top">
                          <LevelBadge level={l} />
                          <b>{a.district}</b>
                        </span>
                        <span className="alert-item-sub">
                          {a.province} · {fmtLatLon(a.lat, a.lon, 2)}
                        </span>
                      </span>
                      <span className="alert-item-right">
                        <b style={{ color: a.priority ? TEXT_COLOUR.critical : undefined }}>{p.main}</b>
                        <small>{p.sub}</small>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}

/** PDF report: status summary and a ranked list, then every active alert in the selection in full. */
export function AlertsReport() {
  const { places, bands } = useAppData();
  const f = useFilters();
  const doc = useJSON<Alerts>("alerts.json");
  const inArea = useMemo(() => sortAlerts(alertsInSelection(doc.data?.alerts ?? [], f, places)), [doc.data, f, places]);
  const levels = [...bands.levels].sort((a, b) => b.level - a.level);
  const where = selectionDoc(f, places).name;

  if (doc.error) return <p className="error-box">Could not load alerts: {doc.error}</p>;
  if (!doc.data) return <Skeleton height={400} />;
  const counts = countLevels(inArea);

  return (
    <>
      {doc.data.mode && doc.data.mode !== "model" && (
        <p className="mode-banner">
          Compared-to-normal fallback: the 72-hour System model did not beat both baselines, so the chance of spreading
          comes from compared to normal.
        </p>
      )}
      <Card title={`Status summary · ${where}`} labelledBy="rpt-status-title">
        <div className="status-tiles">
          {levels.map((l) => {
            const k = levelKey(l.name);
            return (
              <div key={l.level} className={`status-tile ${k}`}>
                <i style={{ background: l.colour }} aria-hidden="true" />
                <span>{l.name}</span>
                <b>{counts[k]}</b>
              </div>
            );
          })}
        </div>
        <p className="hint small">
          {inArea.length} active alert{inArea.length === 1 ? "" : "s"} in {where}
          .
        </p>
        {inArea.length > 0 && (
          <table className="rpt-alert-table">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Level</th>
                <th scope="col">District</th>
                <th scope="col">Province</th>
                <th scope="col">Lat, lon</th>
                <th scope="col">Rescue priority / risk score</th>
              </tr>
            </thead>
            <tbody>
              {inArea.map((a, i) => {
                const l = levels.find((x) => x.level === a.level)!;
                const p = priorityLabel(a);
                return (
                  <tr key={a.id}>
                    <td className="mono">{i + 1}</td>
                    <td>
                      <LevelBadge level={l} />
                    </td>
                    <td>
                      <b>{a.district}</b>
                    </td>
                    <td>{a.province}</td>
                    <td className="mono">{fmtLatLon(a.lat, a.lon, 2)}</td>
                    <td>
                      {p.main} <small className="hint">{p.sub}</small>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
      {doc.data.is_sample ? <p className="foot-note">Sample data: synthetic detections, not real fires.</p> : null}
      {inArea.length === 0 && (
        <Card title={`No active alerts in ${where}`} labelledBy="rpt-no-alerts">
          <p className="hint">Nothing in this selection needs action now. Isolated hotspots are on the Map as Watch.</p>
        </Card>
      )}
      {inArea.map((a, i) => (
        <article key={a.id} className="rpt-alert" aria-label={`Alert ${i + 1} of ${inArea.length}: ${a.district}`}>
          <div className="rpt-alert-count">
            Alert {i + 1} of {inArea.length}
          </div>
          <AlertDetail a={a} levels={levels} />
        </article>
      ))}
    </>
  );
}

function AlertDetail(props: { a: AlertRecord; levels: Level[] }) {
  const { bands } = useAppData();
  const print = usePrintMode();
  const a = props.a;
  const l = props.levels.find((x) => x.level === a.level)!;
  const k = levelKey(l.name);
  const anomalyTone = a.anomaly_pct === null ? "" : a.anomaly_pct > 0 ? "up" : "down";
  const bars = reasonBars(a.reasons);
  const arrive = a.resources.arrive_within_h;

  return (
    <>
      <section className="alert-head card" style={{ borderTopColor: l.colour }} aria-labelledby="alert-title">
        <div className="alert-head-main">
          <div className="alert-head-meta">
            <LevelBadge level={l} long />
            <span className="mono">{a.id}</span>
            <span>
              {a.status}
              {a.status === "Notified" ? " · waiting for response" : ""}
            </span>
          </div>
          <h1 className="alert-title" id="alert-title">
            {a.district}, {a.province}
          </h1>
          <p className="alert-coords mono">
            {fmtLatLon(a.lat, a.lon, 2)} · {a.country} · issued {issuedText(a)}
          </p>
          <p className="alert-directive" style={{ color: TEXT_COLOUR[k] }}>
            {a.directive}
          </p>
          {a.overrides.length > 0 && <p className="hint small">Safety rule applied: {a.overrides.join("; ")}.</p>}
        </div>
        {!print && <NotifyButton alertId={a.id} />}
      </section>

      <div className="alert-tiles">
        <div className="alert-tile">
          <div className="tile-label">Hotspots in 24 h</div>
          <div className="alert-tile-value">{Number.isInteger(a.hotspots_24h) ? a.hotspots_24h : a.hotspots_24h.toFixed(1)}</div>
          <div className="tile-note">{growthText(a)}</div>
        </div>
        <div className="alert-tile">
          <div className="tile-label">Compared to normal</div>
          <div className={`alert-tile-value ${anomalyTone}`}>{a.anomaly_label ?? fmtPct(a.anomaly_pct)}</div>
          <div className="tile-note">{vsUsualNote(a.anomaly_status)}</div>
        </div>
        <div className="alert-tile">
          <div className="tile-label">Chance of spreading</div>
          <div className="alert-tile-value">
            {Math.round(a.chance_72h_pct)}% <small>{a.chance_word?.toLowerCase()}</small>
          </div>
          <div className="tile-note">
            72-hour system outlook{a.chance_source === "fallback" ? " · from compared to normal" : ""}
          </div>
        </div>
        {a.priority ? (
          <div className="alert-tile critical">
            <div className="tile-label">Rescue priority</div>
            <div className="alert-tile-value up">
              P{a.priority.rank} · {a.priority.share_pct}%
            </div>
            <div className="tile-note">share of rescue teams · priority score {a.priority.priority}/100</div>
          </div>
        ) : (
          <div className="alert-tile">
            <div className="tile-label">Risk score</div>
            <div className="alert-tile-value">
              {a.score}
              <small> / 100</small>
            </div>
            <div className="tile-note">
              Level {l.level} {l.name} band · rescue priority is for Critical alerts
            </div>
          </div>
        )}
      </div>

      <Card title="Situation report" labelledBy="report-title" meta="generated by the System from satellite data and fixed rules">
        <dl className="report">
          <dt>Situation</dt>
          <dd>{a.report.situation}</dd>
          <dt>Assessment</dt>
          <dd>{a.report.assessment}</dd>
          <dt>Recommendation</dt>
          <dd>{a.report.recommendation}</dd>
        </dl>
      </Card>

      <Card title="Why the System expects spreading" labelledBy="why-title">
        {a.reasons.length ? (
          <>
            <div className="reason-head">
              <span>Each input's effect on the 72-hour outlook, in percentage points from the average cell</span>
              <span>
                <i className="key raises" /> raises · <i className="key lowers" /> lowers
              </span>
            </div>
            <ul className="reasons">
              {a.reasons.map((r, i) => (
                <li key={r.feature}>
                  <span className="reason-label">{r.label}</span>
                  <span className="reason-value mono">{String(r.value)}</span>
                  <span className="reason-track">
                    <span className={`reason-bar ${bars[i].raises ? "raises" : "lowers"}`} style={{ width: `${bars[i].width}%` }} />
                  </span>
                  <span className={`reason-pct mono ${bars[i].raises ? "raises" : "lowers"}`}>{bars[i].text}</span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="hint">
            Compared-to-normal fallback: the chance comes from how far this month is above normal ({a.anomaly_status ?? "no usual"}
            ), not from the model, so there are no input effects to show.
          </p>
        )}
        <p className="hint small check-line">{lastCheckText(a, bands.check_words)}</p>
      </Card>

      <Card title="Recommended actions" labelledBy="actions-title">
        <div className="table-scroll">
          <table className="actions-table">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Action</th>
                <th scope="col">Why</th>
              </tr>
            </thead>
            <tbody>
              {a.actions.map((x, i) => {
                const t = timeBadge(x.when);
                return (
                  <tr key={i}>
                    <td>
                      <span className={`time-badge ${t.tone}`}>{t.text}</span>
                    </td>
                    <td className="action-cell">{x.action}</td>
                    <td className="why-cell">{x.why}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="two-col">
        <Card title="Resources to deploy" labelledBy="res-title">
          <table className="res-table">
            <thead className="visually-hidden">
              <tr>
                <th scope="col">Resource</th>
                <th scope="col">Quantity</th>
                <th scope="col">Arrive within</th>
              </tr>
            </thead>
            <tbody>
              {a.resources.rows.map((r) => (
                <tr key={r.name}>
                  <td>{r.name}</td>
                  <td className="mono qty">{r.qty}</td>
                  <td className="arrive">
                    {/cloud seeding/i.test(r.name) ? "if clouds ≥ 40%" : arrive ? `≤ ${arrive} h` : "when needed"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {a.resources.notes.length > 0 && <p className="hint small">{a.resources.notes.join(" · ")}</p>}
        </Card>
        <Card title="Coordination" labelledBy="coord-title">
          <ul className="coord">
            <li>
              Jurisdiction: {a.province}, {a.country}
            </li>
            <li>
              Lead agency: <b>{a.coordination.lead}</b>
            </li>
            <li>Support: {a.coordination.support}</li>
            <li>Also inform: {a.coordination.also_inform.length ? a.coordination.also_inform.join("; ") : "–"}</li>
            <li>Duty officer: {a.coordination.duty_officer ?? "–"}</li>
            <li>
              Notification: {a.coordination.channel}
              {a.coordination.if_no_response !== "none" ? ` · ${a.coordination.if_no_response}` : ""}
            </li>
            <li>
              Teams within 50 km:{" "}
              {a.nearby_teams.length ? a.nearby_teams.map((t) => `${t.town} (${t.km.toFixed(0)} km)`).join(", ") : "none listed"}
            </li>
          </ul>
        </Card>
      </div>
    </>
  );
}

type NotifyState =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "done"; mode: string; message?: string; note?: string; recipients?: string[] }
  | { kind: "error"; text: string };

function NotifyButton(props: { alertId: string }) {
  const [s, setS] = useState<NotifyState>({ kind: "idle" });
  useEffect(() => setS({ kind: "idle" }), [props.alertId]);

  async function send() {
    setS({ kind: "busy" });
    try {
      const r = await fetch("/api/notify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ alert_id: props.alertId }),
      });
      const js = await r.json().catch(() => null);
      if (!r.ok || !js?.ok) {
        setS({ kind: "error", text: js?.error ?? `The notify service answered HTTP ${r.status}.` });
        return;
      }
      setS({ kind: "done", mode: js.mode, message: js.message, note: js.note, recipients: js.recipients });
    } catch {
      setS({ kind: "error", text: "Could not reach the notify service (it runs on Vercel, `vercel dev` or `npm run dev`)." });
    }
  }

  return (
    <div className="notify">
      <button type="button" className="btn btn-critical" onClick={send} disabled={s.kind === "busy"}>
        {s.kind === "busy" ? "Sending…" : "Notify nearby teams"}
      </button>
      {s.kind === "done" && (
        <div className={`notify-result ${s.mode}`} role="status">
          <b>{s.mode === "demo" ? "Demo mode" : "Sent"}</b> {s.note}
          {s.recipients && <div className="small">To: {s.recipients.join(", ")}</div>}
          {s.message && (
            <details>
              <summary>Message</summary>
              <pre>{s.message}</pre>
            </details>
          )}
        </div>
      )}
      {s.kind === "error" && (
        <div className="notify-result error" role="alert">
          {s.text}
        </div>
      )}
    </div>
  );
}
