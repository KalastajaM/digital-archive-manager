import { beforeEach, describe, expect, it } from "vitest";
import { forgetLayout, PANE_WIDTH_KEYS, restoreLayout, TODAY_LAYOUT_KEYS } from "./layoutMemory";

beforeEach(() => localStorage.clear());

describe("layoutMemory", () => {
  it("forgets every width and the Today layout, in every archive, and nothing else", () => {
    localStorage.setItem("dam.browse.listwidth", "60");
    localStorage.setItem("dam.browse.listwidth.work", "55");
    localStorage.setItem("dam.today.layout.v1.work", "{}");
    localStorage.setItem("dam.browse.split", "1");
    localStorage.setItem("dam.browse.listwidthy", "9"); // a different key that shares a prefix
    localStorage.setItem("dam.appearance", "dark");
    const removed = forgetLayout();
    expect(Object.keys(removed).sort()).toEqual(["dam.browse.listwidth", "dam.browse.listwidth.work", "dam.today.layout.v1.work"]);
    expect(localStorage.length).toBe(3);
    expect(localStorage.getItem("dam.appearance")).toBe("dark");
    restoreLayout(removed);
    expect(localStorage.getItem("dam.browse.listwidth.work")).toBe("55");
    expect(localStorage.length).toBe(6);
  });

  it("restores only keys it owns", () => {
    restoreLayout({ "dam.appearance": "dark", "dam.trays.listwidth": "300" });
    expect(localStorage.getItem("dam.appearance")).toBeNull();
    expect(localStorage.getItem("dam.trays.listwidth")).toBe("300");
  });

  it("lists every pane width the screens remember (a new useSplitWidth key must be added here)", () => {
    const found = new Set<string>();
    const sources = import.meta.glob(["./**/*.ts", "./**/*.tsx", "!./**/*.test.ts", "!./**/*.test.tsx", "!./layoutMemory.ts"], {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;
    for (const text of Object.values(sources)) {
      for (const m of text.matchAll(/"(dam\.[a-z.]*(?:width|split))"/g)) found.add(m[1]);
    }
    found.delete("dam.browse.split"); // one pane or two: a switch, not a width
    expect([...found].sort()).toEqual([...PANE_WIDTH_KEYS].sort());
    expect(TODAY_LAYOUT_KEYS).toContain("dam.today.layout.v1");
  });
});
