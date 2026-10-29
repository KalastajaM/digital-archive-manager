import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import earlyScript from "../public/appearance.js?raw";
import indexHtml from "../index.html?raw";
import {
  APPEARANCE_KEY,
  installAppearance,
  readAppearance,
  readStyle,
  resolve,
  saveAppearance,
  saveStyle,
  STYLE_KEY,
} from "./appearance";

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

const look = () => document.documentElement.dataset.style;

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.style;
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
    expect(earlyScript).toContain(`"${STYLE_KEY}"`);
    expect(earlyScript).toContain('dark ? "#1a1917" : "#ffffff"');
    // A plain script in <head>, after the theme-color tag it sets (the CSP forbids inline ones).
    const head = indexHtml.slice(0, indexHtml.indexOf("</head>"));
    expect(head).toMatch(/<meta name="theme-color"[^>]*>\s*<script src="\/appearance\.js"><\/script>/);
  });
});

describe("look (New or Classic)", () => {
  it("is New until Classic is saved, and New is not stored", () => {
    expect(readStyle()).toBe("new");
    saveStyle("classic");
    expect(localStorage.getItem(STYLE_KEY)).toBe("classic");
    expect(look()).toBe("classic");
    expect(readStyle()).toBe("classic");
    saveStyle("new");
    expect(localStorage.getItem(STYLE_KEY)).toBeNull();
    expect(look()).toBe("new");
    localStorage.setItem(STYLE_KEY, "purple");
    expect(readStyle()).toBe("new");
  });

  it("someone who chose New when Classic was the default stays on New", () => {
    localStorage.setItem(STYLE_KEY, "new");
    expect(readStyle()).toBe("new");
  });

  it("is applied at start, and a change in another tab follows", () => {
    stubSystem(false);
    localStorage.setItem(STYLE_KEY, "classic");
    installAppearance();
    expect(look()).toBe("classic");
    localStorage.removeItem(STYLE_KEY);
    window.dispatchEvent(new StorageEvent("storage", { key: STYLE_KEY }));
    expect(look()).toBe("new");
  });

  it("the window colour follows look and theme", () => {
    stubSystem(false);
    saveAppearance("light");
    saveStyle("new");
    expect(themeColor()).toBe("#ffffff");
    saveAppearance("dark");
    expect(themeColor()).toBe("#1a1917");
    saveStyle("classic");
    expect(themeColor()).toBe("#1e1e20");
  });

  it("the early script sets the look from the same key", () => {
    localStorage.setItem(STYLE_KEY, "classic");
    document.head.innerHTML = '<meta name="theme-color" content="#fbfbfd" />';
    stubSystem(false);
    new Function(earlyScript)();
    expect(look()).toBe("classic");
    expect(themeColor()).toBe("#fbfbfd");
    localStorage.removeItem(STYLE_KEY);
    new Function(earlyScript)();
    expect(look()).toBe("new");
    expect(themeColor()).toBe("#ffffff");
  });
});
