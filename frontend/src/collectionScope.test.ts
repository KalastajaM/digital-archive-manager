import { describe, expect, it } from "vitest";
import type { CollectionRow, Member } from "./api/client";
import { childOf, scopedCollection } from "./collectionScope";
import type { FilterName, SearchFilter } from "./searchFilters";

const f = (name: FilterName, value: string, negated = false): SearchFilter => ({ name, value, negated });
const member = (drive_id: string): Member => ({ drive_id, path: `x/${drive_id}.pdf`, is_dir: false, missing: false, quarantined: false, is_link: false, group_id: null, connected: true, marks: [] });
const coll = (id: number, name: string, parent_id: number | null = null, members: string[] = [], kind: string | null = null): CollectionRow => ({
  id,
  name,
  state: "open",
  created: 1,
  closed_at: null,
  publish: { ongoing: true },
  ongoing_rel: null,
  members: members.map(member),
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id,
  path: [name],
  kind: kind as CollectionRow["kind"],
  position: id,
  files: members.length,
  open_checks: 0,
});

const ALL = [
  coll(1, "Legal", null, ["a"]),
  coll(2, "Michiel", 1, ["b", "d"]),
  coll(3, "Wills", 2, ["c"]),
  coll(4, "Together", 1, ["d"]),
  coll(5, 'The "big" move'),
  coll(9, "★ Ongoing", null, [], "starred"),
];

describe("scopedCollection", () => {
  it("finds the one collection a search is scoped to", () => {
    expect(scopedCollection([f("collection", "legal")], ALL)).toEqual({ c: ALL[0] });
    expect(scopedCollection([f("collection", "Legal"), f("type", "pdf")], ALL)).toEqual({ c: ALL[0] });
  });
  it("matches a name whose quote marks the chip could not carry", () => {
    expect(scopedCollection([f("collection", "The big move")], ALL)).toEqual({ c: ALL[4] });
  });
  it("is:starred alone is Starred", () => {
    expect(scopedCollection([f("is", "starred")], ALL)).toEqual({ c: ALL[5] });
  });
  it("is nothing for two scopes or none, and says when the name is unknown", () => {
    expect(scopedCollection([f("collection", "Legal"), f("collection", "Michiel")], ALL)).toBeNull();
    expect(scopedCollection([f("collection", "Legal"), f("is", "starred")], ALL)).toBeNull();
    expect(scopedCollection([f("collection", "Legal", true)], ALL)).toBeNull();
    expect(scopedCollection([], ALL)).toBeNull();
    expect(scopedCollection([f("collection", "Nope")], ALL)).toEqual({ missing: "Nope" });
  });
});

describe("childOf", () => {
  it("names the child (at any depth) that holds a file, the nearest first", () => {
    expect(childOf("c", ALL[0], ALL)).toBe("Wills");
    expect(childOf("b", ALL[0], ALL)).toBe("Michiel");
    expect(childOf("d", ALL[0], ALL)).toBe("Michiel"); // in Michiel and Together: the first in tree order
    expect(childOf("a", ALL[0], ALL)).toBeNull(); // in Legal itself
    expect(childOf("zz", ALL[0], ALL)).toBeNull();
  });
});
