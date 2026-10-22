/** The confirmation before an item is removed from its tray (open or done). Removing
 * deletes the item with its note, checklist and history; the files are never touched, so
 * there is no undo and the sheet says so. */
import { useState } from "react";
import { errorText, type Item, useRemoveItem } from "../api/client";
import { visible } from "../text";
import { Sheet } from "./ui/Sheet";

export function RemoveItemSheet({ item, onClose, onRemoved }: { item: Pick<Item, "id" | "title" | "tray_name">; onClose: () => void; onRemoved: () => void }) {
  const remove = useRemoveItem();
  const [error, setError] = useState<string | null>(null);
  const confirm = async () => {
    setError(null);
    try {
      await remove.mutateAsync(item.id);
      onRemoved();
    } catch (e) {
      setError(errorText(e));
    }
  };
  return (
    <Sheet
      open
      title={`Remove ${visible(item.title)} from ${visible(item.tray_name)}?`}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={remove.isPending} onClick={() => void confirm()}>
            Remove from tray
          </button>
        </>
      }
    >
      <p>
        The item, its note, checklist and history are deleted. The files stay where they are, and you can put them in a
        tray again.
      </p>
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </Sheet>
  );
}
