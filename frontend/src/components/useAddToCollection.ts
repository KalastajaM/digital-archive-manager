/** Dropping files on a collection (the sidebar's rows, Browse's collection tree). */
import { useRef } from "react";
import { type CollectionRow, errorText, useCollectionMembers } from "../api/client";
import { draggedLabel } from "../dnd";
import { plural } from "../format";
import { visible } from "../text";
import { changeToast } from "./collectionText";
import { useToast } from "./Toasts";

const dropped = (ids: string[]) => {
  const label = ids.length === 1 ? draggedLabel() : null;
  return label !== null ? visible(label) : plural(ids.length, "file");
};

/** Dropping documents on a collection adds them as members, ungrouped. No confirm: a
 * member change moves no file (the Phase 2 ruling); the toast says what Ongoing did. */
export function useAddToCollection() {
  const members = useCollectionMembers();
  const toast = useToast();
  const adding = useRef(new Set<number>()); // synchronous: a second drop sees it at once
  const accept = (c: CollectionRow) => (ids: string[]) => {
    const name = visible(c.name);
    if (c.state === "closed") return `${name} is closed: reopen it to add files`;
    const have = new Set(c.members.map((m) => m.drive_id));
    if (ids.every((id) => have.has(id))) return `Already in ${name}`;
    return true;
  };
  const add = (c: CollectionRow) => (ids: string[]) => {
    if (adding.current.has(c.id)) return;
    adding.current.add(c.id);
    const what = dropped(ids);
    const name = visible(c.name);
    members
      .mutateAsync({ id: c.id, add: ids })
      .then((result) => toast(changeToast(`Added ${what} to ${name}`, result)))
      .catch((err) => toast({ kind: "error", text: `Could not add ${what} to ${name}: ${visible(errorText(err))}` }))
      .finally(() => adding.current.delete(c.id));
  };
  return { accept, add };
}
