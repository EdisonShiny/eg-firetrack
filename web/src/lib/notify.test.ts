// Tests web/api/notify.ts (the Vercel function) without HTTP.
import { describe, expect, it, vi } from "vitest";
import handler, { buildMessage, notify, type NotifyAlert } from "../../api/notify";
import { alert } from "./fixtures";

const a = alert({ nearby_teams: [{ town: "Palangka Raya", km: 12.3, team: "Response team based in Palangka Raya" }] }) as unknown as NotifyAlert;
const doc = { is_sample: true, alerts: [a] };

function deps(env: Record<string, string | undefined> = {}, fetchFn = vi.fn()) {
  return { env, loadAlerts: async () => doc, fetchFn: fetchFn as unknown as typeof fetch };
}

describe("notify", () => {
  it("demo mode without Telegram env vars: nothing sent, message returned", async () => {
    const f = vi.fn();
    const r = await notify({ alert_id: a.id }, deps({}, f));
    expect(r.status).toBe(200);
    expect(r.body.mode).toBe("demo");
    expect(r.body.note).toContain("demo mode");
    expect(r.body.recipients).toContain("BPBD Central Kalimantan");
    expect(f).not.toHaveBeenCalled();
  });

  it("only token or only chat id is still demo mode", async () => {
    expect((await notify({ alert_id: a.id }, deps({ TELEGRAM_BOT_TOKEN: "x" }))).body.mode).toBe("demo");
    expect((await notify({ alert_id: a.id }, deps({ TELEGRAM_CHAT_ID: "1" }))).body.mode).toBe("demo");
  });

  it("sends to Telegram when both env vars are set", async () => {
    const f = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    const r = await notify({ alert_id: a.id }, deps({ TELEGRAM_BOT_TOKEN: "T0K", TELEGRAM_CHAT_ID: "-100" }, f));
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ ok: true, mode: "telegram" });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("https://api.telegram.org/botT0K/sendMessage");
    const sent = JSON.parse(init.body);
    expect(sent.chat_id).toBe("-100");
    expect(sent.text).toContain("P1 · 20% of rescue teams");
  });

  it("a Telegram failure never leaks the token", async () => {
    const f = vi.fn().mockResolvedValue({ ok: false, status: 401 });
    const r = await notify({ alert_id: a.id }, deps({ TELEGRAM_BOT_TOKEN: "SECRET", TELEGRAM_CHAT_ID: "1" }, f));
    expect(r.status).toBe(502);
    expect(JSON.stringify(r.body)).not.toContain("SECRET");
  });

  it("rejects bad or unknown alert ids", async () => {
    expect((await notify({}, deps())).status).toBe(400);
    expect((await notify({ alert_id: "../../etc" }, deps())).status).toBe(400);
    expect((await notify({ alert_id: "EV-00000000-999" }, deps())).status).toBe(404);
  });

  it("message: level, place, numbers, priority, sample label", () => {
    const m = buildMessage(a, { isSample: true, siteUrl: "https://x.app" });
    expect(m).toContain("[SAMPLE DATA – EXERCISE] EG FireTrack · LEVEL 4 · CRITICAL");
    expect(m).toContain("Kapuas, Central Kalimantan, Indonesia (2.35° S, 114.35° E)");
    expect(m).toContain("41 hotspots in 24 h · chance of spreading 83% (Very likely) · risk score 85/100");
    expect(m).toContain("Rescue priority P1 · 20% of rescue teams");
    expect(m).toContain("Teams within 50 km: Palangka Raya");
    expect(m).toContain("https://x.app/alerts");
    expect(m).not.toMatch(/\bAI\b/);
  });

  it("the HTTP handler only accepts POST", async () => {
    const res = { code: 0, body: null as unknown, status(c: number) { this.code = c; return this; },
      setHeader: vi.fn(), json(b: unknown) { this.body = b; } };
    await handler({ method: "GET", headers: {} }, res);
    expect(res.code).toBe(405);
  });
});
