import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import earlyScript from "../public/appearance.js?raw";
import indexHtml from "../index.html?raw";
import { APPEARANCE_KEY, installAppearance, readAppearance, resolve, saveAppearance } from "./appearance";

/** A system setting the test can flip, with the change listeners matchMedia would call. */
function stubSystem(dark: boolean) {
  const listeners: (() => void)[] = [];
  const query = {
    get matches() {
      return dark;
    },
    addEventListener: (_: string, fn: () => void) => listeners.push(fn),
  };
  vi.stubGlobal("matchMedia", () => query);
  return (next: boolean) => {
    dark = next;
    listeners.forEach((fn) => fn());
  };
}

const theme = () => document.documentElement.dataset.theme;
const themeColor = () => document.querySelector('meta[name="theme-color"]')?.getAttribute("content");

beforeEach(() => {
  localStorage.clear();
  document.head.innerHTML = '<meta name="theme-color" content="#fbfbfd" />';
});
afterEach(() => vi.unstubAllGlobals());

describe("appearance", () => {
  it("is Auto until a choice is saved, and Auto is not stored", () => {
    expect(readAppearance()).toBe("auto");
    saveAppearance("dark");
    expect(localStorage.getItem(APPEARANCE_KEY)).toBe("dark");
    saveAppearance("auto");
    expect(localStorage.getItem(APPEARANCE_KEY)).toBeNull();
    localStorage.setItem(APPEARANCE_KEY, "purple");
    expect(readAppearance()).toBe("auto");
  });

  it("a chosen theme wins over the system, Auto follows it", () => {
    stubSystem(true);
    expect(resolve("light")).toBe("light");
    expect(resolve("auto")).toBe("dark");
    saveAppearance("light");
    expect(theme()).toBe("light");
    expect(themeColor()).toBe("#fbfbfd");
    saveAppearance("dark");
    expect(theme()).toBe("dark");
    expect(themeColor()).toBe("#1e1e20");
  });

  it("on Auto it follows the system switching; a chosen theme stays", () => {
    const flip = stubSystem(false);
    installAppearance();
    expect(theme()).toBe("light");
    flip(true);
    expect(theme()).toBe("dark");
    saveAppearance("light");
    flip(false);
    flip(true);
    expect(theme()).toBe("light");
  });

  it("the script that runs before the first paint uses the same key and colours", () => {
    expect(earlyScript).toContain(`"${APPEARANCE_KEY}"`);
    expect(earlyScript).toContain('"#1e1e20" : "#fbfbfd"');
    // A plain script in <head>, after the theme-color tag it sets (the CSP forbids inline ones).
    const head = indexHtml.slice(0, indexHtml.indexOf("</head>"));
    expect(head).toMatch(/<meta name="theme-color"[^>]*>\s*<script src="\/appearance\.js"><\/script>/);
  });
});
