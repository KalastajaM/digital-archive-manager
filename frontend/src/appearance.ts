/** Light, Dark or Auto (follow the system), and the look (Classic or New): one choice
 * for the whole app in this browser, every archive alike, so it is kept under a plain key, not ``archiveKey``. The theme is
 * ``<html data-theme>``: public/appearance.js sets it before the first paint with the
 * same rule as ``resolve`` here, and ``installAppearance`` keeps it up to date (the
 * system switching while on Auto, another tab changing the choice). */
import { useState, useSyncExternalStore } from "react";

export type Appearance = "light" | "dark" | "auto";

export const APPEARANCE_KEY = "dam.appearance";

/** The look: New (the default) or Classic, kept for now. ``<html data-style>``, next to
 * ``data-theme``, set before the first paint by public/appearance.js with the same rule as
 * ``readStyle``. Only Classic is stored, so a "new" stored when Classic was the default
 * still means New. */
export type Look = "classic" | "new";

export const STYLE_KEY = "dam.style";

/** The window colour per look and theme: each one's ``--bg``. */
const THEME_COLOR = {
  classic: { light: "#fbfbfd", dark: "#1e1e20" },
  new: { light: "#ffffff", dark: "#1a1917" },
} as const;

const systemDark = () => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;

export function readAppearance(): Appearance {
  try {
    const v = localStorage.getItem(APPEARANCE_KEY);
    return v === "light" || v === "dark" ? v : "auto";
  } catch {
    return "auto";
  }
}

export const resolve = (choice: Appearance): "light" | "dark" =>
  choice === "auto" ? (systemDark() ? "dark" : "light") : choice;

export function readStyle(): Look {
  try {
    return localStorage.getItem(STYLE_KEY) === "classic" ? "classic" : "new";
  } catch {
    return "new";
  }
}

// ``data-style`` is set before the first paint, so it is unset only in component tests,
// which were written for Classic and set New where they test it.
const currentStyle = (): Look => (document.documentElement.dataset.style === "new" ? "new" : "classic");
const styleListeners = new Set<() => void>();

export function applyAppearance(choice: Appearance = readAppearance()): void {
  const theme = resolve(choice);
  document.documentElement.dataset.theme = theme;
  document
    .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    ?.setAttribute("content", THEME_COLOR[currentStyle()][theme]);
}

export function applyStyle(look: Look = readStyle()): void {
  const changed = currentStyle() !== look;
  document.documentElement.dataset.style = look;
  applyAppearance(); // the window colour depends on both
  if (changed) styleListeners.forEach((fn) => fn());
}

export function saveStyle(look: Look): void {
  try {
    if (look === "new") localStorage.removeItem(STYLE_KEY);
    else localStorage.setItem(STYLE_KEY, look);
  } catch {
    // Storage blocked: the choice still applies until the window is reloaded.
  }
  applyStyle(look);
}

export function saveAppearance(choice: Appearance): void {
  try {
    if (choice === "auto") localStorage.removeItem(APPEARANCE_KEY);
    else localStorage.setItem(APPEARANCE_KEY, choice);
  } catch {
    // Storage blocked: the choice still applies until the window is reloaded.
  }
  applyAppearance(choice);
}

/** Once, at start: follow the system while on Auto, and a choice made in another tab. */
export function installAppearance(): void {
  applyStyle();
  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => applyAppearance());
  window.addEventListener("storage", (e) => {
    if (e.key === APPEARANCE_KEY || e.key === null) applyAppearance();
    if (e.key === STYLE_KEY || e.key === null) applyStyle();
  });
}

export function useAppearance(): [Appearance, (choice: Appearance) => void] {
  const [choice, setChoice] = useState<Appearance>(readAppearance);
  const set = (next: Appearance) => {
    setChoice(next);
    saveAppearance(next);
  };
  return [choice, set];
}

/** The look and a setter; every user of the hook (Settings, the Ctrl+Alt+L shortcut)
 * sees a change made by any of the others. */
export function useStyle(): [Look, (look: Look) => void] {
  const look = useSyncExternalStore(
    (fn) => {
      styleListeners.add(fn);
      return () => styleListeners.delete(fn);
    },
    currentStyle,
  );
  return [look, saveStyle];
}
