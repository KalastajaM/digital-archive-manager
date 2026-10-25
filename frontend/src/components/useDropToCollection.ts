/** Dropping files from Browse on a collection's folder in ##. Ongoing adds them to that
 * collection (the membership API; the link appears when Ongoing is rebuilt). No confirm:
 * a member change moves no file. The toast says what Ongoing did and offers Undo, which
 * takes out what this drop added. */
import { useRef } from "react";
import { type CollectionRow, errorText, useCollectionMembers } from "../api/client";
import { draggedLabel } from "../dnd";
import { plural } from "../format";
import { visible } from "../text";
import { changeToast } from "./collectionText";
import { useToast } from "./Toasts";

export function useDropToCollection() {
  const members = useCollectionMembers();
  const toast = useToast();
  const adding = useRef(new Set<number>()); // synchronous: a second drop sees it at once
  return (c: CollectionRow, ids: string[]) => {
    if (adding.current.has(c.id)) return;
    adding.current.add(c.id);
    const label = ids.length === 1 ? draggedLabel() : null;
    const what = label !== null ? visible(label) : plural(ids.length, "file");
    const name = visible(c.name);
    const had = new Set(c.members.map((m) => m.drive_id));
    const added = ids.filter((id) => !had.has(id));
    members
      .mutateAsync({ id: c.id, add: ids })
      .then((result) => {
        const undo = async () => {
          try {
            for (const id of added) await members.mutateAsync({ id: c.id, remove: id });
          } catch (e) {
            toast({ kind: "error", text: `Could not take ${what} out of ${name}: ${visible(errorText(e))}` });
          }
        };
        toast({ ...changeToast(`Added ${what} to ${name}`, result), actions: [{ label: "Undo", run: () => void undo() }] });
      })
      .catch((err) => toast({ kind: "error", text: `Could not add ${what} to ${name}: ${visible(errorText(err))}` }))
      .finally(() => adding.current.delete(c.id));
  };
}
