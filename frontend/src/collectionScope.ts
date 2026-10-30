/** Which collection a Browse search is scoped to (the collection tree's pick, a
 * `collection:` chip), so Browse can show that collection above its files, and which of
 * its child collections a listed file comes from. */
import type { CollectionRow } from "./api/client";
import { childrenOf } from "./components/collectionTree";
import type { SearchFilter } from "./searchFilters";

/** A name as the search compares it: NFC, case ignored, and without quote marks (a
 * filter value cannot carry one; the backend ignores them the same way). */
const fold = (name: string) => name.normalize("NFC").replace(/"/g, "").trim().toLowerCase();

/** The one collection ``filters`` scope the search to: one positive `collection:`
 * filter, or `is:starred` on its own (Starred). ``missing``: the name matches no
 * collection (renamed since the link was made). Null: no single collection. */
export function scopedCollection(filters: SearchFilter[], all: CollectionRow[]): { c: CollectionRow } | { missing: string } | null {
  const named = filters.filter((f) => !f.negated && f.name === "collection");
  const starred = filters.some((f) => !f.negated && f.name === "is" && f.value === "starred");
  if (named.length + (starred ? 1 : 0) !== 1) return null;
  if (starred) {
    const c = all.find((x) => x.kind === "starred");
    return c ? { c } : null;
  }
  const want = fold(named[0].value);
  const c = all.find((x) => !x.kind && fold(x.name) === want);
  return c ? { c } : { missing: named[0].value };
}

/** The child collection of ``scope`` (at any depth, the nearest first, then in the tree's
 * order) that holds ``driveId`` itself; null when ``scope`` holds it or none does. */
export function childOf(driveId: string, scope: CollectionRow, all: CollectionRow[]): string | null {
  const kids = childrenOf(all);
  let level = kids.get(scope.id) ?? [];
  const seen = new Set<number>([scope.id]);
  while (level.length > 0) {
    const holder = level.find((c) => c.members.some((m) => m.drive_id === driveId));
    if (holder) return holder.name;
    level.forEach((c) => seen.add(c.id));
    level = level.flatMap((c) => kids.get(c.id) ?? []).filter((c) => !seen.has(c.id));
  }
  return null;
}
