// Vercel serverless function: POST /api/notify {"alert_id": "EV-20261108-001"}
// "Notify nearby teams": sends the alert to the lead agency and teams within 50 km.
// This build sends ONE Telegram message to TELEGRAM_CHAT_ID (the duty channel) using
// TELEGRAM_BOT_TOKEN. Without both env vars it returns mode "demo" with the message it would send.
// The alert is read from the site's own /data/alerts.json, so a caller cannot inject message text.
// Self-contained on purpose (no relative imports), so Vercel's ESM runtime loads it as is.
// The same `notify()` core runs in `npm run dev` / `npm run preview` (vite.config.ts) and in tests.

declare const process: { env: Record<string, string | undefined> };

export interface NotifyAlert {
  id: string;
  level: number;
  level_name: string;
  directive: string;
  place: string;
  country: string;
  lat: number;
  lon: number;
  hotspots_24h: number;
  chance_72h_pct: number;
  chance_word: string | null;
  score: number;
  priority: { rank: number; share_pct: number } | null;
  coordination: { lead: string; support: string; also_inform: string[]; channel: string };
  nearby_teams: { town: string; km: number; team: string }[];
  report?: { situation: string };
}

export interface NotifyResult {
  ok: boolean;
  mode: "demo" | "telegram";
  message?: string;
  recipients?: string[];
  note?: string;
  error?: string;
  sent_at?: string;
}

export interface NotifyDeps {
  env: Record<string, string | undefined>;
  loadAlerts: () => Promise<{ alerts?: NotifyAlert[]; is_sample?: boolean }>;
  fetchFn: typeof fetch;
  siteUrl?: string;
}

const ID_RE = /^[A-Za-z0-9-]{1,40}$/;

function latLon(lat: number, lon: number): string {
  return `${Math.abs(lat).toFixed(2)}° ${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(2)}° ${lon >= 0 ? "E" : "W"}`;
}

export function recipients(a: NotifyAlert): string[] {
  const c = a.coordination;
  return [c.lead, c.support, ...c.also_inform, ...a.nearby_teams.map((t) => `${t.team} (${t.km.toFixed(0)} km)`)];
}

export function buildMessage(a: NotifyAlert, opts: { isSample?: boolean; siteUrl?: string } = {}): string {
  const lines = [
    `${opts.isSample ? "[SAMPLE DATA – EXERCISE] " : ""}EG FireTrack · LEVEL ${a.level} · ${a.level_name.toUpperCase()}`,
    `${a.place}, ${a.country} (${latLon(a.lat, a.lon)})`,
    `${a.hotspots_24h} hotspots in 24 h · chance of spreading ${Math.round(a.chance_72h_pct)}%` +
      `${a.chance_word ? ` (${a.chance_word})` : ""} · risk score ${a.score}/100`,
  ];
  if (a.priority) lines.push(`Rescue priority P${a.priority.rank} · ${a.priority.share_pct}% of rescue teams`);
  lines.push(a.directive);
  lines.push(`Lead: ${a.coordination.lead} · Support: ${a.coordination.support}`);
  if (a.coordination.also_inform.length) lines.push(`Also inform: ${a.coordination.also_inform.join(", ")}`);
  if (a.nearby_teams.length) lines.push(`Teams within 50 km: ${a.nearby_teams.map((t) => t.town).join(", ")}`);
  lines.push(`Alert ${a.id}. System recommendation; the agency in charge decides.`);
  if (opts.siteUrl) lines.push(`${opts.siteUrl}/alerts`);
  return lines.join("\n");
}

/** The whole logic, without HTTP: returns the status code and the JSON answer. */
export async function notify(body: unknown, deps: NotifyDeps): Promise<{ status: number; body: NotifyResult }> {
  const token = deps.env.TELEGRAM_BOT_TOKEN?.trim();
  const chat = deps.env.TELEGRAM_CHAT_ID?.trim();
  const mode: NotifyResult["mode"] = token && chat ? "telegram" : "demo";
  const id = (body as { alert_id?: unknown } | null)?.alert_id;
  if (typeof id !== "string" || !ID_RE.test(id)) {
    return { status: 400, body: { ok: false, mode, error: "alert_id is missing or not valid" } };
  }
  let doc: Awaited<ReturnType<NotifyDeps["loadAlerts"]>>;
  try {
    doc = await deps.loadAlerts();
  } catch {
    return { status: 502, body: { ok: false, mode, error: "could not read alerts.json" } };
  }
  const alert = (doc.alerts ?? []).find((a) => a.id === id);
  if (!alert) return { status: 404, body: { ok: false, mode, error: `no active alert ${id}` } };

  const message = buildMessage(alert, { isSample: doc.is_sample, siteUrl: deps.siteUrl });
  const to = recipients(alert);
  if (mode === "demo") {
    return {
      status: 200,
      body: {
        ok: true, mode, message, recipients: to,
        note: "demo mode: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set, so nothing was sent.",
      },
    };
  }
  try {
    const r = await deps.fetchFn(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chat, text: message, disable_web_page_preview: true }),
    });
    if (!r.ok) {
      // Never echo Telegram's answer or the URL: both could carry the token.
      return { status: 502, body: { ok: false, mode, error: `Telegram refused the message (HTTP ${r.status})` } };
    }
  } catch {
    return { status: 502, body: { ok: false, mode, error: "Telegram could not be reached" } };
  }
  return {
    status: 200,
    body: {
      ok: true, mode, message, recipients: to, sent_at: new Date().toISOString(),
      note: "Sent to the Telegram duty channel.",
    },
  };
}

// --------------------------------------------------------------------------- Vercel handler
interface Req {
  method?: string;
  body?: unknown;
  headers: Record<string, string | string[] | undefined>;
}
interface Res {
  status: (code: number) => Res;
  setHeader: (name: string, value: string) => void;
  json: (body: unknown) => void;
}

function header(req: Req, name: string): string | undefined {
  const v = req.headers[name];
  return Array.isArray(v) ? v[0] : v;
}

export default async function handler(req: Req, res: Res): Promise<void> {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    res.status(405).json({ ok: false, error: "use POST" });
    return;
  }
  const host = header(req, "x-forwarded-host") ?? header(req, "host") ?? "";
  const proto = header(req, "x-forwarded-proto") ?? (host.startsWith("localhost") ? "http" : "https");
  const site = `${proto}://${host}`;
  let body = req.body;
  if (typeof body === "string") {
    try {
      body = JSON.parse(body);
    } catch {
      body = null;
    }
  }
  const out = await notify(body, {
    env: process.env,
    fetchFn: fetch,
    siteUrl: site,
    loadAlerts: async () => {
      const r = await fetch(`${site}/data/alerts.json`);
      if (!r.ok) throw new Error(`alerts.json HTTP ${r.status}`);
      return r.json();
    },
  });
  res.status(out.status).json(out.body);
}
