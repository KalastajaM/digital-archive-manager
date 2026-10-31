/** A collection row's right-click menu and its sheets: Open, New collection inside…,
 * Merge into…, Delete…, then Move up / Move down / Move out one level. One place for
 * Browse's collection tree and the sidebar, so both say and do the same. */
import { type ReactNode, useState } from "react";
import type { CollectionRow } from "../api/client";
import { DeleteCollectionSheet } from "./DeleteCollectionSheet";
import { MergeCollectionSheet } from "./MergeCollectionSheet";
import { NewCollectionSheet } from "./NewCollectionSheet";
import { useToast } from "./Toasts";
import { type CollectionOrder, useOrderMenu } from "./useCollectionOrder";

type Named = { id: number; name: string };

/** ``list``: the collections shown (a merge picks from them). ``open``: how a collection
 * opens here (also the one just made, or the one merged into). ``onDeleted``: the names
 * of every collection a delete took (the inner ones too). */
export function useCollectionMenu(
  list: CollectionRow[],
  order: CollectionOrder,
  { open, onDeleted }: { open: (c: Named) => void; onDeleted?: (names: string[]) => void },
) {
  const toast = useToast();
  const [creating, setCreating] = useState<{ parent: CollectionRow | null } | null>(null);
  const [merging, setMerging] = useState<CollectionRow | null>(null);
  const [deleting, setDeleting] = useState<CollectionRow | null>(null);
  const menu = useOrderMenu(order, (c) => [
    { label: "Open", onSelect: () => open(c) },
    { label: "New collection inside…", onSelect: () => setCreating({ parent: c }) },
    { label: "Merge into…", onSelect: () => setMerging(c) },
    { label: "Delete…", onSelect: () => setDeleting(c) },
  ]);
  const view: ReactNode = (
    <>
      {menu.element}
      {deleting && (
        <DeleteCollectionSheet
          c={deleting}
          onCancel={() => setDeleting(null)}
          onDone={(_, names) => {
            setDeleting(null);
            onDeleted?.(names);
          }}
        />
      )}
      {merging && (
        <MergeCollectionSheet
          c={merging}
          all={list}
          onCancel={() => setMerging(null)}
          onDone={(into) => {
            setMerging(null);
            open(into);
          }}
        />
      )}
      {creating && (
        <NewCollectionSheet
          parent={creating.parent}
          onCancel={() => setCreating(null)}
          onCreated={(child) => {
            setCreating(null);
            toast({ kind: "info", text: creating.parent ? `Created ${child.name} inside ${creating.parent.name}` : `Created ${child.name}` });
            open(child);
          }}
        />
      )}
    </>
  );
  return {
    onContextMenu: menu.onContextMenu,
    /** New collection at the top level (``null``) or inside one. */
    startNew: (parent: CollectionRow | null) => setCreating({ parent }),
    view,
  };
}
