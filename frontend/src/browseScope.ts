/** What Browse's left pane shows (folders, collections or tags) and what a pick in the
 * collection or tag tree means. A pick is a search filter (`collection:`, `tag:`,
 * `is:starred`, `is:important`), so the list, its chips and the address need nothing new. */
import { type SearchFilter, withFilter } from "./searchFilters";

export type TreeKind = "folders" | "collections" | "tags";

/** The tree named in the address (``?tree=``); folders when there is none. */
export function treeParam(value: string | null): TreeKind {
  return value === "collections" || value === "tags" ? value : "folders";
}

export type ScopePick = { kind: "collection"; name: string } | { kind: "tag"; name: string } | { kind: "starred" } | { kind: "important" };

export function pickFilter(pick: ScopePick): SearchFilter {
  if (pick.kind === "collection" || pick.kind === "tag") return { name: pick.kind, value: pick.name, negated: false };
  return { name: "is", value: pick.kind, negated: false };
}

/** A filter a tree pick could have made (negated ones are the user's own). */
const isScope = (f: SearchFilter) =>
  !f.negated && (f.name === "collection" || f.name === "tag" || (f.name === "is" && (f.value === "starred" || f.value === "important")));

/** The filters after a pick: ``add`` (a second tag) keeps the earlier picks, otherwise
 * the pick replaces them. Every other filter stays. */
export function applyPick(filters: SearchFilter[], pick: ScopePick, add: boolean): SearchFilter[] {
  return add ? withFilter(filters, pickFilter(pick)) : [...filters.filter((f) => !isScope(f)), pickFilter(pick)];
}

export type ScopeState = { collections: string[]; tags: string[]; starred: boolean; important: boolean };

/** The picks the filters hold, for the trees to mark. */
export function scopeOf(filters: SearchFilter[]): ScopeState {
  const on = filters.filter(isScope);
  return {
    collections: on.filter((f) => f.name === "collection").map((f) => f.value),
    tags: on.filter((f) => f.name === "tag").map((f) => f.value),
    starred: on.some((f) => f.name === "is" && f.value === "starred"),
    important: on.some((f) => f.name === "is" && f.value === "important"),
  };
}
