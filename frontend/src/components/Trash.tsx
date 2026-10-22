/** Trash (stars spec §8): "Move to To Delete" wherever a file is shown, as a bin
 * button and ⌘⌫ (Finder's Move to Trash; a plain ⌫ never trashes). It is Browse's Mark
 * for deletion flow (``useMarkForDeletion``): a dry run, the confirm with its exact
 * ops, the move into ``##. To Delete`` (mirrored path) and a toast with Undo. The app
 * never deletes; the user empties the folder in Finder. Several selected files go in
 * one batch; the server refuses the whole batch for a file marked Important or a
 * protected path, and its reason is shown. */
import { Trash2 } from "lucide-react";
import { type ReactNode, useMemo, useRef } from "react";
import type { BatchResult } from "../api/client";
import { dialogOpen, isTyping } from "../keyboard";
import { type DeletionMessage, useMarkForDeletion } from "../screens/useMarkForDeletion";
import { inFileManager } from "../fileManager";
import { visible } from "../text";
import { ConfirmPlan } from "./PlanPreview";
import { undoAction, useBlockToastActions, useToast } from "./Toasts";
import { IconButton } from "./ui/IconButton";
import { useUndoConfirm } from "./UndoConfirm";

export const TRASH_LABEL = "Move to To Delete";
export const TRASH_KEY = "⌘⌫";
/** A second ⌘⌫ (or click) while a Trash call is in flight: said, never silent. */
export const TRASH_BUSY = "Already moving…";

const baseName = (path: string) => path.slice(path.lastIndexOf("/") + 1);

/** The Trash key: ⌘⌫ (or ⌘⌦), never held down, never while typing. Outside a dialog
 * only when none is open; with ``within`` (a dialog's own element, e.g. Quick Look)
 * only when the key press happened in that dialog and it is the topmost one. */
export function isTrashKey(e: KeyboardEvent, within?: Element | null): boolean {
  if (e.key !== "Backspace" && e.key !== "Delete") return false;
  if (!e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || e.repeat || isTyping(e.target)) return false;
  if (within === undefined) return !dialogOpen();
  const open = [...document.querySelectorAll("dialog[open]")];
  const target = e.target instanceof Element ? e.target.closest("dialog[open]") : null;
  return within !== null && open.at(-1) === within && target === within;
}

/** The bin button. ``count`` (a selection of several) names how many files it takes. */
export function TrashButton({
  count,
  shortcut = TRASH_KEY,
  disabled,
  disabledReason,
  tipSide,
  onClick,
}: {
  count?: number;
  shortcut?: string | null;
  disabled?: boolean;
  disabledReason?: string | null;
  tipSide?: "below" | "above";
  onClick: () => void;
}) {
  return (
    <IconButton
      icon={<Trash2 />}
      label={count !== undefined && count > 1 ? `Move ${count} to To Delete` : TRASH_LABEL}
      shortcut={shortcut ?? undefined}
      className="trash-button"
      tipSide={tipSide}
      disabled={disabled || !!disabledReason}
      disabledReason={disabledReason ?? undefined}
      onClick={onClick}
    />
  );
}

/** A message as the user reads it: a refusal says what was not done. */
export const messageText = (m: DeletionMessage) => (m.refusal ? `Not moved to To Delete: ${m.text}` : m.text);

type Options = {
  /** After an apply (complete or not): the drive ids that moved. */
  onTrashed?: (ids: string[], result: BatchResult, complete: boolean) => void;
  /** After a complete Undo of a trash batch. */
  onUndone?: () => void;
  /** The screen shows ``message`` itself (Browse); otherwise it is a toast. */
  inlineMessage?: boolean;
};

/** One start of the flow. ``current``: what the screen targets now (a preview or
 * apply for other ids is dropped). ``links``: a target is a symbolic link (the confirm
 * says the link moves, not its target). From inside a dialog (Quick Look, Edit
 * details): ``onConfirming`` runs in the update that opens the confirm (close the
 * dialog there), ``onRefused`` gets a refusal or notice before that, to show in the
 * dialog (``TRASH_BUSY`` too, when a Trash call is already running), and
 * ``onCancelled`` runs when the confirm is cancelled (bring the dialog back); later
 * messages are toasts. */
export type TrashStart = {
  current?: () => string[] | null;
  links?: boolean;
  onConfirming?: () => void;
  onRefused?: (text: string) => void;
  onCancelled?: () => void;
};

export type Trash = ReturnType<typeof useTrash>;

/** One screen's Trash flow: ``start(ids, options)`` dry-runs ``ids`` and opens the
 * confirm. Render ``view``. */
export function useTrash({ onTrashed, onUndone, inlineMessage = false }: Options = {}) {
  const toast = useToast();
  const undo = useUndoConfirm(onUndone);
  const started = useRef<string[] | null>(null);
  const run = useRef<TrashStart>({});
  const links = useRef(false);
  // What the flow compares a preview's ids against, read when the answer arrives.
  const selection = useMemo(
    () => ({
      get current() {
        return run.current.current ? run.current.current() : started.current;
      },
    }),
    [],
  );
  const marking = useMarkForDeletion(
    selection,
    (result, complete) => {
      const ids = result.done.map((op) => op.drive_id).filter((id): id is string => !!id);
      const files = result.done.filter((op) => op.kind === "quarantine");
      if (files.length > 0) {
        const names = files.map((op) => baseName(op.dst)).join(", ");
        const target = { batchId: result.batch_id };
        toast({
          kind: complete ? "info" : "warning",
          text: `${complete ? "" : "Partly applied: "}Moved to To Delete: ${names}`,
          action: undoAction(() => {
            // Belt and braces: the button is disabled in these states anyway.
            if (marking.inFlight.current || undo.undoing.current || dialogOpen()) return;
            undo.open(target);
          }),
        });
      }
      onTrashed?.(ids, result, complete);
    },
    {
      confirming: () => {
        const { onConfirming, onCancelled } = run.current;
        // from here on the dialog is gone: later messages are toasts
        run.current = { current: run.current.current, onCancelled };
        onConfirming?.();
      },
      message: (m) => {
        const { onRefused } = run.current;
        if (onRefused) onRefused(messageText(m));
        else if (!inlineMessage) toast({ kind: m.kind === "error" ? "error" : "info", text: messageText(m) });
      },
    },
  );
  useBlockToastActions(marking.busy || marking.confirm !== null);

  const confirm = marking.confirm;
  const one = confirm?.ids.length === 1;
  const view: ReactNode = confirm && (
    <ConfirmPlan
      planKey={confirm.batchId}
      title={`${TRASH_LABEL}?`}
      intro={
        <>
          <p>
            {one ? "It moves" : `These ${confirm.ids.length} move`} into{" "}
            <code>{visible(confirm.ops.find((op) => op.kind === "quarantine")?.dst.split("/")[0] ?? "")}</code>,
            keeping {one ? "its" : "their"} path. Nothing is deleted: Undo puts {one ? "it" : "them"} back, and you
            empty the folder {inFileManager()}.
          </p>
          {links.current && <p className="notice">A link moves the link; its target stays.</p>}
        </>
      }
      ops={confirm.ops}
      busy={marking.busy}
      confirmLabel={TRASH_LABEL}
      onConfirm={marking.confirmApply}
      onCancel={() => {
        marking.cancel();
        run.current.onCancelled?.();
      }}
    />
  );

  return {
    busy: marking.busy,
    inFlight: marking.inFlight,
    confirm,
    /** For ``inlineMessage``: the message to show. */
    message: inlineMessage ? marking.message : null,
    /** A call is running or its confirm is open (at event time: the ref). */
    running: () => marking.inFlight.current || marking.confirm !== null,
    start: (ids: string[], options: TrashStart = {}) => {
      if (ids.length === 0 || marking.confirm !== null) return;
      if (marking.inFlight.current) {
        options.onRefused?.(TRASH_BUSY); // a dialog's second ⌘⌫: said on its status line
        return;
      }
      started.current = ids;
      run.current = options;
      links.current = !!options.links;
      marking.start(ids);
    },
    view,
  };
}
