// PDF report: a static hotspot map (canvas -> PNG) for the current Area / Place / Period.
// Same selection and dot rules as the live map, drawn without tiles so it always prints.
import { useEffect, useState } from "react";
import { useAppData } from "../lib/appData";
import { useJSON } from "../lib/data";
import { fmtInt, fmtLatLon } from "../lib/format";
import { frpClass, gridFile, pointsPeriod, selectCells, selectPoints } from "../lib/hotspots";
import type { BoundaryFeature, Grid, Hotspots } from "../lib/types";
import { ALL_AREAS, type Filters, type Period, parsePoint } from "../store/filters";
import { Skeleton } from "./ui";

const W = 700;
const H = 520;
const RATIO = 2;
const HOTSPOT = "#D7301F";
const SELECT = "#C2410C";
const PERIOD_WORDS: Record<Period, string> = {
  current: "last 24 h",
  "7d": "last 7 days",
  "30d": "last 30 days",
  "12m": "last 12 months",
  "5y": "last 5 years",
  all: "whole record",
};

type BBox = [number, number, number, number]; // w, s, e, n

function rings(f: BoundaryFeature): number[][][] {
  return f.geometry.type === "Polygon" ? f.geometry.coordinates : f.geometry.coordinates.flat();
}

function bboxOf(fs: BoundaryFeature[]): BBox {
  let [w, s, e, n] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const f of fs)
    for (const r of rings(f))
      for (const [lo, la] of r) {
        if (lo < w) w = lo;
        if (lo > e) e = lo;
        if (la < s) s = la;
        if (la > n) n = la;
      }
  return [w, s, e, n];
}

/** Grow a lat/lon box to the canvas aspect ratio (equirectangular, x scaled by cos(mid lat)). */
export function fitBox(b: BBox, width: number, height: number, pad = 0.06): { box: BBox; kx: number } {
  let [w, s, e, n] = b;
  const kx = Math.cos((((s + n) / 2) * Math.PI) / 180);
  const dx = Math.max(e - w, 0.05) * (1 + 2 * pad);
  const dy = Math.max(n - s, 0.05) * (1 + 2 * pad);
  const cx = (w + e) / 2;
  const cy = (s + n) / 2;
  let spanX = dx;
  let spanY = dy;
  if ((dx * kx) / dy > width / height) spanY = (dx * kx * height) / width;
  else spanX = (dy * width) / height / kx;
  w = cx - spanX / 2;
  e = cx + spanX / 2;
  s = cy - spanY / 2;
  n = cy + spanY / 2;
  return { box: [w, s, e, n], kx };
}

export function StaticMap(props: { filters: Filters }) {
  const f = props.filters;
  const { meta, bands, places, boundaries } = useAppData();
  const usePoints = pointsPeriod(f.period, meta, 30);
  const hotspots = useJSON<Hotspots>(usePoints ? "hotspots_30d.json" : null);
  const grid = useJSON<Grid>(usePoints ? null : gridFile(f.period));
  const radiusKm = places.custom_point_radius_km;
  const [img, setImg] = useState<{ src: string; shown: number } | null>(null);

  useEffect(() => {
    const h = hotspots.data;
    const g = grid.data;
    if (usePoints ? !h : !g) return;

    const provinces = boundaries.features.filter((ft) => ft.properties.level === "province");
    const preset = f.place ? places.places.find((p) => p.id === f.place) : undefined;
    const pt = !preset && f.place ? parsePoint(f.place) : null;
    const selFeat = preset
      ? boundaries.features.find((ft) => ft.properties.level === "district" && ft.properties.id === preset.district)
      : !pt && f.area !== ALL_AREAS
        ? provinces.find((ft) => ft.properties.id === f.area)
        : undefined;
    let target: BBox;
    if (pt) {
      const dLat = radiusKm / 111;
      const dLon = dLat / Math.cos((pt.lat * Math.PI) / 180);
      target = [pt.lon - dLon, pt.lat - dLat, pt.lon + dLon, pt.lat + dLat];
    } else if (selFeat) target = bboxOf([selFeat]);
    else {
      const [w, s, e, n] = places.areas[0].bbox;
      target = [w, s, e, n];
    }
    const { box, kx } = fitBox(target, W, H);
    const [bw, , be, bn] = box;
    const sx = W / ((be - bw) * kx);
    const X = (lon: number) => (lon - bw) * kx * sx;
    const Y = (lat: number) => (bn - lat) * sx;

    const canvas = document.createElement("canvas");
    canvas.width = W * RATIO;
    canvas.height = H * RATIO;
    const c = canvas.getContext("2d")!;
    c.scale(RATIO, RATIO);
    c.fillStyle = "#EAF1F7";
    c.fillRect(0, 0, W, H);

    const path = (ft: BoundaryFeature) => {
      c.beginPath();
      for (const r of rings(ft)) {
        r.forEach(([lo, la], i) => (i ? c.lineTo(X(lo), Y(la)) : c.moveTo(X(lo), Y(la))));
        c.closePath();
      }
    };
    // land + dashed province borders
    c.fillStyle = "#FBFAF6";
    provinces.forEach((ft) => (path(ft), c.fill("evenodd")));
    c.setLineDash([5, 4]);
    c.strokeStyle = "#8E6BB0";
    c.lineWidth = 1.1;
    provinces.forEach((ft) => (path(ft), c.stroke()));
    c.setLineDash([]);

    // graticule
    const span = box[2] - box[0];
    const step = span > 8 ? 2 : span > 3 ? 1 : 0.5;
    c.strokeStyle = "rgba(63,84,104,0.22)";
    c.lineWidth = 0.7;
    c.fillStyle = "#3F5468";
    c.font = "10px Inter, Segoe UI, sans-serif";
    for (let lo = Math.ceil(box[0] / step) * step; lo < box[2]; lo += step) {
      c.beginPath();
      c.moveTo(X(lo), 0);
      c.lineTo(X(lo), H);
      c.stroke();
      c.fillText(`${+lo.toFixed(1)}°E`, X(lo) + 3, 12);
    }
    for (let la = Math.ceil(box[1] / step) * step; la < box[3]; la += step) {
      c.beginPath();
      c.moveTo(0, Y(la));
      c.lineTo(W, Y(la));
      c.stroke();
      c.fillText(`${Math.abs(+la.toFixed(1))}°${la >= 0 ? "N" : "S"}`, 4, Y(la) - 3);
    }

    // selection outline
    c.strokeStyle = SELECT;
    c.fillStyle = "rgba(194,65,12,0.05)";
    c.lineWidth = 2.2;
    if (pt) {
      c.setLineDash([6, 4]);
      c.beginPath();
      c.ellipse(X(pt.lon), Y(pt.lat), (radiusKm / 111 / Math.cos((pt.lat * Math.PI) / 180)) * kx * sx, (radiusKm / 111) * sx, 0, 0, 2 * Math.PI);
      c.fill();
      c.stroke();
      c.setLineDash([]);
    } else if (selFeat) {
      path(selFeat);
      c.fill("evenodd");
      c.stroke();
    }

    // dots: small first so large fires stay on top
    let shown = 0;
    if (usePoints && h) {
      const idx = selectPoints(h, f, meta, places.places, radiusKm).sort((a, b) => h.frp[a] - h.frp[b]);
      const zoom = Math.min(1.6, Math.max(0.7, 10 / span));
      for (const i of idx) {
        const cls = frpClass(h.frp[i], bands.frp_dot_sizes_mw);
        c.beginPath();
        c.arc(X(h.lon[i]), Y(h.lat[i]), [2.2, 3.4, 5][cls] * zoom, 0, 2 * Math.PI);
        c.fillStyle = HOTSPOT;
        c.globalAlpha = 0.9;
        c.fill();
        c.globalAlpha = 1;
        c.lineWidth = cls === 2 ? 1.4 : 0.6;
        c.strokeStyle = cls === 2 ? "#1A0F06" : "#FFFFFF";
        c.stroke();
      }
      shown = idx.length;
    } else if (g) {
      const idx = selectCells(g, f, places.places, radiusKm).sort((a, b) => g.count[a] - g.count[b]);
      const max = Math.max(1, ...idx.map((i) => g.count[i]));
      for (const i of idx) {
        c.beginPath();
        c.arc(X(g.lon[i]), Y(g.lat[i]), 1.8 + 6.5 * Math.sqrt(g.count[i] / max), 0, 2 * Math.PI);
        c.fillStyle = HOTSPOT;
        c.globalAlpha = 0.75;
        c.fill();
        c.globalAlpha = 1;
        c.lineWidth = 0.6;
        c.strokeStyle = "#FFFFFF";
        c.stroke();
        shown += g.count[i];
      }
    }

    // town names when zoomed in enough to read them
    if (span <= 7) {
      c.font = "600 10.5px Inter, Segoe UI, sans-serif";
      c.lineJoin = "round";
      for (const p of places.places) {
        if (p.lon < box[0] || p.lon > box[2] || p.lat < box[1] || p.lat > box[3]) continue;
        const x = X(p.lon);
        const y = Y(p.lat);
        c.fillStyle = "#111827";
        c.beginPath();
        c.arc(x, y, 2.2, 0, 2 * Math.PI);
        c.fill();
        c.strokeStyle = "rgba(255,255,255,0.9)";
        c.lineWidth = 3;
        c.strokeText(p.name, x + 4, y - 4);
        c.fillText(p.name, x + 4, y - 4);
      }
    }

    c.strokeStyle = "#D1D5DB";
    c.lineWidth = 1;
    c.strokeRect(0.5, 0.5, W - 1, H - 1);
    setImg({ src: canvas.toDataURL("image/png"), shown });
  }, [usePoints, hotspots.data, grid.data, f, meta, bands, places, boundaries, radiusKm]);

  const err = hotspots.error ?? grid.error;
  if (err) return <p className="hint">Could not load hotspots ({err}).</p>;
  if (!img) return <Skeleton height={H} />;

  const sizes = bands.frp_dot_sizes_mw;
  const preset = f.place ? places.places.find((p) => p.id === f.place) : undefined;
  const pt = !preset && f.place ? parsePoint(f.place) : null;
  const scope = preset
    ? preset.name
    : pt
      ? `${radiusKm} km of ${fmtLatLon(pt.lat, pt.lon, 2)}`
      : (places.areas.find((a) => a.id === f.area)?.name ?? "Borneo");
  return (
    <figure className="rpt-map">
      <img src={img.src} alt={`Map of hotspots in ${scope}, ${PERIOD_WORDS[f.period]}`} />
      <figcaption className="chart-legend">
        <span>
          <b>{fmtInt(img.shown)}</b> hotspots in {scope} · {PERIOD_WORDS[f.period]}
        </span>
        {usePoints ? (
          <span>
            Dot size = fire intensity (FRP): &lt; {sizes.small_below} MW · {sizes.small_below}–{sizes.large_above} MW · &gt;{" "}
            {sizes.large_above} MW (dark ring)
          </span>
        ) : (
          <span>Dot size = hotspots per {grid.data?.cell_deg ?? 0.1}° cell (raw points only for ≤ 30 days)</span>
        )}
        <span>Orange outline = selection · dashed lines = province borders</span>
      </figcaption>
    </figure>
  );
}
