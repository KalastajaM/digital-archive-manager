/** Undo of a journaled batch, always behind the "Undo these changes?" confirm (for a
 * folder rename, "Undo the folder rename?", naming the folder's new and old name).
 *
 * One app-level provider owns the confirm, the request and the ``undoing`` guard, so a
 * toast's Undo still works after navigating away, and only one undo ever runs app-wide. */
import { createContext, type ReactNode, type RefObject, useContext, useRef, useState } from "react";
import { errorText, type FolderRenameRecord, useUndo, useUndoPreview } from "../api/client";
import { parentOf } from "../paths";
import { visible } from "../text";
import { ConfirmPlan, PlanList } from "./PlanPreview";
import { useToast } from "./Toasts";

/** ``rename``: the batch is a folder rename (Activity's ``folder_rename``), so the confirm
 * says which folder gets which name back. */
export type UndoTarget = { batchId: string; rename?: FolderRenameRecord | null };
type Request = { target: UndoTarget; onUndone?: (batchId: string) => void };

type UndoState = {
  open: (request: Request) => void;
  target: UndoTarget | null;
  /** Synchronous: true from the confirm click until the answer (a disabled button can
   * lag a click). */
  undoing: RefObject<boolean>;
  pending: boolean;
};

const UndoContext = createContext<UndoState | null>(null);

export function UndoProvider({ children }: { children: ReactNode }) {
  const undo = useUndo();
  const toast = useToast();
  const [request, setRequest] = useState<Request | null>(null);
  const undoing = useRef(false);

  const run = async ({ target, onUndone }: Request) => {
    if (undoing.current) return;
    undoing.current = true;
    try {
      const result = await undo.mutateAsync(target.batchId);
      setRequest(null);
      const stopped = result.error || result.failed;
      if (stopped) {
        toast({ kind: "error", text: `Undo stopped: ${result.error ?? "an operation failed"}` });
      }
      // Removing what the batch created (tray items, collection entries, notes) can fail
      // on its own: say so, never swallow it.
      if (result.follow_up_error) {
        const text = stopped ? result.follow_up_error : `Files restored, but: ${result.follow_up_error}`;
        toast({ kind: "warning", text });
      }
      if (!stopped) {
        if (result.kept && result.kept.length > 0) {
          const names = result.kept.map(visible).join(", ");
          toast({
            kind: "info",
            text: `Undone. ${result.kept.length === 1 ? "A folder has" : `${result.kept.length} folders have`} something in them now and stays: ${names}`,
          });
        } else if (!result.follow_up_error) toast({ kind: "info", text: "Undone." });
        onUndone?.(target.batchId);
      }
    } catch (e) {
      setRequest(null);
      toast({ kind: "error", text: `Undo failed: ${errorText(e)}` });
    } finally {
      undoing.current = false;
    }
  };

  const state: UndoState = {
    open: (r) => {
      if (!undoing.current) setRequest(r);
    },
    target: request?.target ?? null,
    undoing,
    pending: undo.isPending,
  };
  return (
    <UndoContext.Provider value={state}>
      {children}
      {request && (
        <UndoSheet
          key={request.target.batchId}
          batchId={request.target.batchId}
          rename={request.target.rename ?? null}
          running={undo.isPending}
          onConfirm={() => void run(request)}
          onCancel={() => setRequest(null)}
        />
      )}
    </UndoContext.Provider>
  );
}

const lastName = (path: string) => path.slice(path.lastIndexOf("/") + 1);

/** What undoing a folder rename does, in words: the folder that gets its old name back,
 * and what goes back with it. ``old`` and ``new`` are archive paths for a folder renamed
 * in Browse, names for a special folder. */
export function renameUndoWords(r: FolderRenameRecord): { what: string; follows: string } {
  if (r.key === "folder") {
    const where = parentOf(r.old);
    return {
      what:
        `The folder '${visible(lastName(r.new))}' gets its old name '${visible(lastName(r.old))}' back` +
        (where ? `, in ${visible(where)}.` : "."),
      follows:
        "The index, rules, filing codes and settings that hold its path go back with it. dam stops for a few seconds while it opens the archive again.",
    };
  }
  return {
    what: `The ${r.title ?? "special"} folder '${visible(r.new)}' gets its old name '${visible(r.old)}' back.`,
    follows:
      "The settings, rules and index that hold its name go back with it. dam stops for a few seconds while it opens the archive again.",
  };
}

/** The confirm, showing the server's undo preview: the exact ops undo will run. Undo
 * stays disabled until the preview has arrived, and for good when it is refused (the
 * reason is shown). A folder rename says in words which folder gets which name back. */
function UndoSheet({
  batchId,
  rename,
  running,
  onConfirm,
  onCancel,
}: {
  batchId: string;
  rename: FolderRenameRecord | null;
  running: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const preview = useUndoPreview(batchId);
  let body: ReactNode;
  if (preview.isPending) body = <p className="placeholder">Checking what undo will do…</p>;
  else if (preview.isError) {
    body = (
      <p className="error" role="alert">
        Cannot undo: {visible(errorText(preview.error))}
      </p>
    );
  } else if (rename) {
    const words = renameUndoWords(rename);
    body = (
      <>
        <p>{words.what}</p>
        <PlanList ops={preview.data} />
        <p className="hint">{words.follows}</p>
      </>
    );
  } else {
    body = (
      <>
        <p>Undoing will:</p>
        <PlanList ops={preview.data} />
        {preview.data.length > 0 && preview.data.every((op) => op.kind === "remove_empty_dir") ? (
          <p className="hint">Only folders that are still empty are removed; a folder with something in it stays.</p>
        ) : (
          <p className="hint">New folders it created stay, empty.</p>
        )}
      </>
    );
  }
  return (
    <ConfirmPlan
      planKey={batchId}
      title={rename ? "Undo the folder rename?" : "Undo these changes?"}
      confirmLabel="Undo"
      ops={preview.data ?? []}
      busy={running || !preview.isSuccess}
      onConfirm={onConfirm}
      onCancel={onCancel}
    >
      {body}
    </ConfirmPlan>
  );
}

/** ``open(target)`` asks before undoing it (ignored while an undo is running);
 * ``onUndone`` runs after a complete undo. */
export function useUndoConfirm(onUndone?: (batchId: string) => void) {
  const state = useContext(UndoContext);
  if (!state) throw new Error("useUndoConfirm needs an <UndoProvider>");
  return {
    open: (target: UndoTarget) => state.open({ target, onUndone }),
    target: state.target,
    undoing: state.undoing,
    pending: state.pending,
  };
}
