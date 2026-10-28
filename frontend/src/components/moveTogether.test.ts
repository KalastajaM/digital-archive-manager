/** Move together: scroll is copied as a share of the way down and across, so documents of
 * different lengths stay at the same place in proportion. */
import { describe, expect, it } from "vitest";
import { alignScroll, alignPages, newHub } from "./moveTogether";

const frame = (scrollHeight: number, clientHeight: number, scrollWidth = 100, clientWidth = 100) =>
  ({ scrollTop: 0, scrollLeft: 0, scrollHeight, clientHeight, scrollWidth, clientWidth }) as unknown as HTMLElement;

describe("alignScroll", () => {
  it("copies the share of the way down, not the pixels", () => {
    const hub = newHub();
    const a = frame(1100, 100, 300, 100);
    const b = frame(2100, 100);
    hub.frames.set("subject", a);
    hub.frames.set("file", b);
    a.scrollTop = 500; // half way down
    a.scrollLeft = 100; // half way across
    alignScroll(hub, "subject");
    expect(b.scrollTop).toBe(1000);
    expect(b.scrollLeft).toBe(0); // nothing to scroll across in b
    // remembered, so b's own scroll event is not copied back
    expect(hub.expected.get(b)).toEqual({ top: 1000, left: 0 });
  });
});

describe("alignPages", () => {
  it("turns the other panes to the page of the one in use", () => {
    const hub = newHub();
    const turned: number[] = [];
    hub.pages.set("subject", { page: 3, to: () => {} });
    hub.pages.set("file", { page: 1, to: (p) => turned.push(p) });
    alignPages(hub, "subject");
    expect(turned).toEqual([3]);
  });
});
