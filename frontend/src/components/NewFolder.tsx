/** "New folder": make a folder at the top of the archive or inside the current one. The
 * sheet previews exactly what will be made as you type (the server checks the name), and
 * the result is one journaled batch that Undo removes again while the folder is empty. */
import { type FormEvent, type ReactNode, useState } from "react";
import { errorText, previewNewFolder, useCreateFolder } from "../api/client";
import { visible } from "../text";
import { PlanList } from "./PlanPreview";
import { useDebouncedPreview } from "./LayoutEditor";
import { undoAction, useToast } from "./Toasts";
import { Sheet } from "./ui/Sheet";
import { useUndoConfirm } from "./UndoConfirm";

const where = (parent: string) => (parent ? `inside ${visible(parent)}` : "at the top of the archive");

export function useNewFolder(onCreated?: (path: string) => void): { open: (parent: string) => void; view: ReactNode } {
  const [parent, setParent] = useState<string | null>(null);
  return {
    open: setParent,
    view: parent !== null && <NewFolderSheet parent={parent} onClose={() => setParent(null)} onCreated={onCreated} />,
  };
}

function NewFolderSheet({ parent, onClose, onCreated }: { parent: string; onClose: () => void; onCreated?: (path: string) => void }) {
  const [name, setName] = useState("");
  const create = useCreateFolder();
  const toast = useToast();
  const undo = useUndoConfirm();
  const trimmed = name.trim();
  const preview = useDebouncedPreview(`${parent}|${trimmed}`, () => previewNewFolder(parent, trimmed), trimmed !== "");
  const ready = trimmed !== "" && preview.data !== null && !preview.error;

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!ready || create.isPending) return;
    try {
      const result = await create.mutateAsync({ parent, name: trimmed });
      if (result.error || result.failed) {
        toast({ kind: "error", text: `The folder was not made: ${visible(result.error ?? "an operation failed")}` });
        return;
      }
      const made = result.done[0]?.dst ?? trimmed;
      onClose();
      toast({
        kind: "info",
        text: `Made the folder ${visible(made)}.`,
        action: undoAction(() => undo.open({ batchId: result.batch_id })),
      });
      onCreated?.(made);
    } catch (err) {
      toast({ kind: "error", text: `The folder was not made: ${visible(errorText(err))}` });
    }
  };

  return (
    <Sheet
      open
      title="New folder"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="new-folder-form" className="primary" disabled={!ready || create.isPending}>
            Make folder
          </button>
        </>
      }
    >
      <form id="new-folder-form" onSubmit={(e) => void submit(e)}>
        <p>
          A new folder {where(parent)}. Nothing is made until you press Make folder, and Undo removes it again while it is empty.
        </p>
        <div className="field">
          <label htmlFor="new-folder-name">Folder name</label>
          <input
            id="new-folder-name"
            type="text"
            value={name}
            autoFocus
            spellCheck={false}
            autoComplete="off"
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div aria-live="polite" className="new-folder-preview">
          {trimmed === "" ? null : preview.error ? (
            <p className="error" role="alert">
              {visible(preview.error)}
            </p>
          ) : preview.data ? (
            <PlanList ops={preview.data} />
          ) : (
            <p className="hint">Checking the name…</p>
          )}
        </div>
      </form>
    </Sheet>
  );
}
