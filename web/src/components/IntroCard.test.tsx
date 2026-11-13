// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, NavLink, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { IntroLauncher, resetIntroAutoShowForTests } from "./IntroCard";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

/** Mini app: a shell (like App.tsx) with the launcher in the top bar, four tabs and a print route. */
function TestApp(props: { path?: string }) {
  return (
    <MemoryRouter initialEntries={[props.path ?? "/"]}>
      <Routes>
        <Route path="/report" element={<p>report</p>} />
        <Route
          element={
            <>
              <IntroLauncher />
              {["/", "/calendar", "/analysis", "/alerts"].map((to) => (
                <NavLink key={to} to={to}>
                  {`tab${to}`}
                </NavLink>
              ))}
              <Outlet />
            </>
          }
        >
          <Route path="*" element={<p>page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

function mount(path?: string) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<TestApp path={path} />));
}

/** Simulates a full page load (F5 / opening the link): fresh module state, fresh mount. */
function pageLoad(path?: string) {
  resetIntroAutoShowForTests();
  mount(path);
}

function closeWithEsc() {
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  });
}

function unmount() {
  act(() => root.unmount());
  host.remove();
}

const dialog = () => document.querySelector('[role="dialog"]');
const introButton = () =>
  Array.from(host.querySelectorAll("button")).find((b) => b.textContent?.trim() === "Intro")!;

beforeEach(() => localStorage.clear());
const tab = (to: string) =>
  Array.from(host.querySelectorAll("a")).find((a) => a.textContent === `tab${to}`)!;
afterEach(() => unmount());

describe("welcome / intro card", () => {
  it("opens on page load, accessible and focused", () => {
    pageLoad();
    const d = dialog();
    expect(d).not.toBeNull();
    expect(d!.getAttribute("aria-modal")).toBe("true");
    const title = document.getElementById(d!.getAttribute("aria-labelledby")!);
    expect(title?.textContent).toBe("Welcome to EG FireTrack");
    expect(d!.contains(document.activeElement)).toBe(true);
  });

  it("opens again on every page load, even after it was closed", () => {
    pageLoad();
    const start = Array.from(document.querySelectorAll("button")).find((b) => b.textContent === "Start exploring")!;
    act(() => start.click());
    expect(dialog()).toBeNull();
    expect(document.activeElement).toBe(introButton());
    unmount();
    pageLoad();
    expect(dialog()).not.toBeNull();
  });

  it("does not use or keep the old localStorage key", () => {
    localStorage.setItem("egft_intro_seen", "1");
    pageLoad();
    expect(dialog()).not.toBeNull();
    closeWithEsc();
    expect(localStorage.getItem("egft_intro_seen")).toBeNull();
  });

  it("stays closed when changing tabs", () => {
    pageLoad();
    closeWithEsc();
    for (const to of ["/calendar", "/analysis", "/alerts", "/"]) {
      act(() => tab(to).dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })));
      expect(tab(to).classList.contains("active")).toBe(true);
      expect(dialog()).toBeNull();
    }
  });

  it("does not show on the print /report route", () => {
    pageLoad("/report");
    expect(host.textContent).toContain("report");
    expect(dialog()).toBeNull();
  });

  it("shows the subtitle and the forecast sentence as two lines", () => {
    pageLoad();
    const subs = Array.from(document.querySelectorAll(".intro-sub")).map((p) =>
      p.textContent?.replace(/\s+/g, " ").trim(),
    );
    expect(subs).toEqual([
      "A website that harmonizes NASA MODIS + VIIRS fire hotspots for Borneo – 10 years of history, updated every day.",
      "It also forecasts where fires may spread in the next 72 hours, predicts activity for the next 3 months, and suggests a response for the agency in charge.",
    ]);
  });

  it("the Intro control is a plain button, not a tab", () => {
    pageLoad();
    closeWithEsc();
    const b = introButton();
    expect(b.className).toBe("intro-btn");
    expect(b.getAttribute("aria-haspopup")).toBe("dialog");
    act(() => b.click());
    expect(b.classList.contains("active")).toBe(false);
  });

  it("reopens from the Intro button and closes with Esc", () => {
    pageLoad();
    closeWithEsc();
    expect(dialog()).toBeNull();
    act(() => introButton().click());
    expect(dialog()).not.toBeNull();
    closeWithEsc();
    expect(dialog()).toBeNull();
    expect(document.activeElement).toBe(introButton());
  });

  it("closes with the × button and the dark background", () => {
    pageLoad();
    act(() => (document.querySelector('button[aria-label="Close"]') as HTMLButtonElement).click());
    expect(dialog()).toBeNull();
    act(() => introButton().click());
    const backdrop = document.querySelector(".intro-backdrop")!;
    act(() => {
      backdrop.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    expect(dialog()).toBeNull();
  });
});
