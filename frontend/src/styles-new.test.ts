/** The New look's sheet must never reach Classic: every selector sits under the data-style
 * attribute. And the icon rail's rules, which jsdom cannot lay out, are read from the sheet. */
import { describe, expect, it } from "vitest";
import css from "./styles-new.css?raw";

const plain = css.replace(/\/\*[\s\S]*?\*\//g, "");

/** Every selector list of every rule, including the rules inside @media and @container. */
function selectors(): string[] {
  return [...plain.matchAll(/([^{};]+)\{[^{}]*\}/g)]
    .map(([, sel]) => sel.trim())
    .filter((sel) => !sel.startsWith("@"))
    .flatMap((sel) => sel.split(",").map((s) => s.trim()));
}

describe("styles-new.css", () => {
  it("scopes every selector under data-style=new", () => {
    expect(selectors().length).toBeGreaterThan(50); // the sheet was read
    const loose = selectors().filter((s) => !/^(:where\(|:root)?\[data-style="new"\]/.test(s));
    expect(loose).toEqual([]);
  });

  it("shows the sidebar as a 60px icon rail at 960px and below, and when it measures under 120px", () => {
    expect(plain).toMatch(/@media \(max-width: 960px\)\s*\{\s*:root\[data-style="new"\] \{ --sidebar-w: 60px; \}/);
    expect(plain).toMatch(/@container side \(max-width: 120px\)/);
    expect(plain).toMatch(/container: side \/ inline-size/);
  });
});

describe("styles-new.css: the Inbox, Draw a box and the rule sheet", () => {
  it("folds the list by the width of the Inbox itself, under about 1000px", () => {
    expect(plain).toMatch(/main:has\(> \.inbox\) \{ container: inbox \/ inline-size; \}/);
    expect(plain).toMatch(/@container inbox \(max-width: 1000px\)/);
  });

  it("keeps the panes side by side where Classic stacks them (900px and 760px)", () => {
    const at = (query: string) => plain.slice(plain.indexOf(query)).split(/\n\}\n/)[0];
    for (const query of ["@media (max-width: 900px)", "@media (max-width: 760px)"]) {
      const block = at(query);
      expect(block).toContain(".review-body");
      expect(block).not.toMatch(/grid-template-columns: 1fr;/);
    }
    // the preview pane stays, and the dividers (hidden by Classic's 900px rule) are shown
    expect(plain).toMatch(/\.review-body\.show-preview > \.preview-pane \{ display: flex;/);
    expect(plain).toMatch(/\.inbox \.splitter \{ display: block; \}/);
  });

  it("hides the document's tools that can wait by the width of the tool row", () => {
    expect(plain).toMatch(/\.zoom-controls \{ container: doc \/ inline-size;/);
    expect(plain).toMatch(/@container doc \(max-width: \d+px\)[^}]*\.doc-wide \{ display: none; \}/);
  });

  it("selects the current row with the calm fill, not the strong blue", () => {
    expect(plain).toMatch(/\.inbox-list li\.highlighted \{ background: var\(--selected\);/);
  });

  it("folds the rule sheet's proof into a summary under 900px of sheet", () => {
    expect(plain).toMatch(/container: sheet \/ inline-size;/);
    expect(plain).toMatch(/@container sheet \(max-width: 900px\)/);
    expect(plain).toMatch(/\.proof-mini \{\s*display: flex;/);
  });
});

describe("styles-new.css: Today and Pay mode", () => {
  it("keeps Today's two card columns side by side where Classic stacks them, folding by Today's own width", () => {
    expect(plain).toMatch(/main:has\(> \.today\) \{ container: today \/ inline-size;/);
    expect(plain).toMatch(/\[data-style="new"\] \.today-grid \{ grid-template-columns: minmax\(0, 1\.15fr\) minmax\(0, 1fr\);/);
    expect(plain).toMatch(/@container today \(max-width: 560px\)/);
  });

  it("never wraps a value in Pay mode: the cards wrap, not their values", () => {
    expect(plain).toMatch(/\.pay-fact dd \{[^}]*white-space: nowrap/);
    expect(plain).toMatch(/\.pay-facts \{[^}]*flex-wrap: wrap/);
  });
});
