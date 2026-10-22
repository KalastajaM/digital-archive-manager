/** "Set up folders" inside the running app: choose a starter layout, edit the list, see
 * every folder that will be made, then make them (one journaled batch). Only folders that
 * do not exist yet are made; nothing that is there is touched. The special folder names
 * are the configured ones. */
import { type ReactNode, useState } from "react";
import { errorText, previewLayout, useCreateLayout, useLayoutTemplates } from "../api/client";
import { visible } from "../text";
import { initialLayout, LayoutEditor, LayoutPreviewList, layoutBody, type LayoutState, useDebouncedPreview } from "./LayoutEditor";
import { undoAction, useToast } from "./Toasts";
import { Sheet } from "./ui/Sheet";
import { useUndoConfirm } from "./UndoConfirm";

export function useSetupFolders(): { open: () => void; view: ReactNode } {
  const [open, setOpen] = useState(false);
  return { open: () => setOpen(true), view: open && <SetupFoldersSheet onClose={() => setOpen(false)} /> };
}

function SetupFoldersSheet({ onClose }: { onClose: () => void }) {
  const templates = useLayoutTemplates();
  const [edited, setEdited] = useState<LayoutState | null>(null);
  const create = useCreateLayout();
  const toast = useToast();
  const undo = useUndoConfirm();
  const data = templates.data;
  const layout = edited ?? (data && data.templates.length > 0 ? initialLayout(data.templates, data.special_folders) : null);
  const body = layout ? layoutBody(layout, false) : null;
  const preview = useDebouncedPreview(JSON.stringify(body), () => previewLayout(body!), body !== null);
  const ready = preview.data !== null && preview.data.to_create > 0 && !preview.error;

  const make = async () => {
    if (!body || !ready || create.isPending) return;
    try {
      const result = await create.mutateAsync(body);
      const batch = result.batch;
      if (!batch || batch.error || batch.failed) {
        toast({ kind: "error", text: `Not all folders were made: ${visible(batch?.error ?? "an operation failed")}` });
        return;
      }
      onClose();
      toast({
        kind: "info",
        text: `Made ${result.created} folders.${result.rules_written ? " Example filing rules were saved for them." : ""}`,
        action: undoAction(() => undo.open({ batchId: batch.batch_id })),
      });
      if (result.rules_error) toast({ kind: "warning", text: result.rules_error });
    } catch (e) {
      toast({ kind: "error", text: `The folders were not made: ${visible(errorText(e))}` });
    }
  };

  return (
    <Sheet
      open
      title="Set up folders"
      onClose={onClose}
      className="setup-folders"
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={!ready || create.isPending} onClick={() => void make()}>
            {preview.data && preview.data.to_create > 0 ? `Make ${preview.data.to_create} folders` : "Make folders"}
          </button>
        </>
      }
    >
      {templates.isError && (
        <p className="error" role="alert">
          {errorText(templates.error)}
        </p>
      )}
      {!layout && !templates.isError && <p className="placeholder">Loading…</p>}
      {layout && data && (
        <>
          <LayoutEditor
            templates={data.templates}
            specials={data.special_folders}
            state={layout}
            onChange={setEdited}
            specialLocked
            disabled={create.isPending}
          />
          {preview.error ? (
            <p className="error" role="alert">
              {visible(preview.error)}
            </p>
          ) : preview.data ? (
            <LayoutPreviewList preview={preview.data} />
          ) : (
            <p className="hint">Checking the folders…</p>
          )}
        </>
      )}
    </Sheet>
  );
}
