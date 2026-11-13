/// <reference types="vitest" />
import { readFile } from "node:fs/promises";
import type { IncomingMessage, ServerResponse } from "node:http";
import { resolve } from "node:path";
import { defineConfig, loadEnv, type Connect, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { notify } from "./api/notify";

/** Serves POST /api/notify in `npm run dev` / `npm run preview` with the same code as the Vercel
 *  function (web/api/notify.ts). Telegram keys come from the environment or the repo's .env;
 *  without them it answers in demo mode. */
function notifyApi(mode: string): Plugin {
  const env = { ...loadEnv(mode, resolve(__dirname, ".."), "TELEGRAM_"), ...process.env };
  const middleware =
    (dataDir: string): Connect.NextHandleFunction =>
    (req: IncomingMessage, res: ServerResponse, next) => {
      if (!req.url?.startsWith("/api/notify")) return next();
      const send = (status: number, body: unknown) => {
        res.statusCode = status;
        res.setHeader("Content-Type", "application/json");
        res.setHeader("Cache-Control", "no-store");
        res.end(JSON.stringify(body));
      };
      if (req.method !== "POST") return send(405, { ok: false, error: "use POST" });
      let raw = "";
      req.on("data", (c) => (raw += c));
      req.on("end", async () => {
        let body: unknown = null;
        try {
          body = JSON.parse(raw || "null");
        } catch {
          body = null;
        }
        const out = await notify(body, {
          env,
          fetchFn: fetch,
          siteUrl: `http://${req.headers.host ?? "localhost"}`,
          loadAlerts: async () => JSON.parse(await readFile(resolve(dataDir, "alerts.json"), "utf-8")),
        });
        send(out.status, out.body);
      });
    };
  return {
    name: "eg-notify-api",
    configureServer(server) {
      server.middlewares.use(middleware(resolve(__dirname, "public/data")));
    },
    configurePreviewServer(server) {
      server.middlewares.use(middleware(resolve(__dirname, "dist/data")));
    },
  };
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), notifyApi(mode)],
  build: {
    // ECharts (Calendar/Analysis only) gets its own lazily loaded chunk.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: (id) => (/node_modules[\/](echarts|zrender)[\/]/.test(id) ? "echarts" : undefined),
      },
    },
  },
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
}));
