import { useEffect, useMemo, useRef, useState } from "react";
import L from "../lib/leafletSetup";
import "leaflet-draw";
import { useAppData } from "../lib/appData";
import { useJSON } from "../lib/data";
import { fmtAtOffset, fmtInt, fmtLatLon, fmtNum } from "../lib/format";
import { inLatLngRing } from "../lib/geo";
import { frpClass, gridFile, pointsPeriod, selectCells, selectPoints } from "../lib/hotspots";
import type { Grid, Hotspots } from "../lib/types";
import { ALL_AREAS, type Filters, type Period, parsePoint } from "../store/filters";

const TILES = {
  street: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  },
  satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
  },
};
type Basemap = keyof typeof TILES;

const BORNEO_BOUNDS = L.latLngBounds([-6.5, 106.5], [9.5, 121.5]); // maxBounds: Borneo + margin
const DOT_RADIUS = [3.5, 5.5, 8];
const HOTSPOT = "#D7301F";
const DARK = "#111827";
const PERIOD_WORDS: Record<Period, string> = {
  current: "last 24 h",
  "7d": "last 7 days",
  "30d": "last 30 days",
  "12m": "last 12 months",
  "5y": "last 5 years",
  all: "whole record",
};
const NEXT_PERIOD: Partial<Record<Period, string>> = {
  current: "Try 7 days.",
  "7d": "Try 30 days.",
  "30d": "Try 12 months.",
};
const SENSOR_RES: Record<string, string> = { VIIRS: "375 m", MODIS: "1 km" };

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}
function cap(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

function popupHtml(title: string, rows: [string, string, boolean?][]): string {
  return (
    `<p class="popup-title">${esc(title)}</p><dl class="popup-grid">` +
    rows
      .map(([k, v, bold]) => `<dt>${esc(k)}</dt><dd${k === "Lat, lon" ? ' class="mono"' : ""}>${bold ? `<strong>${esc(v)}</strong>` : esc(v)}</dd>`)
      .join("") +
    "</dl>"
  );
}

interface Props {
  filters: Filters;
}

export function MapView({ filters: f }: Props) {
  const { meta, bands, places, boundaries, mytOffset } = useAppData();
  const elRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const tilesRef = useRef<L.TileLayer | null>(null);
  const dotsRef = useRef<L.LayerGroup | null>(null);
  const selectionRef = useRef<L.LayerGroup | null>(null);
  const drawnRef = useRef<L.FeatureGroup | null>(null);
  const drawHandlerRef = useRef<L.Draw.Polygon | null>(null);
  const cursorRef = useRef<HTMLSpanElement>(null);
  const selectedDotRef = useRef<{ dot: L.CircleMarker; style: L.PathOptions } | null>(null);

  const [basemap, setBasemap] = useState<Basemap>("street");
  const [drawing, setDrawing] = useState(false);
  const [drawnRing, setDrawnRing] = useState<[number, number][] | null>(null);

  const usePoints = pointsPeriod(f.period, meta, 30);
  const hotspots = useJSON<Hotspots>(usePoints ? "hotspots_30d.json" : null);
  const grid = useJSON<Grid>(usePoints ? null : gridFile(f.period));
  const radiusKm = places.custom_point_radius_km;

  // ------------------------------------------------------------ map setup (once)
  useEffect(() => {
    if (!elRef.current) return;
    const map = L.map(elRef.current, {
      zoomControl: false,
      preferCanvas: true,
      maxBounds: BORNEO_BOUNDS,
      maxBoundsViscosity: 1,
      minZoom: 5,
      maxZoom: 14,
      attributionControl: false,
    });
    L.control
      .attribution({ position: "bottomright", prefix: "Borneo view for this competition · the system can run globally" })
      .addTo(map);
    const [w, s, e, n] = places.areas[0].bbox;
    map.fitBounds([
      [s, w],
      [n, e],
    ]);

    // Dashed country/province borders.
    L.geoJSON(boundaries as unknown as GeoJSON.GeoJsonObject, {
      filter: (ft) => ft.properties.level === "province",
      style: { color: "#8E6BB0", weight: 1.4, dashArray: "5 5", fill: false, opacity: 0.9 },
      interactive: false,
    }).addTo(map);

    // Lat/lon grid lines every 2° with edge labels.
    const grat = L.layerGroup().addTo(map);
    const lons = [109, 111, 113, 115, 117, 119];
    const lats = [-3, -1, 1, 3, 5, 7];
    const lineStyle = { color: "#3F5468", weight: 0.8, opacity: 0.35, interactive: false };
    lons.forEach((lo) => L.polyline([[-12, lo], [15, lo]], lineStyle).addTo(grat));
    lats.forEach((la) => L.polyline([[la, 100], [la, 128]], lineStyle).addTo(grat));
    const labels = L.layerGroup().addTo(map);
    const drawLabels = () => {
      labels.clearLayers();
      const b = map.getBounds();
      const pxTop = map.containerPointToLatLng([0, 12]).lat;
      const pxLeft = map.containerPointToLatLng([150, 0]).lng;
      lons
        .filter((lo) => lo > b.getWest() && lo < b.getEast())
        .forEach((lo) =>
          L.marker([pxTop, lo], {
            interactive: false,
            icon: L.divIcon({ className: "graticule-label", html: `${lo}°E`, iconSize: [40, 14], iconAnchor: [-4, 7] }),
          }).addTo(labels),
        );
      lats
        .filter((la) => la > b.getSouth() && la < b.getNorth())
        .forEach((la) =>
          L.marker([la, pxLeft], {
            interactive: false,
            icon: L.divIcon({
              className: "graticule-label",
              html: `${Math.abs(la)}°${la >= 0 ? "N" : "S"}`,
              iconSize: [30, 14],
              iconAnchor: [0, 16],
            }),
          }).addTo(labels),
        );
    };
    map.on("moveend zoomend resize", drawLabels);
    drawLabels();

    // Town names (also needed on the satellite view).
    const towns = L.layerGroup().addTo(map);
    places.places.forEach((p) =>
      L.marker([p.lat, p.lon], {
        interactive: false,
        keyboard: false,
        icon: L.divIcon({ className: "town-label", html: esc(p.name), iconSize: undefined, iconAnchor: [4, 8] }),
      }).addTo(towns),
    );

    selectionRef.current = L.layerGroup().addTo(map);
    dotsRef.current = L.layerGroup().addTo(map);
    drawnRef.current = new L.FeatureGroup().addTo(map);

    map.on("mousemove", (ev: L.LeafletMouseEvent) => {
      if (cursorRef.current) cursorRef.current.textContent = fmtLatLon(ev.latlng.lat, ev.latlng.lng);
    });
    map.on(L.Draw.Event.CREATED, (ev) => {
      const layer = (ev as L.DrawEvents.Created).layer as L.Polygon;
      drawnRef.current!.clearLayers();
      layer.setStyle({ color: DARK, weight: 2, dashArray: "6 4", fillOpacity: 0.06 });
      drawnRef.current!.addLayer(layer);
      const ring = (layer.getLatLngs()[0] as L.LatLng[]).map((p) => [p.lat, p.lng] as [number, number]);
      setDrawnRing(ring);
      setDrawing(false);
    });
    map.on(L.Draw.Event.DRAWSTOP, () => setDrawing(false));
    map.on("popupclose", () => {
      const sel = selectedDotRef.current;
      if (sel) sel.dot.setStyle(sel.style);
      selectedDotRef.current = null;
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [boundaries, places]);

  // ------------------------------------------------------------ basemap
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    tilesRef.current?.remove();
    const t = TILES[basemap];
    tilesRef.current = L.tileLayer(t.url, { attribution: t.attribution, maxZoom: 19 }).addTo(map);
    tilesRef.current.bringToBack();
  }, [basemap]);

  // ------------------------------------------------------------ selection outline + zoom
  useEffect(() => {
    const map = mapRef.current;
    const sel = selectionRef.current;
    if (!map || !sel) return;
    sel.clearLayers();
    const outline = { color: "#C2410C", weight: 2.5, fill: true, fillColor: "#C2410C", fillOpacity: 0.04, interactive: false };
    const preset = f.place ? places.places.find((p) => p.id === f.place) : undefined;
    const pt = !preset && f.place ? parsePoint(f.place) : null;
    let bounds: L.LatLngBounds | null = null;
    if (pt) {
      const c = L.circle([pt.lat, pt.lon], { radius: radiusKm * 1000, ...outline, dashArray: "6 4" }).addTo(sel);
      L.circleMarker([pt.lat, pt.lon], { radius: 4, color: "#fff", weight: 1.5, fillColor: DARK, fillOpacity: 1 }).addTo(sel);
      bounds = c.getBounds();
    } else {
      const feat = preset
        ? boundaries.features.find((ft) => ft.properties.level === "district" && ft.properties.id === preset.district)
        : f.area !== ALL_AREAS
          ? boundaries.features.find((ft) => ft.properties.level === "province" && ft.properties.id === f.area)
          : undefined;
      if (feat) bounds = L.geoJSON(feat as unknown as GeoJSON.GeoJsonObject, { style: outline }).addTo(sel).getBounds();
    }
    if (!bounds) {
      const [w, s, e, n] = places.areas[0].bbox;
      bounds = L.latLngBounds([s, w], [n, e]);
    }
    map.flyToBounds(bounds, { padding: [30, 30], duration: 0.6, maxZoom: 11 });
  }, [f.area, f.place, boundaries, places, radiusKm]);

  // ------------------------------------------------------------ dots
  const selection = useMemo(() => {
    if (usePoints && hotspots.data) return { kind: "points" as const, idx: selectPoints(hotspots.data, f, meta, places.places, radiusKm) };
    if (!usePoints && grid.data) return { kind: "cells" as const, idx: selectCells(grid.data, f, places.places, radiusKm) };
    return null;
  }, [usePoints, hotspots.data, grid.data, f, meta, places, radiusKm]);

  useEffect(() => {
    const map = mapRef.current;
    const layer = dotsRef.current;
    if (!map || !layer) return;
    layer.clearLayers();
    map.closePopup();
    if (!selection) return;
    const sizes = bands.frp_dot_sizes_mw;
    if (selection.kind === "points" && hotspots.data) {
      const h = hotspots.data;
      const base = Date.parse(h.base_time_utc);
      // small dots first so large fires stay on top
      const order = [...selection.idx].sort((a, b) => h.frp[a] - h.frp[b]);
      for (const i of order) {
        const cls = frpClass(h.frp[i], sizes);
        const style: L.CircleMarkerOptions = {
          radius: DOT_RADIUS[cls],
          color: cls === 2 ? "#1A0F06" : "#FFFFFF",
          weight: cls === 2 ? 2 : 1,
          fillColor: HOTSPOT,
          fillOpacity: 0.95,
        };
        const dot = L.circleMarker([h.lat[i], h.lon[i]], style).addTo(layer);
        dot.on("click", () => {
          const prev = selectedDotRef.current;
          if (prev) prev.dot.setStyle(prev.style);
          dot.setStyle({ color: DARK, weight: 3.5 });
          dot.bringToFront();
          selectedDotRef.current = { dot, style };
          const satName = h.satellites[h.sat[i]];
          const sensor = h.sensor_of_satellite[satName] ?? satName;
          const html = popupHtml("Hotspot details", [
            ["Lat, lon", fmtLatLon(h.lat[i], h.lon[i])],
            ["Detected", `${fmtAtOffset(new Date(base + h.t[i] * 60_000), mytOffset)} MYT`],
            ["Sensor", `${sensor} (${satName}${SENSOR_RES[sensor] ? ", " + SENSOR_RES[sensor] : ""})`],
            ["FRP", `${fmtNum(h.frp[i])} MW`, true],
            ["Confidence", cap(h.confidence[h.conf[i]] ?? "")],
            ["Brightness", `${Math.round(h.bright[i])} K`],
          ]);
          L.popup({ offset: [0, -4], maxWidth: 320, autoPanPadding: [40, 40] })
            .setLatLng([h.lat[i], h.lon[i]])
            .setContent(html)
            .openOn(map);
        });
      }
    } else if (selection.kind === "cells" && grid.data) {
      const g = grid.data;
      const max = Math.max(1, ...selection.idx.map((i) => g.count[i]));
      const order = [...selection.idx].sort((a, b) => g.count[a] - g.count[b]);
      for (const i of order) {
        const style: L.CircleMarkerOptions = {
          radius: 3 + 9 * Math.sqrt(g.count[i] / max),
          color: "#FFFFFF",
          weight: 1,
          fillColor: HOTSPOT,
          fillOpacity: 0.8,
        };
        const dot = L.circleMarker([g.lat[i], g.lon[i]], style).addTo(layer);
        dot.on("click", () => {
          const prev = selectedDotRef.current;
          if (prev) prev.dot.setStyle(prev.style);
          dot.setStyle({ color: DARK, weight: 3 });
          selectedDotRef.current = { dot, style };
          const html = popupHtml(`Hotspots in this ${g.cell_deg}° cell`, [
            ["Cell centre", fmtLatLon(g.lat[i], g.lon[i], 2)],
            ["Period", PERIOD_WORDS[f.period]],
            ["Hotspots", fmtInt(g.count[i]), true],
            ["Average FRP", `${fmtNum(g.frp[i])} MW`],
            ["District", g.districts[g.district[i]] ?? "–"],
          ]);
          L.popup({ offset: [0, -4], maxWidth: 320 }).setLatLng([g.lat[i], g.lon[i]]).setContent(html).openOn(map);
        });
      }
    }
  }, [selection, hotspots.data, grid.data, bands, mytOffset, f.period]);

  // ------------------------------------------------------------ drawn area summary
  const drawnSummary = useMemo(() => {
    if (!drawnRing || !selection) return null;
    if (selection.kind === "points" && hotspots.data) {
      const h = hotspots.data;
      const inside = selection.idx.filter((i) => inLatLngRing(h.lat[i], h.lon[i], drawnRing));
      return { count: inside.length, maxFrp: inside.length ? Math.max(...inside.map((i) => h.frp[i])) : null };
    }
    if (selection.kind === "cells" && grid.data) {
      const g = grid.data;
      const inside = selection.idx.filter((i) => inLatLngRing(g.lat[i], g.lon[i], drawnRing));
      return { count: inside.reduce((s, i) => s + g.count[i], 0), maxFrp: null };
    }
    return null;
  }, [drawnRing, selection, hotspots.data, grid.data]);

  function toggleDraw() {
    const map = mapRef.current;
    if (!map) return;
    if (drawing) {
      drawHandlerRef.current?.disable();
      setDrawing(false);
      return;
    }
    drawHandlerRef.current = new L.Draw.Polygon(map as L.DrawMap, {
      showArea: false,
      shapeOptions: { color: DARK, weight: 2 },
    });
    drawHandlerRef.current.enable();
    setDrawing(true);
  }

  function clearDrawn() {
    drawnRef.current?.clearLayers();
    setDrawnRing(null);
  }

  function resetView() {
    const map = mapRef.current;
    if (!map) return;
    const [w, s, e, n] = places.areas[0].bbox;
    map.flyToBounds([[s, w], [n, e]], { duration: 0.6 });
  }

  // ------------------------------------------------------------ render
  const loading = usePoints ? !hotspots.data && !hotspots.error : !grid.data && !grid.error;
  const loadError = hotspots.error ?? grid.error;
  const preset = f.place ? places.places.find((p) => p.id === f.place) : undefined;
  const pt = !preset && f.place ? parsePoint(f.place) : null;
  const scopeName = preset
    ? preset.name
    : pt
      ? `${radiusKm} km of ${fmtLatLon(pt.lat, pt.lon, 2)}`
      : (places.areas.find((a) => a.id === f.area)?.name ?? "Borneo");
  const sizes = bands.frp_dot_sizes_mw;

  return (
    <div className="map-card">
      <div ref={elRef} className="map-el" role="region" aria-label="Hotspot map of Borneo" />

      <div className="map-overlay map-basemap" role="group" aria-label="Base map">
        <button type="button" aria-pressed={basemap === "street"} onClick={() => setBasemap("street")}>
          Street
        </button>
        <button type="button" aria-pressed={basemap === "satellite"} onClick={() => setBasemap("satellite")}>
          Satellite
        </button>
      </div>

      <div className="map-overlay map-buttons">
        <button type="button" className="map-btn" aria-label="Zoom in" title="Zoom in" onClick={() => mapRef.current?.zoomIn()}>
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
        </button>
        <button type="button" className="map-btn" aria-label="Zoom out" title="Zoom out" onClick={() => mapRef.current?.zoomOut()}>
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
        </button>
        <button type="button" className="map-btn" aria-label="Reset view" title="Reset view" onClick={resetView}>
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></svg>
        </button>
        <button
          type="button"
          className="map-btn"
          aria-label={drawing ? "Stop drawing" : "Draw area"}
          title={drawing ? "Stop drawing" : "Draw area"}
          aria-pressed={drawing}
          onClick={toggleDraw}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><path d="M12 3l8 6-3 10H7L4 9z" /></svg>
        </button>
      </div>

      {(drawing || drawnRing) && (
        <div className="map-overlay map-status" role="status">
          {drawing && !drawnRing && <p>Click on the map to add corners; click the first corner to finish.</p>}
          {drawnRing && (
            <>
              <p>
                <strong>Drawn area:</strong> {drawnSummary ? fmtInt(drawnSummary.count) : "…"} hotspots ·{" "}
                {PERIOD_WORDS[f.period]}
                {drawnSummary?.maxFrp != null && <> · max FRP {fmtNum(drawnSummary.maxFrp)} MW</>}
              </p>
              <button type="button" className="btn" onClick={clearDrawn}>
                Clear drawn area
              </button>
            </>
          )}
        </div>
      )}

      {loading && (
        <div className="map-overlay map-empty" role="status">
          Loading hotspots…
        </div>
      )}
      {loadError && (
        <div className="map-overlay map-empty" role="alert">
          Could not load hotspots ({loadError}).
        </div>
      )}
      {selection && selection.idx.length === 0 && (
        <div className="map-overlay map-empty" role="status">
          No hotspots in {scopeName} in the {PERIOD_WORDS[f.period]}.
          <p className="hint">{NEXT_PERIOD[f.period] ?? "Try another area."}</p>
        </div>
      )}

      <div className="map-overlay map-legend">
        {usePoints ? (
          <>
            <strong>Fire intensity (FRP)</strong>
            <span className="legend-item">
              <span className="legend-dot" style={{ width: 7, height: 7 }} />
              &lt; {sizes.small_below} MW
            </span>
            <span className="legend-item">
              <span className="legend-dot" style={{ width: 11, height: 11 }} />
              {sizes.small_below}–{sizes.large_above}
            </span>
            <span className="legend-item">
              <span className="legend-dot" style={{ width: 16, height: 16, border: "2px solid #1A0F06" }} />
              &gt; {sizes.large_above} MW
            </span>
            <span className="legend-note">· click a dot for details</span>
          </>
        ) : (
          <>
            <strong>Hotspots per {grid.data?.cell_deg ?? 0.1}° cell</strong>
            <span className="legend-item">
              <span className="legend-dot" style={{ width: 7, height: 7 }} /> few
            </span>
            <span className="legend-item">
              <span className="legend-dot" style={{ width: 18, height: 18 }} /> many
            </span>
            <span className="legend-note">· raw points only for ≤ 30 days</span>
          </>
        )}
        {selection && <span className="legend-note">· {fmtInt(selection.kind === "points" ? selection.idx.length : selection.idx.reduce((s, i) => s + (grid.data?.count[i] ?? 0), 0))} shown</span>}
        {meta.is_sample && <span className="legend-note">· sample data</span>}
      </div>

      <div className="map-overlay map-cursor" aria-live="off">
        <span ref={cursorRef}>move over the map</span>
      </div>
    </div>
  );
}
