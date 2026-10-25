/** Restore: take files and folders out of ``##. To Delete`` again, one or a selection.
 *
 * "Restore to where it was" (the path they were marked at; a folder that is gone is made
 * again, a name that is taken gets a number, and the preview says both) or "Restore to
 * Inbox". It is a normal previewed batch: a dry run, the confirm with its exact ops, the
 * move, and a toast with Undo (which puts them back in To Delete). Nothing is deleted. */
import { type ReactNode, useRef, useState } from "react";
import { ApiError, type BatchResult, errorText, type ResolvedOp, useRestore } from "../api/client";
import { plural } from "../format";
import { dialogOpen } from "../keyboard";
import { visible } from "../text";
import { ConfirmPlan } from "./PlanPreview";
import { undoAction, useBlockToastActions, useToast } from "./Toasts";
import type { MenuEntry } from "./ui/Menu";
import { useUndoConfirm } from "./UndoConfirm";

export type RestoreTo = "original" | "inbox";

export const RESTORE_LABEL: Record<RestoreTo, string> = {
  original: "Restore to where it was",
  inbox: "Restore to Inbox",
};

type Preview = { ids: string[]; to: RestoreTo; batchId: string; ops: ResolvedOp[] };

const refusal = (e: unknown) => (e instanceof ApiError && e.detail ? e.detail : errorText(e));

/** The menu entries that restore ``ids`` (disabled, with ``reason``, when they cannot). */
export function restoreEntries(start: (to: RestoreTo) => void, reason: string | null): Exclude<MenuEntry, "separator">[] {
  return (["original", "inbox"] as const).map((to) => ({
    label: RESTORE_LABEL[to],
    disabled: reason !== null,
    reason: reason ?? undefined,
    onSelect: () => start(to),
  }));
}

/** One screen's Restore flow: ``start(ids, to)`` dry-runs and opens the confirm; render
 * ``view``. ``onRestored`` runs after an apply (complete or not). */
export function useRestoreFlow({ onRestored }: { onRestored?: (result: BatchResult) => void } = {}) {
  const restore = useRestore();
  const toast = useToast();
  const undo = useUndoConfirm();
  const [confirm, setConfirm] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false); // synchronous: a second click sees it at once
  useBlockToastActions(busy || confirm !== null);

  const guarded = async (work: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      await work();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const preview = async (ids: string[], to: RestoreTo) => {
    let dry: BatchResult;
    try {
      dry = await restore.mutateAsync({ drive_ids: ids, to, dry_run: true });
    } catch (e) {
      toast({ kind: "error", text: `Not restored: ${visible(refusal(e))}` });
      return;
    }
    if (dry.error || dry.failed) {
      toast({ kind: "error", text: `Cannot restore: ${visible(dry.error ?? "an operation failed")}` });
      return;
    }
    if (dry.done.length === 0) {
      toast({ kind: "info", text: "Nothing to restore: the dry run planned no changes." });
      return;
    }
    setConfirm({ ids, to, batchId: dry.batch_id, ops: dry.done });
  };

  const apply = async (previewed: Preview) => {
    setConfirm(null);
    let result: BatchResult;
    try {
      result = await restore.mutateAsync({ drive_ids: previewed.ids, to: previewed.to, dry_run: false });
    } catch (e) {
      toast({ kind: "error", text: `Not restored: ${visible(refusal(e))}` });
      return;
    }
    const complete = !result.error && !result.failed;
    const moved = result.done.filter((op) => op.kind === "move");
    if (!complete) {
      toast({ kind: "error", text: `Stopped after ${result.done.length} change(s): ${visible(result.error ?? "an operation failed")}` });
    }
    if (moved.length > 0) {
      const target = { batchId: result.batch_id };
      toast({
        kind: complete ? "info" : "warning",
        text: `${complete ? "" : "Partly applied: "}Restored ${restoredWhat(moved)} from To Delete${previewed.to === "inbox" ? " to the inbox" : ""}`,
        action: undoAction(() => {
          if (inFlight.current || undo.undoing.current || dialogOpen()) return;
          undo.open(target);
        }),
      });
    }
    onRestored?.(result);
  };

  const view: ReactNode = confirm && (
    <ConfirmPlan
      planKey={confirm.batchId}
      title="Restore from To Delete?"
      intro={
        <p>
          {confirm.ids.length === 1 ? "It moves" : `These ${confirm.ids.length} move`} out of To Delete{" "}
          {confirm.to === "inbox" ? "into the inbox" : "back to where they were marked"}. A folder that is gone is made
          again and a name that is taken gets a number; both are shown below. Nothing is deleted: Undo puts{" "}
          {confirm.ids.length === 1 ? "it" : "them"} back in To Delete.
        </p>
      }
      ops={confirm.ops}
      busy={busy}
      confirmLabel={RESTORE_LABEL[confirm.to]}
      onConfirm={() => void guarded(() => apply(confirm))}
      onCancel={() => setConfirm(null)}
    />
  );

  return {
    busy,
    running: () => inFlight.current || confirm !== null,
    start: (ids: string[], to: RestoreTo) => {
      if (ids.length === 0 || confirm !== null) return;
      void guarded(() => preview(ids, to));
    },
    view,
  };
}

const baseName = (path: string) => path.slice(path.lastIndexOf("/") + 1);

/** "a.pdf" for one, "3 files" for several (the toast and Activity say the same). */
function restoredWhat(moved: ResolvedOp[]): string {
  return moved.length === 1 ? visible(baseName(moved[0].dst)) : plural(moved.length, "file");
}
