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
  it("keeps Today's two columns side by side where Classic stacks them, folding by Today's own width", () => {
    expect(plain).toMatch(/main:has\(> \.today\) \{ container: today \/ inline-size;/);
    expect(plain).toMatch(/\.tn-body-grid \{ display: grid; grid-template-columns: minmax\(420px, 1\.9fr\) minmax\(220px, 1fr\);/);
    expect(plain).toMatch(/@container today \(max-width: 663px\)/);
  });

  it("never cuts a figure on Today: tile values and bill amounts stay on one line, names truncate", () => {
    expect(plain).toMatch(/\.tn-tile-value \{[^}]*white-space: nowrap/);
    expect(plain).toMatch(/\.tn-bill-actions \{[^}]*white-space: nowrap/);
    expect(plain).toMatch(/\.tn-bill-name > a \{[^}]*text-overflow: ellipsis/);
  });

  it("never wraps a value in Pay mode: the cards wrap, not their values", () => {
    expect(plain).toMatch(/\.pay-fact dd \{[^}]*white-space: nowrap/);
    expect(plain).toMatch(/\.pay-facts \{[^}]*flex-wrap: wrap/);
  });
});

describe("styles-new.css: Browse", () => {
  it("makes the screen and each pane a container, and folds in the agreed order", () => {
    expect(plain).toMatch(/main:has\(> \.browse\) \{ container: browse \/ inline-size; \}/);
    expect(plain).toMatch(/\.browse-pane \{ container: pane \/ inline-size;/);
    const order = ["1120px", "880px", "760px", "640px"].map((w) => plain.indexOf(`@container browse (max-width: ${w})`));
    expect(order.every((i) => i > 0)).toBe(true);
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(plain).toMatch(/@container pane \(max-width: 480px\)/);
  });

  it("has the folder tree and the details beside the panes, each behind its own button when the room is short", () => {
    expect(plain).toMatch(/\.browse-body > \.tree \{ flex: 0 0 var\(--tree-w\);/);
    expect(plain).toMatch(/\.browse-body > \.browse-preview \{ flex: 0 0 var\(--details-w\);/);
    expect(plain).toMatch(/@container browse \(max-width: 1120px\) \{\s*\[data-style="new"\] \.browse-toolbar \.details-button \{ display: inline-flex; \}/);
    expect(plain).toMatch(/@container browse \(max-width: 880px\) \{[\s\S]*?\.tree-button \{ display: inline-flex; \}/);
    expect(plain).toMatch(/\.browse-body\[data-tree="open"\] > \.tree \{\s*display: flex;\s*position: absolute;/);
  });

  it("keeps the panes side by side where Classic stacks them at 900px", () => {
    const block = plain.slice(plain.indexOf('@media (max-width: 900px) {\n  [data-style="new"] .app:has(.browse)')).split(/\n\}\n/)[0];
    expect(block).toContain('[data-style="new"] .browse:not(.browse-split) .browse-main { grid-template-columns: minmax(0, 1fr); }');
    expect(block).toContain('[data-style="new"] .app:has(.browse) .content { height: 100%; }');
    expect(block).not.toMatch(/grid-template-columns: 1fr;/);
  });

  it("drops the parents of a path first, and the folder you are in last", () => {
    expect(plain).toMatch(/\.breadcrumb li \{ flex: 0 100 auto; min-width: 0; \}/);
    expect(plain).toMatch(/\.breadcrumb li:last-child \{ flex: 0 1 auto; min-width: 8ch; \}/);
  });

  it("shows the drop sheet's Option-key line, which Classic hides", () => {
    expect(plain).toMatch(/\.drop-mode-note \{ display: block;/);
  });
});

describe("styles-new.css: Collections and Trays", () => {
  it("makes the collection page a container and folds in the agreed order", () => {
    expect(plain).toMatch(/main:has\(> \.collection-page\) \{ container: coll \/ inline-size; \}/);
    const order = ["900px", "760px"].map((w) => plain.indexOf(`@container coll (max-width: ${w})`));
    expect(order.every((i) => i > 0)).toBe(true);
    expect(order[0]).toBeLessThan(order[1]);
    expect(plain).toMatch(/@container coll \(max-width: 760px\) \{\s*\[data-style="new"\] \.collection-head \.hdr-wide \{ display: none; \}/);
  });

  it("keeps the collection's list and side panel side by side where Classic stacks them at 900px", () => {
    const block = plain.slice(plain.indexOf('@media (max-width: 900px) {\n  [data-style="new"] .app:has(.collection-page)')).split(/\n\}\n/)[0];
    expect(block).toContain('[data-style="new"] .app:has(.collection-page) .content');
    expect(block).not.toMatch(/grid-template-columns: 1fr;/);
    expect(plain).toMatch(/\.collection-cols > \.splitter \{ display: block; \}/);
  });

  it("keeps the header on one line: the subtitle shrinks before the title", () => {
    expect(plain).toMatch(/\.collection-head-line \{ display: flex; align-items: baseline;/);
    expect(plain).toMatch(/\.collection-head-count \{ flex: 0 100 auto;/);
  });

  it("makes the trays a container, lists the items with the calm selection and keeps the panes side by side", () => {
    expect(plain).toMatch(/main:has\(> \.trays\) \{ container: trays \/ inline-size; \}/);
    expect(plain).toMatch(/\.tray-items > li\[aria-current="true"\] \{\s*background: var\(--selected\);/);
    expect(plain).toMatch(/\.trays-main \{ grid-template-columns: var\(--split\) minmax\(0, 1fr\); \}/);
    expect(plain).toMatch(/\.trays-main > \.splitter \{ display: block; \}/);
  });

  it("stacks the item's details and its file panel in one column, as Browse", () => {
    expect(plain).toMatch(/\.trays-detail \{ container: tdetail \/ inline-size;/);
    expect(plain).toMatch(/@container tdetail \(min-width: \d+px\)/);
    expect(plain).toMatch(/\.item-stack \{ display: flex; flex-direction: column;/);
    expect(plain).not.toMatch(/\.item-cols \{/);
  });
});

describe("styles-new.css: text never leaves its box", () => {
  /** Every declaration block whose selector list is exactly this selector, joined. */
  const rule = (selector: string) => {
    const blocks = [...plain.matchAll(/([^{};]+)\{([^{}]*)\}/g)].filter(([, sel]) => sel.split(",").map((x) => x.trim()).includes(selector)).map(([, , body]) => body);
    expect(blocks.length).toBeGreaterThan(0);
    return blocks.join(" ");
  };

  it("lets a checklist entry wrap, though a control's text never does", () => {
    expect(rule('[data-style="new"] button')).toContain("white-space: nowrap");
    const entry = rule('[data-style="new"] button.check-text');
    expect(entry).toContain("white-space: normal");
    expect(entry).toContain("overflow-wrap: anywhere");
    expect(rule('[data-style="new"] .check')).toContain("align-items: flex-start");
  });

  it("scales a tile's figure with its tile instead of cutting it", () => {
    expect(rule('[data-style="new"] .tn-tile')).toContain("container-type: inline-size");
    expect(rule('[data-style="new"] .tn-tile-value')).toContain("cqi");
  });

  it("keeps the fields' bottom margin from pushing Mark done below the inputs", () => {
    expect(rule('[data-style="new"] .item-fields .field')).toContain("margin-bottom: 0");
  });
});

describe("styles-new.css: Draw a box panel", () => {
  it("keeps a box's message from taking a 100% flex basis in the card's column", () => {
    expect(plain).toMatch(/\.box-kept-problem \{ flex: none; \}/);
  });
});
