/** The time a check last ended in this browser: kept per archive, forgotten on request, and
 * written the way the status line reads it. */
import { beforeEach, describe, expect, it } from "vitest";
import { archiveKey } from "../../api/client";
import { forgetRun, lastRun, noteRun, RAN_KEY, ranText } from "./lastRun";

beforeEach(() => localStorage.clear());

describe("last run", () => {
  it("remembers each check's time and forgets one or all", () => {
    expect(lastRun("duplicates")).toBeNull();
    noteRun("duplicates", 1000);
    noteRun("names", 2000);
    expect(lastRun("duplicates")).toBe(1000);
    expect(lastRun("names")).toBe(2000);
    forgetRun("duplicates");
    expect(lastRun("duplicates")).toBeNull();
    expect(lastRun("names")).toBe(2000);
    forgetRun();
    expect(localStorage.getItem(archiveKey(RAN_KEY))).toBeNull();
  });

  it("ignores what it cannot read", () => {
    localStorage.setItem(archiveKey(RAN_KEY), "not json");
    expect(lastRun("names")).toBeNull();
    localStorage.setItem(archiveKey(RAN_KEY), JSON.stringify({ names: "yesterday", moved: 5 }));
    expect(lastRun("names")).toBeNull();
    expect(lastRun("moved")).toBe(5);
  });

  it("writes today and yesterday as words and older days as a date", () => {
    const now = new Date(2026, 9, 28, 15, 0);
    expect(ranText(new Date(2026, 9, 28, 14, 10).getTime(), now)).toBe("today 14:10");
    expect(ranText(new Date(2026, 9, 27, 8, 50).getTime(), now)).toBe("yesterday 08:50");
    expect(ranText(new Date(2026, 9, 15, 14, 10).getTime(), now)).toMatch(/^15 Oct/);
  });
});
