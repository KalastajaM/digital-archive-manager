/** The shell's rules that jsdom cannot lay out: read from the style sheets. */
import { describe, expect, it } from "vitest";
import css from "./styles.css?raw";
import theme from "./theme.css?raw";
import { balanceColumns } from "./components/today/balance";
import { holdsText } from "./components/collectionTree";

const strip = (text: string) => text.replace(/\/\*[\s\S]*?\*\//g, "");

/** The declarations of the rules whose selector list contains ``selector``. */
function declarations(selector: string): string {
  const rules = [...strip(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)];
  return rules
    .filter(([, sel]) => sel.split(",").some((s) => s.trim() === selector))
    .map(([, , body]) => body)
    .join(";");
}

/** The custom properties of one theme block (light: the first :root; dark: :root[data-theme="dark"]). */
function tokens(block: "light" | "dark"): Record<string, string> {
  const text = strip(theme);
  const at = text.indexOf(':root[data-theme="dark"]');
  const source = block === "light" ? text.slice(0, at) : text.slice(at);
  return Object.fromEntries([...source.matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{6})\b/g)].map((m) => [m[1], m[2]]));
}

const luminance = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

describe("theme contrast (4.5:1 for small text)", () => {
  for (const scheme of ["light", "dark"] as const) {
    const t = tokens(scheme);
    const light = scheme === "light";
    const surfaces = ["--bg", "--panel", "--panel-2"];
    it(`${scheme}: muted text on the surfaces`, () => {
      const all = { ...tokens("light"), ...t };
      for (const s of surfaces) expect(contrast(all["--muted"], all[s])).toBeGreaterThanOrEqual(4.5);
      expect(contrast(all["--muted-2"], all["--panel-2"])).toBeGreaterThanOrEqual(4.5);
    });
    it(`${scheme}: accent text on the surfaces, and ${light ? "white" : "white"} on the accent fill`, () => {
      const all = { ...tokens("light"), ...t };
      for (const s of surfaces) expect(contrast(all["--accent"], all[s])).toBeGreaterThanOrEqual(4.5);
      expect(contrast("#ffffff", all["--accent-fill"])).toBeGreaterThanOrEqual(4.5);
      expect(contrast(all["--selected-strong-text"], all["--selected-strong"])).toBeGreaterThanOrEqual(4.5);
    });
  }

  it("filled buttons use the fill token, not the text accent", () => {
    expect(declarations("button.primary")).toMatch(/background:\s*var\(--accent-fill\)/);
  });
});

describe("the shell never scrolls itself (no 100vh)", () => {
  it("the window chain is 100% tall and the shell hides its own overflow", () => {
    expect(declarations("#root")).toMatch(/height:\s*100%/);
    const app = declarations(".app");
    expect(app).toMatch(/height:\s*100%/);
    expect(app).toMatch(/overflow:\s*hidden/);
    expect(app).not.toMatch(/100vh/);
    expect(declarations(".sidebar")).not.toMatch(/100vh/);
  });

  it("the content column is the pane that scrolls, and no shell rule uses 100vh", () => {
    expect(declarations(".content")).toMatch(/overflow-y:\s*auto/);
    for (const selector of [".app:has(.inbox) .content", ".app:has(.browse) .content", ".app:has(.trays) .content"]) {
      expect(declarations(selector)).not.toMatch(/100vh/);
    }
  });
});

describe("the sidebar's fold chevron", () => {
  it("is centred on its own row, not on the row plus its children", () => {
    const rule = declarations(".sidebar-disclosure");
    expect(rule).not.toMatch(/bottom:\s*0/);
    expect(rule).toMatch(/top:\s*calc\(\(var\(--sidebar-row-h\) - var\(--icon-button-sm\)\) \/ 2\)/);
    expect(declarations(".sidebar-row")).toMatch(/min-height:\s*var\(--sidebar-row-h\)/);
  });
});

describe("Today's default layout", () => {
  it("deals the cards out between the columns by their heights, the first to the shorter column", () => {
    const columns = balanceColumns([
      { id: "a", weight: 4 },
      { id: "b", weight: 10 },
      { id: "c", weight: 3 },
      { id: "d", weight: 3 },
      { id: "e", weight: 3 },
    ]);
    expect(columns).toEqual([["a", "c", "d", "e"], ["b"]]);
  });
});

describe("one counting rule for a collection's members", () => {
  const folder = { is_dir: true };
  const file = { is_dir: false };
  it("files alone: the list's count, else the direct members", () => {
    expect(holdsText({ members: [file, file] })).toBe("2 files");
    expect(holdsText({ members: [file] }, 23)).toBe("23 files");
  });
  it("a folder member: the folders, then every file in them", () => {
    expect(holdsText({ members: [folder] }, 23)).toBe("1 folder · 23 files");
    expect(holdsText({ members: [folder, file] }, 24)).toBe("1 folder · 24 files");
    expect(holdsText({ members: [folder] })).toBe("1 folder"); // the list has not loaded yet
  });
});
