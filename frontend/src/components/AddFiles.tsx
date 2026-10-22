/** Getting documents in: "Choose files…" copies the chosen files into the inbox. The
 * originals stay where they are; a taken name gets _2; nothing is overwritten. Each file
 * is one journaled batch (Undo moves the copy to To Delete). */
import { type ReactNode, useRef, useState } from "react";
import { type ApiError, errorText, useUploadToInbox } from "../api/client";
import { plural } from "../format";
import { visible } from "../text";
import { undoAction, useToast } from "./Toasts";
import { useUndoConfirm } from "./UndoConfirm";

/** The biggest file the inbox takes (the server's limit, ``MAX_COPY_BYTES``). */
export const MAX_UPLOAD_MB = 200;

export function useAddFiles(): { choose: () => void; busy: boolean; view: ReactNode } {
  const upload = useUploadToInbox();
  const toast = useToast();
  const undo = useUndoConfirm();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const running = useRef(false);

  async function addAll(files: File[]) {
    if (running.current || files.length === 0) return;
    running.current = true;
    setBusy(true);
    const added: string[] = [];
    const problems: string[] = [];
    try {
      for (const file of files) {
        if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
          problems.push(`${visible(file.name)}: larger than ${MAX_UPLOAD_MB} MB`);
          continue;
        }
        try {
          const result = await upload.mutateAsync(file);
          if (result.error || result.failed) problems.push(`${visible(file.name)}: ${visible(result.error ?? "the copy failed")}`);
          else added.push(result.batch_id);
        } catch (e) {
          problems.push(`${visible(file.name)}: ${visible((e as ApiError).detail || errorText(e))}`);
        }
      }
    } finally {
      running.current = false;
      setBusy(false);
    }
    if (added.length > 0) {
      toast({
        kind: "info",
        text: `Copied ${plural(added.length, "file")} into the inbox.${added.length > 1 ? " Undo each one from Activity." : ""}`,
        action: added.length === 1 ? undoAction(() => undo.open({ batchId: added[0] })) : undefined,
      });
    }
    if (problems.length > 0) toast({ kind: "error", text: `Not copied: ${problems.join("; ")}` });
  }

  return {
    choose: () => input.current?.click(),
    busy,
    view: (
      <input
        ref={input}
        type="file"
        multiple
        hidden
        data-testid="add-files-input"
        aria-label="Choose files to copy into the inbox"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = ""; // the same file can be chosen again
          void addAll(files);
        }}
      />
    ),
  };
}
