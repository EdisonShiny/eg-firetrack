import { type ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/** Old localStorage key from when the card showed only on the first visit; cleared on load. */
const LEGACY_INTRO_SEEN_KEY = "egft_intro_seen";

/** The card auto-opens once per full page load (first visit, every refresh, every opened link). */
let autoShownThisLoad = false;

function takeAutoShow(): boolean {
  if (autoShownThisLoad) return false;
  autoShownThisLoad = true;
  try {
    window.localStorage.removeItem(LEGACY_INTRO_SEEN_KEY);
  } catch {
    /* storage blocked (private window): nothing to clear */
  }
  return true;
}

/** Test helper: behave as if the page had just been loaded again. */
export function resetIntroAutoShowForTests() {
  autoShownThisLoad = false;
}

const svg = (children: ReactNode, size = 20) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={2}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    {children}
  </svg>
);

const ICONS = {
  info: (size?: number) =>
    svg(
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v5M12 8h.01" />
      </>,
      size,
    ),
  map: () =>
    svg(
      <>
        <path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2Z" />
        <path d="M9 4v14M15 6v14" />
      </>,
    ),
  calendar: () =>
    svg(
      <>
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M3 10h18M8 3v4M16 3v4" />
      </>,
    ),
  analysis: () => svg(<path d="M3 20h18M5 16l4-5 4 3 6-8" />),
  alerts: () =>
    svg(
      <>
        <path d="M10.3 4.2 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z" />
        <path d="M12 9v5M12 17h.01" />
      </>,
    ),
};

const PAGES = [
  { icon: ICONS.map, name: "Map", text: "See where fires are now, how today compares with normal, and the top 5 districts." },
  { icon: ICONS.calendar, name: "Calendar", text: "See when fires happen: a 10-year heatmap, yearly totals and the fire season." },
  {
    icon: ICONS.analysis,
    name: "Analysis",
    text: "Follow the trend from past to now to the next 3 months, with the harmonization check.",
  },
  {
    icon: ICONS.alerts,
    name: "Alerts",
    text: "Know what to do and where first: alert levels, reasons, actions and rescue priority.",
  },
];

const STEPS = [
  "Choose an Area in the top bar – Whole Borneo, Sarawak, Sabah, Brunei or a Kalimantan province.",
  "Or pick a Place such as Kuching, Miri or Pontianak (or type a latitude, longitude) – the Area changes automatically.",
  "Select a Period, from Current (last 24 hours) to All (2017–2026). Every page updates together and keeps your choice.",
  "Click a hotspot dot on the Map for its time, satellite and fire intensity, or a calendar cell for that month's details.",
  "Check the Active alerts bar, then open Alerts to see what needs action first.",
  "Use Download CSV or PDF report to save the data or a full report of all four pages.",
];

const FOCUSABLE = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** The welcome card itself (modal dialog). */
export function IntroCard(props: { onClose: () => void }) {
  const { onClose } = props;
  const card = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    card.current?.querySelector<HTMLElement>(".intro-start")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !card.current) return;
      const items = Array.from(card.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || !card.current.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !card.current.contains(active))) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, []);

  return createPortal(
    <div
      className="intro-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="intro-card" ref={card} role="dialog" aria-modal="true" aria-labelledby="intro-title">
        <button type="button" className="intro-close" aria-label="Close" onClick={onClose}>
          ×
        </button>
        <img src="/brand/logo-mark.png" alt="" className="intro-logo" width={56} height={56} />
        <h2 id="intro-title" className="intro-title">
          Welcome to EG FireTrack
        </h2>
        <p className="intro-sub intro-sub-lead">
          A website that harmonizes NASA MODIS + VIIRS fire hotspots for Borneo – 10 years of history, updated every
          day.
        </p>
        <p className="intro-sub">
          It also forecasts where fires may spread in the next 72 hours, predicts activity for the next 3 months, and
          suggests a response for the agency in charge.
        </p>
        <ul className="intro-pages">
          {PAGES.map((p) => (
            <li key={p.name}>
              <span className="intro-page-icon">{p.icon()}</span>
              <span>
                <b>{p.name}</b>
                <span className="intro-page-text">{p.text}</span>
              </span>
            </li>
          ))}
        </ul>
        <h3 className="intro-h3">How to start</h3>
        <ol className="intro-steps">
          {STEPS.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
        <p className="intro-foot">
          Data: NASA FIRMS (MODIS C6.1, VIIRS 375 m). Check the Data status button for freshness.
        </p>
        <div className="intro-actions">
          <button type="button" className="btn btn-primary intro-start" onClick={onClose}>
            Start exploring
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** Small outlined "Intro" button for the top bar (before the page tabs; never an active tab), plus the card. Auto-opens once per page load. */
export function IntroLauncher() {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);

  // In an effect (not the state initializer) so React StrictMode's double call cannot swallow it.
  useEffect(() => {
    if (takeAutoShow()) setOpen(true);
  }, []);

  function close() {
    setOpen(false);
    button.current?.focus();
  }

  return (
    <>
      <button
        type="button"
        ref={button}
        className="intro-btn"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        {ICONS.info(16)}
        Intro
      </button>
      {open && <IntroCard onClose={close} />}
    </>
  );
}
