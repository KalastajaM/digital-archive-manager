import type { CollectionRow } from "../api/client";
import { groupDigits, plural } from "../format";

/** Parent collections: the tree of a collection list, paths and where a collection may
 * move. Names are unique across all collections, so a path of names names one. */

type Node = {
  id: number;
  name: string;
  parent_id?: number | null;
  path?: string[];
  state?: "open" | "closed";
  /** The owner's order among the collections with the same parent. */
  position?: number;
};

/** Between the names of a path, as Finder shows a path. */
export const PATH_SEP = " › ";

export const byName = (a: { name: string }, b: { name: string }) =>
  a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true });

/** The names from the root to the collection (the API's ``path``; the name alone when
 * a caller has no path). */
export const pathOf = (c: Node): string[] => (c.path && c.path.length > 0 ? c.path : [c.name]);

/** "Houses › 2026 Sauna conversion". Pass the result through ``visible`` to show it. */
export const pathLabel = (c: Node): string => pathOf(c).join(PATH_SEP);

/** The owner's order among siblings: by position, then A–Z. */
export const byPosition = (a: Node, b: Node) => (a.position ?? 0) - (b.position ?? 0) || byName(a, b);

/** The collections by parent id (null: the top), in the owner's order on each level (then A–Z). A collection whose
 * parent is not in the list (a closed one's open parent in the Closed list) is at the
 * top here. */
export function childrenOf<T extends Node>(list: readonly T[]): Map<number | null, T[]> {
  const ids = new Set(list.map((c) => c.id));
  const out = new Map<number | null, T[]>();
  for (const c of list) {
    const parent = c.parent_id != null && ids.has(c.parent_id) && c.parent_id !== c.id ? c.parent_id : null;
    const level = out.get(parent);
    if (level) level.push(c);
    else out.set(parent, [c]);
  }
  for (const level of out.values()) level.sort(byPosition);
  return out;
}

/** Whether ``id`` is ``ancestor`` or sits anywhere under it, by the parents in ``list``. */
export function isWithin(list: readonly Node[], id: number, ancestor: number): boolean {
  const parent = new Map(list.map((c) => [c.id, c.parent_id ?? null]));
  const seen = new Set<number>();
  for (let at: number | null = id; at !== null && !seen.has(at); at = parent.get(at) ?? null) {
    if (at === ancestor) return true;
    seen.add(at);
  }
  return false;
}

/** Why ``moving`` cannot go inside ``target`` (null: the top level), or null when it can.
 * The server refuses the same (a cycle, a closed parent); this only says so first. */
export function moveRefusal(list: readonly Node[], moving: Node, target: Node | null): string | null {
  if (target === null) return (moving.parent_id ?? null) === null ? `${moving.name} is already at the top level` : null;
  if (target.id === moving.id) return `${moving.name} cannot go inside itself`;
  if (isWithin(list, target.id, moving.id)) return `${target.name} is inside ${moving.name}: ${moving.name} cannot go inside it`;
  if (target.state === "closed") return `${target.name} is closed: reopen it first`;
  if ((moving.parent_id ?? null) === target.id) return `${moving.name} is already in ${target.name}`;
  return null;
}

/** Past this many recreated links a move is slow enough to say so. */
export const MANY_LINKS = 50;

/** "(recreated 51 links)" when a move recreated more than ``MANY_LINKS`` links (a move
 * takes the subtree down and recreates every link; the time grows with the count). */
export const recreatedNote = (links: number) => (links > MANY_LINKS ? ` (recreated ${groupDigits(links)} links)` : "");

/** The toast after a move: "Moved Sauna into Car", "Moved Sauna to the top level",
 * with ``recreatedNote`` when ``links`` is many. */
export const movedText = (name: string, target: string | null, links = 0) =>
  (target === null ? `Moved ${name} to the top level` : `Moved ${name} into ${target}`) + recreatedNote(links);

/** How many links the move's batch recreated (its SYMLINK ops). */
export const recreatedLinks = (result: { batch: { done: { kind: string }[] } | null }) =>
  result.batch?.done.filter((op) => op.kind === "symlink").length ?? 0;

/** What a collection holds, counted one way on every screen: "3 files", or, when a
 * folder is a member, "1 folder · 23 files" (``files``: every usable file, the folders'
 * contents included, as the list endpoint counts them; else the direct file members). */
export function holdsText(c: { members: { is_dir: boolean }[] }, files?: number): string {
  const folders = c.members.filter((m) => m.is_dir).length;
  const direct = c.members.length - folders;
  if (folders === 0) return plural(files ?? direct, "file");
  // without the list's count only the direct file members are known
  const shown = files ?? direct;
  return shown > 0 || files !== undefined ? `${plural(folders, "folder")} · ${plural(shown, "file")}` : plural(folders, "folder");
}

/** A collection's counts: "3 files · 2 collections · 1 group · 2 open checks". */
export function countsOf(c: CollectionRow, collections = 0): string {
  const parts = [holdsText(c, c.files)];
  if (collections > 0) parts.push(plural(collections, "collection"));
  if (c.groups.length > 0) parts.push(plural(c.groups.length, "group"));
  if (c.open_checks > 0) parts.push(plural(c.open_checks, "open check"));
  return parts.join(" · ");
}

/** Which edge of a row a dragged collection is over: the top quarter puts it before the
 * row, the bottom quarter after it, anything between is the middle (null). With
 * ``halves`` there is no middle: the upper half is before, the lower half after. */
export function dropZone(clientY: number, rect: { top: number; height: number }, halves = false): "before" | "after" | null {
  if (rect.height <= 0) return null;
  const at = (clientY - rect.top) / rect.height;
  if (halves) return at < 0.5 ? "before" : "after";
  return at < 0.25 ? "before" : at > 0.75 ? "after" : null;
}

/** The siblings of ``c`` in ``list`` (itself included), in the owner's order. */
export function siblingsOf<T extends Node>(list: readonly T[], c: Node): T[] {
  return childrenOf(list).get(c.parent_id != null && list.some((x) => x.id === c.parent_id) ? c.parent_id : null) ?? [];
}

/** ``list`` depth-first in the owner's order (a parent before its own, siblings by
 * position, then A–Z): the order the API lists them in, for a list that may not be. */
export function inTreeOrder<T extends Node>(list: readonly T[]): T[] {
  const kids = childrenOf(list);
  const out: T[] = [];
  const seen = new Set<number>();
  const walk = (parent: number | null) => {
    for (const c of kids.get(parent) ?? []) {
      if (seen.has(c.id)) continue;
      seen.add(c.id);
      out.push(c);
      walk(c.id);
    }
  };
  walk(null);
  return out;
}

/** Tree order: by the names of the path, A–Z on each level (a parent before its own). */
export function byPath(a: Node, b: Node): number {
  const pa = pathOf(a);
  const pb = pathOf(b);
  for (let i = 0; i < Math.min(pa.length, pb.length); i++) {
    const d = byName({ name: pa[i] }, { name: pb[i] });
    if (d !== 0) return d;
  }
  return pa.length - pb.length;
}

/** ``id`` and every collection under it in ``list``, found in one walk down the tree. */
export function subtreeOf(list: readonly Node[], id: number): Set<number> {
  const kids = childrenOf(list);
  const out = new Set<number>([id]);
  const todo = [id];
  while (todo.length > 0) {
    for (const child of kids.get(todo.pop()!) ?? []) {
      if (!out.has(child.id)) {
        out.add(child.id);
        todo.push(child.id);
      }
    }
  }
  return out;
}

/** One collection move at a time in this window, from the sidebar or a collection
 * page: synchronous, so a second drop or a second Move sees it at once. */
let moveRunning = false;
export const collectionMoveRunning = () => moveRunning;
/** True when this caller may move now (and holds the guard until ``endCollectionMove``). */
export function startCollectionMove(): boolean {
  if (moveRunning) return false;
  moveRunning = true;
  return true;
}
export function endCollectionMove() {
  moveRunning = false;
}
