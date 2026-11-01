/** Saved searches as addresses: where one opens, and whether Browse shows it now. */
import { filterToken, positiveTags, readQuery, serializeQuery, type SearchFilter, withFilter } from "./searchFilters";

export type SearchState = { query: string; tag_mode: "all" | "any" };

/** The query in one spelling (the words, then the filters in sorted order: their order
 * does not change what they find), and the tag mode only where it counts: with two or
 * more tags. */
function normal({ query, tag_mode }: SearchState): string {
  const { words, filters } = readQuery(query);
  const mode = positiveTags(filters).length > 1 && tag_mode === "any" ? "any" : "all";
  const tokens = filters.map((f) => filterToken({ ...f, value: f.value.toLowerCase() })).sort();
  return `${words.toLowerCase()}\n${tokens.join(" ")}\n${mode}`;
}

/** Do two searches find the same files the same way? */
export const sameSearch = (a: SearchState, b: SearchState) => normal(a) === normal(b);

/** The navigation state a saved search opens Browse with: it searches the whole archive
 * (This folder off), as its count in the sidebar does. */
export const SEARCH_EVERYWHERE = { searchEverywhere: true } as const;

/** The Browse address that runs a saved search. */
export function savedSearchHref(s: SearchState): string {
  const p = new URLSearchParams({ q: s.query });
  if (s.tag_mode === "any" && positiveTags(readQuery(s.query).filters).length > 1) p.set("tag_mode", "any");
  return `/browse?${p}`;
}

/** What Browse saves: its words and filters, with the "This folder" scope (``folder``,
 * when on) written as an ``in:`` filter so the saved search finds what was on screen. */
export function queryToSave(words: string, filters: SearchFilter[], folder: string): string {
  const all = folder ? withFilter(filters, { name: "in", value: folder, negated: false }) : filters;
  return serializeQuery(words, all);
}
