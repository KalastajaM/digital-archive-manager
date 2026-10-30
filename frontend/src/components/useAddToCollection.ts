/** Dropping files on a collection (the sidebar's rows, Browse's collection tree). */
import { useRef } from "react";
import { type CollectionRow, errorText, useCollectionMembers, useCollections } from "../api/client";
import { draggedLabel } from "../dnd";
import { plural } from "../format";
import { visible } from "../text";
import { changeToast } from "./collectionText";
import { undoAction, useToast } from "./Toasts";

const dropped = (ids: string[]) => {
  const label = ids.length === 1 ? draggedLabel() : null;
  return label !== null ? visible(label) : plural(ids.length, "file");
};

/** Dropping documents on a collection adds them as members. No confirm: a member change
 * moves no file (the Phase 2 ruling); the toast says what Ongoing did. Files dragged from
 * a collection (``from``) onto another collection of the same tree are moved there
 * instead, with Undo, as groups used to sort them. */
export function useAddToCollection() {
  const members = useCollectionMembers();
  const open = useCollections("open");
  const toast = useToast();
  const adding = useRef(new Set<number>()); // synchronous: a second drop sees it at once
  const byId = new Map((open.data ?? []).map((c) => [c.id, c]));
  const top = (id: number): number => {
    const seen = new Set<number>();
    let at = id;
    for (let p = byId.get(at)?.parent_id; p != null && byId.has(p) && !seen.has(p); p = byId.get(at)?.parent_id) {
      seen.add(p);
      at = p;
    }
    return at;
  };
  /** The collection the files move out of, or null: they are added. */
  const source = (c: CollectionRow, from?: number | null) =>
    from != null && from !== c.id && byId.has(from) && top(from) === top(c.id) ? (byId.get(from) ?? null) : null;
  const accept = (c: CollectionRow) => (ids: string[]) => {
    const name = visible(c.name);
    if (c.state === "closed") return `${name} is closed: reopen it to add files`;
    const have = new Set(c.members.map((m) => m.drive_id));
    if (ids.every((id) => have.has(id))) return `Already in ${name}`;
    return true;
  };
  const add = (c: CollectionRow) => (ids: string[], from?: number | null) => {
    if (adding.current.has(c.id)) return;
    adding.current.add(c.id);
    const what = dropped(ids);
    const name = visible(c.name);
    const out = source(c, from);
    const moveBack = (back: CollectionRow) => () =>
      void members
        .mutateAsync({ id: c.id, move: { to: back.id, ids } })
        .then((result) => toast(changeToast(`Moved ${what} back to ${visible(back.name)}`, result)))
        .catch((err) => toast({ kind: "error", text: `Could not move ${what} back: ${visible(errorText(err))}` }));
    (out
      ? members
          .mutateAsync({ id: out.id, move: { to: c.id, ids } })
          .then((result) => toast({ ...changeToast(`Moved ${what} from ${visible(out.name)} to ${name}`, result), action: undoAction(moveBack(out)) }))
      : members.mutateAsync({ id: c.id, add: ids }).then((result) => toast(changeToast(`Added ${what} to ${name}`, result)))
    )
      .catch((err) => toast({ kind: "error", text: `Could not ${out ? "move" : "add"} ${what} to ${name}: ${visible(errorText(err))}` }))
      .finally(() => adding.current.delete(c.id));
  };
  return { accept, add };
}
