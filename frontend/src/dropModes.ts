/** What dropping files on a folder in Browse does: Move, Link or Copy, a restore out of
 * ``##. To Delete``, or adding to a collection. Pure rules, no React: the server checks
 * the same things (``services/browse.py``); this says so before the drop, and why.
 *
 * The verdict of a drop is one of
 * - ``refused``: not allowed, with the reason (shown on the target while dragging, and in
 *   a toast when dropped anyway);
 * - ``collection``: the target is a collection's folder in ``##. Ongoing``: the only thing
 *   a drop does there is "Add to collection <name>";
 * - ``restore``: the files come from ``##. To Delete`` and go into the folder;
 * - ``files``: the move/link/copy choice, each way with the reason it is off (or null), and
 *   the way that is preselected (Option/Alt at the drop preselects Copy, as in Finder). */
import { LOCKED_REASON } from "./api/client";
import { TO_DELETE_REASON } from "./toDelete";

export type DropMode = "move" | "link" | "copy";
export const DROP_MODES: DropMode[] = ["move", "link", "copy"];

export const MODE_LABEL: Record<DropMode, string> = { move: "Move", link: "Link", copy: "Copy" };
/** The short line under each way in the choice. */
export const MODE_HINT: Record<DropMode, string> = {
  move: "the file goes there",
  link: "a shortcut there; the file stays where it is",
  copy: "not recommended: makes a duplicate",
};

export const ALREADY_HERE = "Already in this folder";
export const ONGOING_ROOT_REASON =
  "Ongoing is made from your collections: drop on a collection's folder, or use Add to collection";
export const DELETE_TARGET_REASON = "Not allowed: use Mark for deletion to send files to To Delete";
export const IMPORTANT_TARGET_REASON = "Not allowed: ##. Important is kept by the app. Mark a file Important instead";
export const TOP_REASON = "Not allowed: the top of the archive holds folders only";
export const IMPORTANT_MOVE_REASON = "This file is marked Important; unmark it first";
export const LINK_OFF_REASON = "Windows needs Developer Mode to make links: turn it on in Windows settings, or use Copy";
export const FOLDER_DRAG_REASON = "Folders can't be dropped here: drag one to a collection in the sidebar";
export const SEARCH_DROP_REASON = "Search results are not a folder: drop on a folder row or a pane showing a folder";
export const MIXED_REASON = "These files are in different places: drag them one place at a time";
export const ADD_FROM_OWN_FOLDER = "Open the file's own folder to add it to a collection, or use Add to collection";

const fold = (s: string) => s.normalize("NFC").toLowerCase();
const isUnder = (path: string, area: string) => fold(path) === fold(area) || fold(path).startsWith(`${fold(area)}/`);
const isInside = (path: string, area: string) => fold(path).startsWith(`${fold(area)}/`);
export const parentOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");

export type Areas = { quarantine: string; ongoing: string; important: string };

/** Where a dragged file lies: in one of the app's folders, or an ordinary folder. */
export type Place = "delete" | "ongoing" | "important" | "plain";
export function placeOf(path: string, areas: Areas): Place {
  if (isUnder(path, areas.quarantine)) return "delete";
  if (isUnder(path, areas.ongoing)) return "ongoing";
  if (isUnder(path, areas.important)) return "important";
  return "plain";
}

/** A dragged row, as far as the screen knows it. */
export type Dragged = { id: string; path: string; locked: boolean };

/** A collection a folder in ``##. Ongoing`` can stand for. */
export type OngoingCollection = { id: number; name: string; ongoing_rel: string | null; members: { drive_id: string }[] };

export type DropVerdict =
  | { kind: "refused"; reason: string }
  | { kind: "collection"; collection: OngoingCollection }
  | { kind: "restore"; folder: string }
  | { kind: "files"; modes: Record<DropMode, string | null>; initial: DropMode; place: Place };

export type DropInput = {
  /** The dragged rows that this screen knows (a row it does not know counts as ordinary). */
  dragged: Dragged[];
  /** How many files the drag carries (``dragged`` may know fewer). */
  count: number;
  /** The folder dropped on (archive-relative; "" the top of the archive). */
  target: string;
  areas: Areas | undefined;
  collections: OngoingCollection[] | undefined;
  /** Links can be made here (false: Windows without Developer Mode). */
  canLink: boolean;
  /** Option/Alt is held. */
  alt: boolean;
};

/** The collection whose Ongoing folder ``target`` is, or lies inside (a group's folder):
 * the deepest one. */
export function collectionAt(target: string, collections: OngoingCollection[]): OngoingCollection | null {
  let best: OngoingCollection | null = null;
  for (const c of collections) {
    if (!c.ongoing_rel || !isUnder(target, c.ongoing_rel)) continue;
    if (!best || fold(c.ongoing_rel).length > fold(best.ongoing_rel ?? "").length) best = c;
  }
  return best;
}

export function judgeDrop(input: DropInput): DropVerdict {
  const { dragged, target, areas, alt } = input;
  const refused = (reason: string): DropVerdict => ({ kind: "refused", reason });
  if (!areas) return refused("The special folders are not known yet");
  if (!target) return refused(TOP_REASON);

  const places = new Set(dragged.map((d) => placeOf(d.path, areas)));
  if (places.size > 1) return refused(MIXED_REASON);
  const place: Place = places.values().next().value ?? "plain";

  // -- the app's own folders as the target
  if (isUnder(target, areas.quarantine)) {
    return refused(place === "delete" ? "Already in To Delete" : DELETE_TARGET_REASON);
  }
  if (isUnder(target, areas.important)) return refused(IMPORTANT_TARGET_REASON);
  if (isUnder(target, areas.ongoing)) {
    if (!isInside(target, areas.ongoing)) return refused(ONGOING_ROOT_REASON);
    if (place === "delete") return refused(TO_DELETE_REASON);
    if (place !== "plain") return refused(ADD_FROM_OWN_FOLDER);
    const collection = input.collections ? collectionAt(target, input.collections) : null;
    if (!collection) return refused(ONGOING_ROOT_REASON);
    const have = new Set(collection.members.map((m) => m.drive_id));
    if (dragged.length === input.count && dragged.every((d) => have.has(d.id))) {
      return refused(`Already in ${collection.name}`);
    }
    return { kind: "collection", collection };
  }

  // -- an ordinary folder
  if (place === "delete") return { kind: "restore", folder: target };

  const here = dragged.length > 0 && dragged.length === input.count && dragged.every((d) => fold(parentOf(d.path)) === fold(target));
  const locked = dragged.some((d) => d.locked);
  const modes: Record<DropMode, string | null> = {
    move: place === "important" ? IMPORTANT_MOVE_REASON : here ? ALREADY_HERE : locked ? LOCKED_REASON : null,
    link: !input.canLink ? LINK_OFF_REASON : here ? ALREADY_HERE : null,
    copy: null,
  };
  // Dropping a file in its own folder, or a locked file anywhere: Copy only, and only when
  // asked for with Option (a plain drag there is more often a slip than a wish for a
  // duplicate, and a locked file keeps the refusal it always had).
  if (here && !alt) return refused(`${ALREADY_HERE}. Hold ⌥ (Option) while dropping to put a copy here`);
  if (locked && place === "plain" && !alt) return refused(LOCKED_REASON);
  const initial: DropMode = alt ? "copy" : modes.move === null ? "move" : modes.link === null ? "link" : "copy";
  return { kind: "files", modes, initial, place };
}

/** The reason a drag is refused, or true when a drop does something (for ``accept``). */
export const verdictAccept = (v: DropVerdict): true | string => (v.kind === "refused" ? v.reason : true);
