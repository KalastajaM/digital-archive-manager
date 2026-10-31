/** Delete…: a collection goes with every collection inside it: their memberships, notes,
 * checklists, summaries and links in ##. Ongoing. Files are never deleted. There is no Undo;
 * the sheet lists what goes and says so before anything happens. */
import { useEffect, useState } from "react";
import { errorText, useDeleteCollection } from "../api/client";
import { plural } from "../format";
import { changeToast } from "./collectionText";
import { useToast } from "./Toasts";
import { visible } from "../text";
import { Sheet } from "./ui/Sheet";

type Row = { id: number; name: string; state: "open" | "closed"; files: number };

export function DeleteCollectionSheet({
  c,
  onDone,
  onCancel,
}: {
  c: { id: number; name: string };
  /** After the delete (the sheet says it in a toast): how many collections went, and their names. */
  onDone: (deleted: number, names: string[]) => void;
  onCancel: () => void;
}) {
  const { remove, preview } = useDeleteCollection();
  const toast = useToast();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    preview(c.id).then(setRows, (e) => setError(errorText(e)));
    // once per collection; ``preview`` is a new function each render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [c.id]);
  const go = async () => {
    try {
      const r = await remove.mutateAsync(c.id);
      const done = r.deleted === 1 ? `Deleted ${visible(c.name)}` : `Deleted ${visible(c.name)} and the ${r.deleted - 1} inside it`;
      toast(changeToast(done, { ...r, ongoing_status: null }));
      onDone(r.deleted, (rows ?? []).map((x) => x.name));
    } catch (e) {
      setError(errorText(e));
    }
  };
  const n = rows?.length ?? 0;
  return (
    <Sheet
      open
      title={`Delete ${visible(c.name)}?`}
      onClose={onCancel}
      onKeyDown={(e) => e.stopPropagation()}
      footer={
        <>
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          {rows && (
            <button type="button" className="primary danger" disabled={remove.isPending} onClick={() => void go()}>
              {n === 1 ? "Delete the collection" : `Delete ${n} collections`}
            </button>
          )}
        </>
      }
    >
      {rows === null && !error && <p className="placeholder">Loading…</p>}
      {rows && (
        <>
          <p>{n === 1 ? "This collection goes:" : "These collections go, the one you chose and every one inside it:"}</p>
          <ul className="delete-list">
            {rows.map((r) => (
              <li key={r.id}>
                <span className="delete-name" title={visible(r.name)}>
                  {visible(r.name)}
                </span>
                <span className="delete-count">
                  {r.state === "closed" && "\u00a0(closed)"}:&nbsp;{r.files === 0 ? "no files" : plural(r.files, "file")}
                </span>
              </li>
            ))}
          </ul>
          <p>
            Their memberships, notes, checklists and summaries go with them, and their links in ##. Ongoing. Your files are not deleted
            or moved.
          </p>
          <p>
            <b>This cannot be undone.</b> A snapshot is taken first (Settings, Snapshots), so restoring it is the way back.
          </p>
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </Sheet>
  );
}
