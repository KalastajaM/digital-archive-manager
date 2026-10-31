/** Renewed… on a Renew item: the new expiry date (required) and, optionally, the new file,
 * picked with the file picker. Without a file only the date changes and it applies at
 * once. With one, the old file's move into Expired is previewed first; a locked old file
 * needs the deliberate "Unlock and move", which unlocks it and previews the move again
 * under that grant, so the move is shown before Renewed applies it. A lock this form
 * took is given back whichever way the form ends (applied, failed, cancelled, closed) and
 * when the preview is redone. The toast's Undo is Activity's when the old file moved,
 * else the renewal's own. */
import { useEffect, useId, useRef, useState } from "react";
import {
  errorText,
  isUnlockedNow,
  type ItemFile,
  useFileLock,
  useRenew,
  useRenewalUndo,
  useRenewPreview,
} from "../api/client";
import type { components } from "../api/schema";
import { dialogOpen, isTyping, useKeydown } from "../keyboard";
import { visible } from "../text";
import { AddFile } from "./AddFile";
import { PlanPreview } from "./PlanPreview";
import { undoAction, useToast } from "./Toasts";
import { useUndoConfirm } from "./UndoConfirm";

type Preview = components["schemas"]["RenewPreviewOut"];
type Picked = { drive_id: string; name: string };

export function RenewForm({
  item,
  files,
  label,
  onClose,
}: {
  item: { id: number; title: string };
  /** The item's files; the first is the one a new file replaces. */
  files: ItemFile[];
  /** The tray's renew label ("Renewed"). */
  label: string;
  onClose: () => void;
}) {
  const ids = useId();
  const toast = useToast();
  const renew = useRenew();
  const preview = useRenewPreview();
  const renewalUndo = useRenewalUndo();
  const undo = useUndoConfirm();
  const old = files[0];
  const lock = useFileLock(old?.drive_id ?? "", old?.marks ?? [], old?.path);
  const [expires, setExpires] = useState("");
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [plan, setPlan] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sending = useRef(false); // synchronous: a second Enter never posts twice
  // the old file was unlocked by this form (Unlock and move): only that lock is given back
  const took = useRef(false);
  const relock = useRef(lock.relock);
  relock.current = lock.relock;
  const formRef = useRef<HTMLFormElement>(null);
  const dateRef = useRef<HTMLInputElement>(null);
  const { id, title } = item;

  useEffect(() => dateRef.current?.focus(), []);
  const release = () => {
    if (!took.current) return;
    took.current = false;
    relock.current();
  };
  // a form that goes away without applying locks the file again too
  useEffect(() => () => release(), []);
  const close = () => {
    release();
    onClose();
  };
  // a changed date or file needs a new preview, and a new Unlock and move
  const resetPlan = () => {
    setPlan(null);
    release();
  };
  // Esc cancels even after the focus has left the form, as in the done form.
  useKeydown((e) => {
    if (e.key !== "Escape" || e.metaKey || e.ctrlKey || e.altKey || dialogOpen()) return;
    const target = e.target instanceof Node ? e.target : null;
    if (target && formRef.current?.contains(target)) return;
    if (isTyping(e.target)) return;
    close();
  });

  const body = () => (picked ? { expires, drive_id: picked.drive_id } : { expires });
  const locked = plan?.locked ?? [];
  // a new file is applied only after its preview; a renewal without one moves nothing
  const needsPreview = picked !== null && plan === null;

  const announce = (result: Awaited<ReturnType<typeof renew.mutateAsync>>) => {
    const runUndo = () => {
      if (result.undo === "activity") {
        if (!undo.undoing.current && !dialogOpen()) undo.open({ batchId: result.batch_id });
        return;
      }
      renewalUndo
        .mutateAsync(result.batch_id)
        .then(() => toast({ kind: "info", text: "Undone." }))
        .catch((e: unknown) => toast({ kind: "error", text: `Could not undo the renewal of ${visible(title)}: ${visible(errorText(e))}` }));
    };
    const skipped = result.skipped ? ` ${result.skipped}, so it was not moved.` : "";
    toast({ kind: skipped ? "warning" : "info", text: `Renewed: ${title}${skipped}`, action: undoAction(runUndo) });
  };

  const apply = async () => {
    try {
      const result = await renew.mutateAsync({ id, body: body() });
      close();
      announce(result);
    } catch (err) {
      // the grant is given back, so the move is previewed again before it can apply
      if (took.current) resetPlan();
      throw err;
    }
  };

  // Unlock and move: unlock the old file, then preview the move under that grant
  const unlockAndPreview = async () => {
    const notUnlocked = new Error(`${locked[0]?.name ?? "The old file"} could not be unlocked.`);
    // one the owner unlocked before stays so: only a lock this form takes is given back
    if (old !== undefined && !isUnlockedNow(old.drive_id)) {
      await lock.unlock("now");
      took.current = isUnlockedNow(old.drive_id);
      if (!took.current) throw notUnlocked;
    }
    try {
      const next = await preview.mutateAsync({ id, body: body() });
      if (next.locked.length > 0) throw notUnlocked;
      setPlan(next);
    } catch (err) {
      release();
      throw err;
    }
  };

  const submit = async (e: { preventDefault: () => void }, unlock = false) => {
    e.preventDefault();
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      if (unlock) await unlockAndPreview();
      else if (needsPreview) setPlan(await preview.mutateAsync({ id, body: body() }));
      else await apply();
    } catch (err) {
      setError(errorText(err));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };

  const dateId = `${ids}-expires`;
  return (
    <form
      ref={formRef}
      className="done-form renew-form"
      aria-label={visible(label)}
      onSubmit={(e) => void submit(e)}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          close();
        }
      }}
    >
      <div className="field">
        <label htmlFor={dateId}>New expiry date</label>
        <input
          ref={dateRef}
          id={dateId}
          type="date"
          required
          value={expires}
          onChange={(e) => {
            setExpires(e.target.value);
            resetPlan();
          }}
        />
      </div>
      {picked ? (
        <p className="renew-file">
          <span className="renew-file-name" title={visible(picked.name)}>
            {visible(picked.name)}
          </span>{" "}
          <button
            type="button"
            className="link-button"
            onClick={() => {
              setPicked(null);
              resetPlan();
            }}
          >
            Don’t attach
          </button>
        </p>
      ) : (
        <button type="button" className="link-button" aria-expanded={picking} onClick={() => setPicking((p) => !p)}>
          Attach the new file (optional)
        </button>
      )}
      {picking && (
        <AddFile
          taken={files.map((f) => f.drive_id)}
          takenMode="mark"
          takenLabel="already on this item"
          choose={async (hit) => {
            setPicked(hit);
            resetPlan();
          }}
          onDone={() => setPicking(false)}
        />
      )}
      {plan && plan.ops.length > 0 && <PlanPreview ops={plan.ops} />}
      {plan?.skipped && <p className="hint">{visible(plan.skipped)}, so it is not moved.</p>}
      {locked.map((f) => (
        <p key={f.drive_id} className="notice">
          {visible(f.name)} is locked.
        </p>
      ))}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
      <div className="actions">
        <button type="button" onClick={close}>
          Cancel
        </button>
        {locked.length > 0 ? (
          <button type="button" className="primary" disabled={busy} onClick={(e) => void submit(e, true)}>
            Unlock and move
          </button>
        ) : (
          <button type="submit" className="primary" disabled={busy}>
            {needsPreview ? "Preview…" : visible(label)}
          </button>
        )}
      </div>
    </form>
  );
}
