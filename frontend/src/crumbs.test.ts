import { describe, expect, it } from "vitest";
import { hiddenCrumbs } from "./crumbs";

describe("hiddenCrumbs", () => {
  const widths = [60, 100, 100, 80]; // Archive, A, B, Current
  it("folds nothing when the whole path fits", () => {
    expect(hiddenCrumbs(widths, 26, 4, 400)).toBe(0);
  });
  it("folds the farthest steps first", () => {
    // all: 340 + 12 = 352. Fold 1: 26 + 4 + 280 + 8 = 318. Fold 2: 26 + 4 + 180 + 4 = 214.
    expect(hiddenCrumbs(widths, 26, 4, 330)).toBe(1);
    expect(hiddenCrumbs(widths, 26, 4, 300)).toBe(2);
  });
  it("always keeps the last step, however narrow", () => {
    expect(hiddenCrumbs(widths, 26, 4, 50)).toBe(3);
  });
  it("has nothing to fold for a single step or an unknown width", () => {
    expect(hiddenCrumbs([60], 26, 4, 10)).toBe(0);
    expect(hiddenCrumbs(widths, 26, 4, 0)).toBe(0);
  });
});
