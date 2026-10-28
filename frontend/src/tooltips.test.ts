import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installTooltips, placeTip } from "./tooltips";

const view = { width: 1000, height: 700 };
const tip = { width: 120, height: 24 };
const box = (left: number, top: number, width = 30, height = 30) => ({ left, top, width, right: left + width, bottom: top + height });

describe("placeTip", () => {
  it("centres below the control", () => {
    expect(placeTip(box(400, 100), tip, view, false)).toEqual({ left: 355, top: 136 });
  });
  it("shifts left at the right window edge so it is never cut off", () => {
    const { left } = placeTip(box(980, 100, 20), tip, view, false);
    expect(left + tip.width).toBeLessThanOrEqual(view.width - 4);
  });
  it("shifts right at the left window edge", () => {
    expect(placeTip(box(0, 100, 20), tip, view, false).left).toBe(4);
  });
  it("flips above when there is no room below", () => {
    expect(placeTip(box(400, 680), tip, view, false).top).toBe(680 - 6 - 24);
  });
  it("goes above on request when it fits", () => {
    expect(placeTip(box(400, 300), tip, view, true).top).toBe(300 - 6 - 24);
  });
  it("anchors a wide control's tip at its left edge", () => {
    expect(placeTip(box(50, 100, 400), tip, view, false).left).toBe(50);
  });
});

describe("installTooltips", () => {
  let remove = () => {};
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    remove();
    vi.useRealTimers();
    document.body.innerHTML = "";
    delete document.documentElement.dataset.style;
  });
  const button = (tipText: string, attrs: Record<string, string> = {}) => {
    const b = document.createElement("button");
    b.setAttribute("data-tip", tipText);
    for (const [k, v] of Object.entries(attrs)) b.setAttribute(k, v);
    document.body.append(b);
    return b;
  };
  const over = (el: Element) => el.dispatchEvent(new Event("pointerover", { bubbles: true }));
  const shown = () => document.body.querySelector<HTMLElement>(".dam-tip[data-open]");

  it("New: shows the tip in its own element on <body> after a short hover, and hides it on leaving", () => {
    document.documentElement.dataset.style = "new";
    remove = installTooltips();
    const b = button("Relatives");
    over(b);
    expect(shown()).toBeNull();
    vi.advanceTimersByTime(500);
    expect(shown()?.textContent).toBe("Relatives");
    expect(shown()?.parentElement).toBe(document.body);
    expect(shown()?.getAttribute("popover")).toBe("manual");
    over(document.body);
    expect(shown()).toBeNull();
  });

  it("New: keyboard focus shows it too, Escape hides it", () => {
    document.documentElement.dataset.style = "new";
    remove = installTooltips();
    const b = button("Quick Look");
    b.focus();
    vi.advanceTimersByTime(500);
    expect(shown()?.textContent).toBe("Quick Look");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(shown()).toBeNull();
  });

  it("a disabled control shows none, and Classic draws none (its CSS box stays)", () => {
    document.documentElement.dataset.style = "new";
    remove = installTooltips();
    over(button("Nope", { disabled: "" }));
    vi.advanceTimersByTime(500);
    expect(shown()).toBeNull();
    document.documentElement.dataset.style = "classic";
    over(button("Classic tip"));
    vi.advanceTimersByTime(500);
    expect(shown()).toBeNull();
  });

  it("a refused drop target says why at once", async () => {
    document.documentElement.dataset.style = "new";
    remove = installTooltips();
    const row = button("Not here");
    row.setAttribute("data-drop", "refused");
    await Promise.resolve();
    expect(shown()?.textContent).toBe("Not here");
    row.removeAttribute("data-drop");
    await Promise.resolve();
    expect(shown()).toBeNull();
  });
});
