import { type ComponentType, lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Outlet, Route, Routes } from "react-router-dom";
import { PrintHeader } from "./components/PrintHeader";
import { TopBar } from "./components/TopBar";
import { Skeleton } from "./components/ui";
import { type AppData, AppDataContext } from "./lib/appData";
import { loadJSON } from "./lib/data";
import { mytOffsetHours } from "./lib/format";
import { featureAt } from "./lib/geo";
import type { Bands, Boundaries, Meta, PlacesDoc } from "./lib/types";
import { MapPage } from "./pages/MapPage";
import { initFilters } from "./store/filters";

// Chart pages load ECharts only when opened, so the Map page stays light.
const CalendarPage = lazy(() => import("./pages/CalendarPage").then((m) => ({ default: m.CalendarPage })));
const AnalysisPage = lazy(() => import("./pages/AnalysisPage").then((m) => ({ default: m.AnalysisPage })));
const AlertsPage = lazy(() => import("./pages/AlertsPage").then((m) => ({ default: m.AlertsPage })));
// "PDF report" print route (all four pages, no top bar).
const ReportPage = lazy(() => import("./pages/ReportPage").then((m) => ({ default: m.ReportPage })));

/** Top bar + print header around the four site pages. */
function Shell() {
  return (
    <>
      <TopBar />
      <PrintHeader />
      <Outlet />
    </>
  );
}

function Lazy(props: { page: ComponentType }) {
  const Page = props.page;
  return (
    <Suspense
      fallback={
        <div className="page" aria-busy="true">
          <Skeleton height={620} />
          <div className="side">
            <Skeleton height={420} />
          </div>
        </div>
      }
    >
      <Page />
    </Suspense>
  );
}

export default function App() {
  const [app, setApp] = useState<AppData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      loadJSON<Meta>("meta.json"),
      loadJSON<Bands>("bands.json"),
      loadJSON<PlacesDoc>("places.json"),
      loadJSON<Boundaries>("boundaries.json"),
    ]).then(([meta, bands, places, boundaries]) => {
      initFilters({
        areas: places.areas.map((a) => a.id),
        places: places.places,
        areaOfPoint: (lat, lon) => featureAt(boundaries, lat, lon, "province")?.properties.id ?? null,
      });
      setApp({ meta, bands, places, boundaries, mytOffset: mytOffsetHours(meta.data_through_utc, meta.data_through_myt) });
    }, (e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="error-box">Could not load the site data: {error}</div>;
  if (!app) {
    return (
      <div aria-busy="true">
        <div className="topbar" style={{ height: 132 }} />
        <div className="page">
          <Skeleton height={760} />
          <div className="side">
            <Skeleton height={230} />
            <Skeleton height={230} />
            <Skeleton height={300} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <AppDataContext.Provider value={app}>
      <BrowserRouter>
        <Routes>
          <Route
            path="/report"
            element={
              <Suspense fallback={<p className="hint" style={{ padding: 24 }}>Preparing the report…</p>}>
                <ReportPage />
              </Suspense>
            }
          />
          <Route element={<Shell />}>
            <Route path="/" element={<MapPage />} />
            <Route path="/calendar" element={<Lazy page={CalendarPage} />} />
            <Route path="/analysis" element={<Lazy page={AnalysisPage} />} />
            <Route path="/alerts" element={<Lazy page={AlertsPage} />} />
            <Route path="*" element={<MapPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppDataContext.Provider>
  );
}
