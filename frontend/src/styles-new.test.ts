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
