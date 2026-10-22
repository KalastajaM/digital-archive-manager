/** Mark for deletion = move into ``##. To Delete`` (mirrored path), never a delete.
 *
 * Always a dry run first; the confirm shows its exact ops, and the confirm sends exactly the
 * previewed drive ids. A preview that answers for a selection that has changed since
 * is dropped, and a preview that reports a failure offers no confirm. */
import { type RefObject, useRef, useState } from "react";
import { ApiError, type BatchResult, errorText, type ResolvedOp, useQuarantine } from "../api/client";
import { useToast } from "../components/Toasts";
import { unexpectedDestinations } from "./useFiling";

/** A dry run's plan together with the exact ids it was computed for. */
export type DeletionPreview = { ids: string[]; batchId: string; ops: ResolvedOp[] };

/** ``refusal``: the server refused the request; ``text`` is its own reason. */
export type DeletionMessage = { text: string; kind: "error" | "notice"; refusal?: boolean };

export const SELECTION_CHANGED = "Selection changed — press Move to To Delete again";
export const NOTHING_TO_MARK = "Nothing to mark: the dry run planned no changes.";

/** The server's refusal of a protected path (a custom one, not caught up front), in
 * plain words. */
export const PROTECTED = "Some of these are in a protected folder and cannot be moved to To Delete.";
const plain = (e: unknown) => {
  const text = errorText(e);
  if (/protected (path )?and cannot be quarantined|comes from a protected path/.test(text)) return PROTECTED;
  // A refusal (400) is the server's own reason, e.g. "This file is marked Important;
  // unmark it first: …", without "Invalid request:" in front of it.
  return e instanceof ApiError && e.status === 400 && e.detail ? e.detail : text;
};

const sameIds = (a: string[] | null, b: string[]) => a !== null && JSON.stringify(a) === JSON.stringify(b);

const failure = (result: BatchResult) => {
  const op = result.failed ? ` (${result.failed.kind} ${result.failed.src ?? result.failed.dst})` : "";
  return `${result.error ?? "an operation failed"}${op}`;
};

/** ``selection`` holds the currently selected drive ids (the screen keeps it current). */
/** ``events``: ``confirming`` runs in the same update that opens the confirm (so a
 * dialog under it can close in the same commit); ``message`` gets every message as it
 * is set. */
export function useMarkForDeletion(
  selection: RefObject<string[] | null>,
  onApplied: (result: BatchResult, complete: boolean) => void,
  events: { confirming?: (previewed: DeletionPreview) => void; message?: (m: DeletionMessage) => void } = {},
) {
  const quarantine = useQuarantine();
  const toast = useToast();
  const [confirm, setConfirm] = useState<DeletionPreview | null>(null);
  const [message, setShown] = useState<DeletionMessage | null>(null);
  const setMessage = (m: DeletionMessage | null) => {
    setShown(m);
    if (m) events.message?.(m);
  };
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false); // synchronous: a second click sees it at once

  async function guarded(work: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      await work();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function preview(ids: string[]) {
    setMessage(null);
    let dry: BatchResult;
    try {
      dry = await quarantine.mutateAsync({ drive_ids: ids, dry_run: true });
    } catch (e) {
      setMessage(
        sameIds(selection.current, ids)
          ? { kind: "error", text: plain(e), refusal: true }
          : { kind: "notice", text: SELECTION_CHANGED },
      );
      return;
    }
    if (!sameIds(selection.current, ids)) {
      setMessage({ kind: "notice", text: SELECTION_CHANGED });
      return;
    }
    if (dry.error || dry.failed) {
      setMessage({ kind: "error", text: `Cannot move to To Delete: ${failure(dry)}` });
      return;
    }
    if (dry.done.length === 0) {
      setMessage({ kind: "notice", text: NOTHING_TO_MARK });
      return;
    }
    const previewed = { ids, batchId: dry.batch_id, ops: dry.done };
    setConfirm(previewed);
    events.confirming?.(previewed);
  }

  async function apply(previewed: DeletionPreview) {
    setConfirm(null);
    if (!sameIds(selection.current, previewed.ids)) {
      setMessage({ kind: "notice", text: SELECTION_CHANGED });
      return;
    }
    let result: BatchResult;
    try {
      result = await quarantine.mutateAsync({ drive_ids: previewed.ids, dry_run: false });
    } catch (e) {
      setMessage({ kind: "error", text: plain(e), refusal: true });
      return;
    }
    const complete = !result.error && !result.failed;
    if (!complete) {
      setMessage({ kind: "error", text: `Stopped after ${result.done.length} change(s): ${failure(result)}` });
    }
    const moved = unexpectedDestinations(result.done, previewed.ops);
    if (moved.length > 0) {
      toast({ kind: "warning", text: `Moved somewhere other than previewed: ${moved.join(", ")}` });
    }
    if (result.index_error) {
      toast({
        kind: "warning",
        text: `Index update failed: ${result.index_error}. The next scan repairs it.`,
      });
    }
    onApplied(result, complete);
  }

  return {
    busy,
    inFlight,
    confirm,
    message,
    /** Dry-run these ids and show the confirm (or the reason there is none). */
    start: (ids: string[]) => void guarded(() => preview(ids)),
    /** Apply exactly what the confirm showed. */
    confirmApply: () => {
      const previewed = confirm;
      if (previewed) void guarded(() => apply(previewed));
    },
    cancel: () => setConfirm(null),
  };
}
