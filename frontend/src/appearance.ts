/** Light, Dark or Auto (follow the system): one choice for the whole app in this browser,
 * every archive alike, so it is kept under a plain key, not ``archiveKey``. The theme is
 * ``<html data-theme>``: public/appearance.js sets it before the first paint with the
 * same rule as ``resolve`` here, and ``installAppearance`` keeps it up to date (the
 * system switching while on Auto, another tab changing the choice). */
import { useState } from "react";

export type Appearance = "light" | "dark" | "auto";

export const APPEARANCE_KEY = "dam.appearance";

/** The window colour per theme: each theme's ``--bg``. */
const THEME_COLOR = { light: "#fbfbfd", dark: "#1e1e20" } as const;

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

export function applyAppearance(choice: Appearance = readAppearance()): void {
  const theme = resolve(choice);
  document.documentElement.dataset.theme = theme;
  document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[theme]);
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
  applyAppearance();
  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => applyAppearance());
  window.addEventListener("storage", (e) => {
    if (e.key === APPEARANCE_KEY || e.key === null) applyAppearance();
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
