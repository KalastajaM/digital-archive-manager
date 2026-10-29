import { describe, expect, it } from "vitest";
import { applyPick, pickFilter, scopeOf, treeParam } from "./browseScope";
import type { FilterName, SearchFilter } from "./searchFilters";

const f = (name: FilterName, value: string, negated = false): SearchFilter => ({ name, value, negated });

describe("browse scope", () => {
  it("reads the tree from the address", () => {
    expect(treeParam("collections")).toBe("collections");
    expect(treeParam("tags")).toBe("tags");
    expect(treeParam(null)).toBe("folders");
    expect(treeParam("junk")).toBe("folders");
  });
  it("turns a pick into the search filter it stands for", () => {
    expect(pickFilter({ kind: "collection", name: "House sale" })).toEqual(f("collection", "House sale"));
    expect(pickFilter({ kind: "tag", name: "medical" })).toEqual(f("tag", "medical"));
    expect(pickFilter({ kind: "starred" })).toEqual(f("is", "starred"));
    expect(pickFilter({ kind: "important" })).toEqual(f("is", "important"));
  });
  it("a plain pick replaces earlier picks and keeps the other filters", () => {
    const before = [f("collection", "A"), f("tag", "x"), f("is", "starred"), f("type", "pdf"), f("tag", "paid", true), f("is", "locked")];
    expect(applyPick(before, { kind: "collection", name: "B" }, false)).toEqual([f("type", "pdf"), f("tag", "paid", true), f("is", "locked"), f("collection", "B")]);
  });
  it("an added tag joins the tags already picked, once", () => {
    const before = [f("tag", "x")];
    expect(applyPick(before, { kind: "tag", name: "y" }, true)).toEqual([f("tag", "x"), f("tag", "y")]);
    expect(applyPick(before, { kind: "tag", name: "X" }, true)).toEqual(before);
  });
  it("reads the picks back for the trees to highlight", () => {
    expect(scopeOf([f("collection", "A"), f("tag", "x"), f("tag", "y", true), f("is", "important")])).toEqual({ collections: ["A"], tags: ["x"], starred: false, important: true });
  });
});
