/** Undo of a journaled batch, always behind the "Undo these changes?" confirm.
 *
 * One app-level provider owns the confirm, the request and the ``undoing`` guard, so a
 * toast's Undo still works after navigating away, and only one undo ever runs app-wide. */
import { createContext, type ReactNode, type RefObject, useContext, useRef, useState } from "react";
import { errorText, useUndo, useUndoPreview } from "../api/client";
import { visible } from "../text";
import { ConfirmPlan, PlanList } from "./PlanPreview";
import { useToast } from "./Toasts";

export type UndoTarget = { batchId: string };
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
          running={undo.isPending}
          onConfirm={() => void run(request)}
          onCancel={() => setRequest(null)}
        />
      )}
    </UndoContext.Provider>
  );
}

/** The confirm, showing the server's undo preview: the exact ops undo will run. Undo
 * stays disabled until the preview has arrived, and for good when it is refused (the
 * reason is shown). */
function UndoSheet({
  batchId,
  running,
  onConfirm,
  onCancel,
}: {
  batchId: string;
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
      title="Undo these changes?"
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
