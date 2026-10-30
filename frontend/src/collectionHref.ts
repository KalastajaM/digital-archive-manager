/** Where a collection opens: in Browse, as a search of it with the Collections tree
 * beside it (its header and details show above its files); Important keeps its own page. */
import { filterToken } from "./searchFilters";

export function collectionHref(c: { id: number; name: string; kind?: string | null }): string {
  if (c.kind === "important") return "/important";
  const q = c.kind === "starred" ? "is:starred" : filterToken({ name: "collection", value: c.name, negated: false });
  return `/browse?${new URLSearchParams({ tree: "collections", q })}`;
}
