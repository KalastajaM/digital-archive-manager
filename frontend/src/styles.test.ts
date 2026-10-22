/** Rules that tests cannot see through jsdom's missing layout: read from the sheet. */
import { describe, expect, it } from "vitest";
import css from "./styles.css?raw";

/** The declarations of the rule whose selector list contains ``selector``. */
function declarations(selector: string): string {
  const plain = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = [...plain.matchAll(/([^{}]+)\{([^{}]*)\}/g)];
  const found = rules.filter(([, sel]) => sel.split(",").some((s) => s.trim() === selector));
  return found.map(([, , body]) => body).join(";");
}

describe("copyable text", () => {
  // The errors sheet opens from the sidebar, whose text is not selectable.
  it.each(["dialog.sheet", "dialog.quicklook"])("%s text can be selected", (selector) => {
    expect(declarations(selector)).toMatch(/(^|[;\s])user-select:\s*text/);
    expect(declarations(selector)).toMatch(/-webkit-user-select:\s*text/);
  });

  it("the No preview path hint can be selected", () => {
    expect(declarations(".no-preview code")).toMatch(/(^|[;\s])user-select:\s*text/);
  });
});

describe("sizes the components set (CSS variables, never repeated numbers)", () => {
  it("the barcode digits are inset by the quiet zone the SVG draws", () => {
    expect(declarations(".barcode-code")).toMatch(/padding:\s*0 var\(--quiet-zone\)/);
    expect(css).not.toMatch(/calc\(10 \* 3px\)/);
  });

  it("the tray-defaults value and problem lines are indented by the checkbox width", () => {
    for (const selector of [".defaults-value", ".defaults-problem"]) {
      expect(declarations(selector)).toMatch(/calc\(var\(--check-width\) \+ var\(--sp-2\)\)/);
    }
    expect(declarations(".defaults-list input[type=\"checkbox\"]")).toMatch(/width:\s*var\(--check-width\)/);
  });
});

describe("sheets keep their title and buttons in view (the body scrolls)", () => {
  it("an open sheet is a column no taller than the window, and does not scroll itself", () => {
    const open = declarations("dialog.sheet[open]");
    expect(open).toMatch(/display:\s*flex/);
    expect(open).toMatch(/flex-direction:\s*column/);
    const sheet = declarations("dialog.sheet");
    expect(sheet).toMatch(/overflow:\s*hidden/);
    expect(sheet).toMatch(/max-height:\s*calc\(100dvh/);
  });

  it("only the body scrolls; the title and the footer keep their size", () => {
    const body = declarations(".sheet-body");
    expect(body).toMatch(/overflow-y:\s*auto/);
    expect(body).toMatch(/min-height:\s*0/);
    expect(body).toMatch(/flex:\s*1 1 auto/);
    for (const fixed of [".sheet-title", ".sheet-footer"]) expect(declarations(fixed)).toMatch(/flex:\s*none/);
  });
});

describe("folder browser rows", () => {
  it("a dimmed row stays dimmed while selected in the focused tree", () => {
    const rule = declarations('.folder-tree:focus .folder-tree-row[aria-selected="true"].folder-tree-dimmed');
    expect(rule).toMatch(/color:\s*var\(--selected-strong-muted\)/);
  });
});
