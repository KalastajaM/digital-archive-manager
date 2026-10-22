import { afterEach, describe, expect, it } from "vitest";
import { installOverflowTitles } from "./overflowTitles";

/** jsdom has no layout: give an element the sizes and style a cut-off text has. */
function cell(text: string, { overflow, ellipsis = true }: { overflow: boolean; ellipsis?: boolean }) {
  const el = document.createElement("span");
  el.textContent = text;
  el.style.textOverflow = ellipsis ? "ellipsis" : "clip";
  Object.defineProperty(el, "clientWidth", { configurable: true, value: 100 });
  Object.defineProperty(el, "scrollWidth", { configurable: true, value: overflow ? 300 : 100 });
  document.body.append(el);
  return el;
}
const hover = (el: Element) => el.dispatchEvent(new Event("pointerover", { bubbles: true }));

describe("overflow titles", () => {
  let remove = () => {};
  afterEach(() => {
    remove();
    document.body.innerHTML = "";
  });

  it("shows the full text of a cut-off name on hover", () => {
    remove = installOverflowTitles();
    const el = cell("20051025_Housingcooperatives.pdf", { overflow: true });
    hover(el);
    expect(el.title).toBe("20051025_Housingcooperatives.pdf");
  });

  it("finds the cut-off cell from a span inside it", () => {
    remove = installOverflowTitles();
    const el = cell("", { overflow: true });
    const inner = document.createElement("b");
    inner.textContent = "20. Houses/00. Hillside";
    el.append(inner);
    hover(inner);
    expect(el.title).toBe("20. Houses/00. Hillside");
  });

  it("adds nothing to text that fits or is not ellipsized", () => {
    remove = installOverflowTitles();
    const fits = cell("short.pdf", { overflow: false });
    const clippedOnly = cell("long text", { overflow: true, ellipsis: false });
    hover(fits);
    hover(clippedOnly);
    expect(fits.hasAttribute("title")).toBe(false);
    expect(clippedOnly.hasAttribute("title")).toBe(false);
  });

  it("keeps an element's own tooltip", () => {
    remove = installOverflowTitles();
    const el = cell("Name", { overflow: true });
    el.title = "Own tooltip";
    hover(el);
    expect(el.title).toBe("Own tooltip");
  });

  it("drops its title when the text fits again", () => {
    remove = installOverflowTitles();
    const el = cell("20051025_Housingcooperatives.pdf", { overflow: true });
    hover(el);
    Object.defineProperty(el, "scrollWidth", { configurable: true, value: 100 });
    hover(el);
    expect(el.hasAttribute("title")).toBe(false);
  });
});
