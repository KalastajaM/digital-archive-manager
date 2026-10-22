/** Preview → (confirm) → apply. Owned by the Inbox, so a result always has somewhere to
 * go: switching entries is blocked while a call is in flight, and the error, plan and
 * confirm outlive the review card that started them. */
import { type RefObject, useRef, useState } from "react";
import {
  errorText,
  type FileItResult,
  type FileRequest,
  type ResolvedOp,
  type TrayDef,
  useFileIt,
  usePreview,
} from "../api/client";
import { useToast } from "../components/Toasts";
import { prefillValues, type TrayValues } from "../components/TrayPicker";
import { fieldWord, formatField } from "../format";

/** Called after an apply; ``complete`` is false when the batch stopped part way. */
export type OnApplied = (result: FileItResult, complete: boolean, requests: FileRequest[]) => void;

/** Spec §10: only one plain RENAME or MOVE (no new folders, no notes) skips the confirm. */
export function appliesDirectly(ops: ResolvedOp[], fileCount: number): boolean {
  if (fileCount !== 1 || ops.length !== 1) return false;
  const [op] = ops;
  return (op.kind === "rename" || op.kind === "move") && !op.note;
}

/** Requests compare equal when they would send the same JSON. */
export const sameRequests = (a: FileRequest[] | null, b: FileRequest[] | null) =>
  a !== null && b !== null && JSON.stringify(a) === JSON.stringify(b);

/** A plan together with the exact requests it was computed for, and the speaker's scan
 * prefill as it was then (the confirm's follow-up lines come from it, never from the
 * live entries, which can refetch while the sheet is open). */
export type Snapshot = { requests: FileRequest[]; ops: ResolvedOp[]; prefill?: Record<string, string> };

const RELOCATES = new Set<ResolvedOp["kind"]>(["rename", "move", "quarantine"]);
const destinations = (ops: ResolvedOp[]) => ops.filter((op) => RELOCATES.has(op.kind)).map((op) => op.dst);

/** Where applied ops put files that the previewed plan did not show (e.g. a new ``_2``
 * collision suffix because the disk changed in between). */
export function unexpectedDestinations(applied: ResolvedOp[], previewed: ResolvedOp[]): string[] {
  const expected = new Set(destinations(previewed));
  return destinations(applied).filter((dst) => !expected.has(dst));
}

/** What happens after the move: the tray item, collections and note. */
export type FollowUps = {
  tray: string | null;
  /** Every value the form shows for the tray's fields ("" = cleared); ``{}`` lets the
   * server prefill each file's item from its own scan (batch). */
  trayFields: TrayValues;
  collections: string[];
  note: string;
};

/** ``base`` plus its follow-ups; one left out means none (the server's default), so a
 * plain filing sends exactly what Phase 1 sent. */
export function withFollowUps(base: FileRequest, follow: FollowUps): FileRequest {
  const request: FileRequest = { ...base };
  if (follow.tray !== null) {
    request.tray = follow.tray;
    request.tray_fields = follow.trayFields;
  }
  if (follow.collections.length > 0) request.collections = follow.collections;
  const note = follow.note.trim(); // the server trims too: send what it will store
  if (note) request.note = note;
  return request;
}

const NOTE_SHOWN = 120;

/** The request whose follow-ups describe a filing: a batch leaves the tray out for files
 * already in it, so the first one that has a tray speaks for all (else the first). */
export const speaker = (requests: FileRequest[]): FileRequest | undefined =>
  requests.find((r) => r.tray) ?? requests[0];

/** The follow-ups of ``requests`` as plan lines ("Put in To pay: due date 15.10.2026").
 * Both cards give every request of one filing the same tray (except files already in
 * it), collections and note, so one request speaks for all of them. ``prefill`` is that file's scan values:
 * a blank field is shown as "none (will be flagged)" if required, "cleared" if the
 * scan had a value for it, and left out otherwise. */
export function followUpLines(
  requests: FileRequest[],
  trays: TrayDef[],
  prefill: Record<string, string> = {},
): string[] {
  const first = speaker(requests);
  if (!first) return [];
  const lines: string[] = [];
  if (first.tray) {
    const tray = trays.find((t) => t.id === first.tray);
    const scanned = tray ? prefillValues(tray, prefill) : {};
    const values: string[] = [];
    for (const [name, v] of Object.entries(first.tray_fields ?? {})) {
      const def = tray?.fields?.[name];
      if (typeof v === "string" && !v.trim()) {
        if (def?.required) values.push(`${fieldWord(name)}: none (will be flagged)`);
        else if (name in scanned) values.push(`${fieldWord(name)}: cleared`);
      } else {
        values.push(`${fieldWord(name)} ${formatField(def?.type, v)}`);
      }
    }
    const withTray = requests.filter((r) => r.tray).length;
    const skipped = requests.length - withTray;
    // A batch with files already in the tray says how many get a new item.
    const name = `${tray?.name ?? first.tray}${skipped > 0 ? ` (${withTray} of ${requests.length}; ${skipped} already in it)` : ""}`;
    lines.push(values.length > 0 ? `Put in ${name}: ${values.join(", ")}` : `Put in ${name}`);
  }
  if (first.collections?.length) lines.push(`Add to collection: ${first.collections.join(", ")}`);
  const note = first.note?.trim();
  if (note) lines.push(`Note: ${note.length > NOTE_SHOWN ? `${note.slice(0, NOTE_SHOWN)}…` : note}`);
  return lines;
}

const MAX_NAMES = 5;

/** "a.pdf, b.pdf +N more": the files of these requests by their new names. */
const requestNames = (requests: FileRequest[]) => {
  const shown = requests.slice(0, MAX_NAMES).map((r) => r.name).join(", ");
  return requests.length > MAX_NAMES ? `${shown} +${requests.length - MAX_NAMES} more` : shown;
};

export type Filing = ReturnType<typeof useFiling>;

/** An error (or notice) for the files it concerns: shown only on their card. */
export type Message = { ids: string[]; text: string; kind: "error" | "notice" };

/** Preview and File while a preview or a filing is in flight. */
export const FILING_BUSY = "Still working on the last preview or filing";

export const FORM_CHANGED = "Form changed — press File it again";

const idsOf = (requests: FileRequest[]) => requests.map((r) => r.drive_id);

/** ``prefillOf`` gives a file's scan prefill (the inbox entry's), read at preview time. */
export function useFiling(
  onApplied: OnApplied,
  prefillOf: (driveId: string) => Record<string, string> | undefined = () => undefined,
) {
  const previewCall = usePreview();
  const fileCall = useFileIt();
  const toast = useToast();
  const [plan, setPlan] = useState<Snapshot | null>(null);
  const [confirm, setConfirm] = useState<Snapshot | null>(null);
  const [message, setMessage] = useState<Message | null>(null);
  const setError = (text: string | null, ids: string[]) =>
    setMessage(text === null ? null : { ids, text, kind: "error" });
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false); // synchronous guard: a second key press sees it at once
  /** The current form's requests (null if incomplete); the card keeps it up to date. */
  const form: RefObject<FileRequest[] | null> = useRef<FileRequest[] | null>(null);

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

  /** Preview ``requests``; the result is dropped (null) if the form changed meanwhile.
   * For File it that is said on the card, so the user knows nothing was filed. */
  async function fetchPlan(requests: FileRequest[], forFileIt: boolean): Promise<Snapshot | null> {
    setMessage(null);
    const ids = idsOf(requests);
    let ops: ResolvedOp[];
    try {
      ops = await previewCall.mutateAsync(requests);
    } catch (e) {
      if (sameRequests(form.current, requests)) setError(errorText(e), ids);
      return null;
    }
    if (!sameRequests(form.current, requests)) {
      if (forFileIt) setMessage({ ids, text: FORM_CHANGED, kind: "notice" });
      return null;
    }
    const first = speaker(requests);
    const snapshot: Snapshot = { requests, ops, prefill: first ? prefillOf(first.drive_id) : undefined };
    setPlan(snapshot);
    return snapshot;
  }

  async function apply(snapshot: Snapshot) {
    setConfirm(null);
    setMessage(null);
    const ids = idsOf(snapshot.requests);
    let result: FileItResult;
    try {
      result = await fileCall.mutateAsync(snapshot.requests);
    } catch (e) {
      setError(errorText(e), ids);
      return;
    }
    const complete = !result.error && !result.failed;
    if (!complete) {
      const op = result.failed ? ` (${result.failed.kind} ${result.failed.src ?? ""})` : "";
      setError(
        `Stopped after ${result.done.length} change(s)${op}: ${result.error ?? "failed"}`,
        ids,
      );
    }
    const moved = unexpectedDestinations(result.done, snapshot.ops);
    if (moved.length > 0) {
      toast({
        kind: "warning",
        text: `Filed somewhere other than previewed: ${moved.join(", ")}`,
      });
    }
    if (result.index_error) {
      toast({
        kind: "warning",
        text: `Index update failed: ${result.index_error}. The next scan repairs it.`,
      });
    }
    if (result.tag_error) {
      toast({
        kind: "warning",
        text: `Tagging failed: ${result.tag_error}. Not tagged: ${result.untagged.join(", ")}. The files were filed; add the tags again.`,
      });
    }
    if (result.follow_up_error) {
      toast({
        kind: "warning",
        text:
          snapshot.requests.length > 1
            ? `Filed, but adding to tray/collection failed for one or more of: ${requestNames(snapshot.requests)}: ${result.follow_up_error}`
            : `${requestNames(snapshot.requests)}: Filed, but adding to tray/collection failed: ${result.follow_up_error}`,
      });
    }
    setPlan(null);
    onApplied(result, complete, snapshot.requests);
  }

  return {
    busy,
    inFlight,
    form,
    message,
    /** The message for a card showing these files, if it concerns any of them. */
    messageFor: (ids: string[]) =>
      message && message.ids.some((id) => ids.includes(id)) ? message : null,
    dismissMessage: () => setMessage(null),
    confirm,
    /** The inline plan, only while it still matches the form exactly. */
    planFor: (requests: FileRequest[] | null) =>
      plan && sameRequests(plan.requests, requests) ? plan : null,
    setError,
    clearPlan: () => setPlan(null),

    cancel: () => setConfirm(null),
    preview: (requests: FileRequest[]) =>
      void guarded(async () => {
        await fetchPlan(requests, false);
      }),
    /** File it: use the shown plan if it matches the form, else preview again; apply
     * directly only when ``appliesDirectly``, otherwise ask first. */
    fileIt: (requests: FileRequest[], batch = false) =>
      void guarded(async () => {
        const current = plan && sameRequests(plan.requests, requests) ? plan : null;
        const snapshot = current ?? (await fetchPlan(requests, true));
        if (snapshot === null) return;
        if (!batch && appliesDirectly(snapshot.ops, snapshot.requests.length)) await apply(snapshot);
        else setConfirm(snapshot);
      }),
    /** Apply the confirmed snapshot (exactly what the dialog showed). */
    confirmApply: () => {
      const snapshot = confirm;
      if (snapshot) void guarded(() => apply(snapshot));
    },
  };
}
