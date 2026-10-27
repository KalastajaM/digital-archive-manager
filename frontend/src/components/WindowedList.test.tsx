/** WindowedList: which rows a long list renders, and that short or unlaid lists render all. */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { type Part, rowWindow, WindowedList } from "./WindowedList";

const rows = (n: number, h = 30) => new Array<number>(n).fill(h);
const total = (parts: Part[], heights: number[]) =>
  parts.reduce((sum, p) => sum + ("spacer" in p ? p.spacer : heights.slice(p.from, p.to).reduce((a, b) => a + b, 0)), 0);

describe("rowWindow", () => {
  it("at the top: the rows in view and some below, then one spacer for the rest", () => {
    const heights = rows(1000);
    const parts = rowWindow(heights, 0, 600, null);
    expect(parts).toEqual([{ from: 0, to: 47 }, { spacer: (1000 - 47) * 30 }]);
  });

  it("in the middle: spacers above and below keep the full height", () => {
    const heights = rows(1000);
    const parts = rowWindow(heights, 15000, 600, null);
    expect(parts[0]).toEqual({ spacer: expect.any(Number) });
    const run = parts[1] as { from: number; to: number };
    expect(run.from).toBeLessThanOrEqual(500);
    expect(run.to).toBeGreaterThan(520);
    expect(total(parts, heights)).toBe(30000);
  });

  it("the pinned row is rendered wherever it is, between spacers", () => {
    const heights = rows(1000);
    const below = rowWindow(heights, 0, 600, 900);
    expect(below).toEqual([{ from: 0, to: 47 }, { spacer: (900 - 47) * 30 }, { from: 900, to: 901 }, { spacer: 99 * 30 }]);
    const above = rowWindow(heights, 15000, 600, 3);
    expect(above[0]).toEqual({ spacer: 90 });
    expect(above[1]).toEqual({ from: 3, to: 4 });
    expect(total(above, heights)).toBe(30000);
    // a pinned row inside the window adds nothing
    expect(rowWindow(heights, 0, 600, 10)).toEqual(rowWindow(heights, 0, 600, null));
  });

  it("rows of different heights", () => {
    const heights = [...rows(100, 30), ...rows(100, 60)];
    const parts = rowWindow(heights, 6000, 300, null);
    expect(total(parts, heights)).toBe(9000);
    const run = parts.find((p) => !("spacer" in p)) as { from: number; to: number };
    // the row at 6000 px: 100 rows of 30 px, then 50 of 60 px
    expect(run.from).toBeLessThan(150);
    expect(run.to).toBeGreaterThan(155);
  });
});

describe("WindowedList", () => {
  const list = (n: number) => (
    <div>
      <WindowedList
        entries={Array.from({ length: n }, (_, k) => k)}
        keyOf={(k) => String(k)}
        pin={null}
        render={(k) => <li key={k}>row {k}</li>}
        listRef={() => {}}
        className="entries"
        aria-label="Rows"
      />
    </div>
  );

  it("renders every row of a list with no laid-out height (as jsdom)", () => {
    const { container } = render(list(2000));
    expect(container.querySelectorAll("li")).toHaveLength(2000);
  });

  it("renders every row of a short list", () => {
    const { container } = render(list(20));
    expect(container.querySelectorAll("li")).toHaveLength(20);
  });
});
