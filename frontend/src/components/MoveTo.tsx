/** Moving files between archive folders (Browse): a drop on a folder and "Move to…"
 * both run the same flow, always preview → confirm → apply → Undo. A drop never moves a
 * file by itself. "Edit details…" renames (and maybe moves) one file through it too.
 *
 * The apply sends exactly the previewed ids and folder, and its destinations are
 * compared with the previewed ones (the snapshot rule): a file that landed elsewhere
 * (the disk changed in between) is named in a warning. */
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import {
  errorText,
  type MoveResult,
  type ResolvedOp,
  useMoveFiles,
  useMovePreview,
  useRenameFile,
  useRenamePreview,
  useStatus,
} from "../api/client";
import { plural } from "../format";
import { dialogOpen } from "../keyboard";
import { unexpectedDestinations } from "../screens/useFiling";
import { TO_DELETE_REASON } from "../toDelete";
import { visible } from "../text";
import { FolderPicker } from "./FolderPicker";
import { ConfirmPlan, snapshotKey } from "./PlanPreview";
import { useToast } from "./Toasts";
import { Sheet } from "./ui/Sheet";
import { useUndoConfirm } from "./UndoConfirm";

/** The folder as the UI names it: the archive's top level is "Archive". */
export const folderLabel = (folder: string) => (folder ? visible(folder) : "Archive");

const baseName = (path: string) => path.slice(path.lastIndexOf("/") + 1);

/** Why files may not be dropped into ``folder`` (null: they may). The server checks the
 * same rules; this only says so before the drop. */
/** Why files in ``path``'s area may not be moved at all (null: they may). */
export function sourceRefusal(path: string): string | null {
  const top = path.split("/")[0].normalize("NFC").toLowerCase();
  if (top === "##. to delete") return TO_DELETE_REASON;
  if (top === "##. ongoing") return "Files in ##. Ongoing cannot be moved: the app keeps them";
  return null;
}

/** The server's refusal of a file marked ! Important (``IMPORTANT_REFUSAL`` in
 * ``services/browse.py``): said up front wherever the record's ``marks`` are known. */
export const IMPORTANT_REFUSAL = "This file is marked Important; unmark it first";

/** Why Mark for deletion refuses a file or folder at ``path`` (the server refuses these
 * too; ``##. Important`` is the default protected path). With ``marks`` (the record's),
 * a file marked Important is refused up front with the server's own reason. */
export function deletionRefusal(path: string, marks?: readonly string[] | null): string | null {
  if (marks?.includes("important")) return IMPORTANT_REFUSAL;
  const top = path.split("/")[0].normalize("NFC").toLowerCase();
  if (top === "##. important") return "Files in ##. Important are protected";
  if (top === "##. to delete") return "Already in ##. To Delete";
  return null;
}

/** Shown on a drop target while a move is being previewed or applied. */
export const MOVE_BUSY = "Another move is still running";

export function moveRefusal(folder: string): string | null {
  const top = folder.split("/")[0].normalize("NFC").toLowerCase();
  if (!folder) return "Not allowed: the top of the archive holds folders only";
  if (top === "##. to delete") return "Not allowed: use Move to To Delete";
  if (top === "##. ongoing") return "Not allowed: ##. Ongoing is kept by the app";
  return null;
}

export const ALREADY_IN_INBOX = "Already in the inbox";
export const INBOX_UNKNOWN = "The inbox folder is not known yet";

const topOf = (path: string) => path.split("/")[0].normalize("NFC").toLowerCase();

/** The configured inbox folder (``##. Organize``), once the status has loaded. */
export function useInboxFolder(): string | null {
  return useStatus().data?.special_folders?.inbox ?? null;
}

/** Why these files cannot go back to the inbox (null: they can). ``paths`` null: not
 * known here (the server's preview decides). */
export function inboxRefusal(paths: string[] | null, inbox: string | null): string | null {
  if (!inbox) return INBOX_UNKNOWN;
  if (!paths) return null;
  const from = paths.map(sourceRefusal).find((r) => r !== null);
  if (from) return from;
  if (paths.length > 0 && paths.every((p) => topOf(p) === topOf(inbox))) return ALREADY_IN_INBOX;
  return null;
}

/** A move back into the inbox folder (through the same preview → confirm → Undo).
 * With the files' ``paths`` (as the drag knows them, in ``ids``' order), those already
 * anywhere under the inbox are left out of the request and counted as ``skipped``. */
export function backToInbox(ids: string[], inbox: string, paths?: string[] | null): MoveRequest {
  const known = paths && paths.length === ids.length ? paths : null;
  const keep = known ? ids.filter((_, i) => topOf(known[i]) !== topOf(inbox)) : ids;
  return { ids: keep, folder: inbox, nothing: ALREADY_IN_INBOX, skipped: ids.length - keep.length };
}

/** Previews and applies in flight across every move flow in this window (Browse, the
 * sidebar Inbox): one at a time, whichever started it. */
let movesRunning = 0;
export const anyMoveRunning = () => movesRunning > 0;

export type MoveRequest = {
  ids: string[];
  folder: string;
  /** One file's new name ("Edit details…"; ``ids`` holds just that file): a rename in
   * its own folder, else a move that gives it this name. */
  name?: string;
  /** Said when the preview plans nothing (default: "Nothing to move: already in …"). */
  nothing?: string;
  /** Files of the drag left out before the request (already in the inbox). */
  skipped?: number;
};
type Pending = MoveRequest & { ops: ResolvedOp[] };

/** A window event every move flow sends after an apply that changed something (and,
 * with no ids, after its Undo): a screen showing files it did not move itself (Browse,
 * after a drop on the sidebar Inbox) forgets them and reloads. */
export const FILES_MOVED_EVENT = "dam:files-moved";
export type FilesMovedDetail = { ids: string[] };

function announceMoved(ids: string[]) {
  window.dispatchEvent(new CustomEvent<FilesMovedDetail>(FILES_MOVED_EVENT, { detail: { ids } }));
}

/** The files a move took: those its ops name; with a complete apply every requested
 * file (ops of files without a Drive id carry none). */
export function movedIds(result: MoveResult, request: MoveRequest): string[] {
  const moved = result.done.map((op) => op.drive_id).filter((id): id is string => !!id);
  const all = !result.error && !result.failed ? request.ids : [];
  return [...new Set([...moved, ...all])];
}

/** ``onMoved`` runs after an apply that changed something, ``onUndone`` after its
 * batch was undone (from the toast). Both are also announced as ``FILES_MOVED_EVENT``. */
export function useMoveFlow(
  onMoved?: (result: MoveResult, request: MoveRequest) => void,
  onUndone?: (batchId: string) => void,
  /** A refused preview (or one with nothing to do), said here instead of in a toast:
   * "Edit details…" shows it in its own sheet, which stays open. */
  onRefused?: (text: string) => void,
) {
  const preview = useMovePreview();
  const apply = useMoveFiles();
  const renamePreview = useRenamePreview();
  const rename = useRenameFile();
  const toast = useToast();
  const undo = useUndoConfirm((batchId) => {
    onUndone?.(batchId);
    announceMoved([]);
  });
  const [confirm, setConfirm] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false); // synchronous: a second click or drop sees it at once

  async function guarded(work: () => Promise<void>) {
    if (inFlight.current || anyMoveRunning()) return;
    inFlight.current = true;
    movesRunning += 1;
    setBusy(true);
    try {
      await work();
    } finally {
      inFlight.current = false;
      movesRunning -= 1;
      setBusy(false);
    }
  }

  // Exactly the request: the preview and the apply send the same body.
  const previewCall = (r: MoveRequest) =>
    r.name === undefined
      ? preview.mutateAsync({ drive_ids: r.ids, folder: r.folder })
      : renamePreview.mutateAsync({ drive_id: r.ids[0], name: r.name, folder: r.folder });
  const applyCall = (r: MoveRequest) =>
    r.name === undefined
      ? apply.mutateAsync({ drive_ids: r.ids, folder: r.folder })
      : rename.mutateAsync({ drive_id: r.ids[0], name: r.name, folder: r.folder });

  async function previewMove(request: MoveRequest) {
    let ops: ResolvedOp[];
    try {
      ops = await previewCall(request);
    } catch (e) {
      const text = `Cannot ${request.name === undefined ? "move" : "change"}: ${visible(errorText(e))}`;
      if (onRefused) onRefused(text);
      else toast({ kind: "error", text });
      return;
    }
    if (ops.length === 0) {
      const nothing = request.name === undefined ? `Nothing to move: already in ${folderLabel(request.folder)}` : "Nothing to change";
      if (onRefused) onRefused(request.nothing ?? nothing);
      else toast({ kind: "info", text: request.nothing ?? nothing });
      return;
    }
    setConfirm({ ...request, ops });
  }

  async function applyMove(pending: Pending) {
    setConfirm(null);
    let result: MoveResult;
    try {
      result = await applyCall(pending);
    } catch (e) {
      toast({ kind: "error", text: `Could not ${pending.name === undefined ? "move" : "change"}: ${visible(errorText(e))}` });
      return;
    }
    const complete = !result.error && !result.failed;
    if (!complete) {
      const at = result.failed ? ` (at ${visible(result.failed.src ?? result.failed.dst)})` : "";
      toast({
        kind: "error",
        text: `Stopped after ${plural(result.done.length, "change")}: ${visible(result.error ?? "an operation failed")}${at}`,
      });
    }
    const elsewhere = unexpectedDestinations(result.done, pending.ops);
    if (elsewhere.length > 0) {
      toast({ kind: "warning", text: `Moved somewhere other than previewed: ${elsewhere.map(visible).join(", ")}` });
    }
    if (result.index_error) {
      toast({ kind: "warning", text: `Index update failed: ${visible(result.index_error)}. The next scan repairs it.` });
    }
    const moved = result.done.filter((op) => op.kind === "move");
    const renamed = result.done.find((op) => op.kind === "rename");
    if (result.done.length > 0) {
      const what = moved.length === 1 ? visible(baseName(moved[0].dst)) : plural(moved.length, "file");
      const target = { batchId: result.batch_id };
      const said =
        moved.length === 0 && renamed ? `Renamed to ${visible(baseName(renamed.dst))}` : `Moved ${what} to ${folderLabel(pending.folder)}`;
      toast({
        kind: complete ? "info" : "warning",
        text: `${complete ? "" : "Partly applied: "}${said}`,
        action: {
          label: "Undo",
          run: () => {
            // Belt and braces: the button is disabled in these states anyway.
            if (inFlight.current || undo.undoing.current || dialogOpen()) return;
            undo.open(target);
          },
        },
      });
      onMoved?.(result, pending);
      announceMoved(movedIds(result, pending));
    }
  }

  const renaming = confirm?.name !== undefined;
  const renameOnly = renaming && !confirm?.ops.some((op) => op.kind === "move");
  const view: ReactNode = confirm ? (
    <ConfirmPlan
      planKey={snapshotKey({ ids: confirm.ids, folder: confirm.folder, name: confirm.name, ops: confirm.ops })}
      title={
        !renaming
          ? `Move ${plural(confirm.ids.length, "file")} to ${folderLabel(confirm.folder)}?`
          : renameOnly
            ? `Rename to ${visible(confirm.name ?? "")}?`
            : `Move to ${folderLabel(confirm.folder)} as ${visible(confirm.name ?? "")}?`
      }
      confirmLabel={renameOnly ? "Rename" : "Move"}
      intro={
        <>
          {renaming ? (
            <p>
              A name already taken there gets a suffix such as <code>_2</code>. Undo puts the file back as it was.
            </p>
          ) : (
            <p>
              Names are kept; a name already taken there gets a suffix such as <code>_2</code>. Undo puts the files
              back.
            </p>
          )}
          {(confirm.skipped ?? 0) > 0 && <p className="hint">{confirm.skipped} already in the inbox (skipped)</p>}
        </>
      }
      ops={confirm.ops}
      busy={busy}
      onConfirm={() => {
        const pending = confirm;
        void guarded(() => applyMove(pending));
      }}
      onCancel={() => setConfirm(null)}
    />
  ) : null;

  return {
    busy,
    inFlight,
    /** A confirm is showing. */
    confirming: confirm !== null,
    /** Preview moving these files into ``folder`` and show the confirm. */
    start: (request: MoveRequest) => void guarded(() => previewMove(request)),
    /** The confirm sheet while one is pending: render it anywhere. */
    view,
  };
}

type SheetProps = {
  /** The names of the files to move (shown, up to a few). */
  names: string[];
  /** The folder the picker starts with (e.g. the other pane's). */
  initial: string;
  onCancel: () => void;
  onChoose: (folder: string) => void;
};

const NAMES_SHOWN = 5;

/** "Move to…": pick the folder (type to filter, any existing or new folder), then the
 * move flow previews it. */
export function MoveToSheet({ names, initial, onCancel, onChoose }: SheetProps) {
  const [folder, setFolder] = useState(initial);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);
  const target = folder.trim().replace(/^\/+|\/+$/g, "");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (target) onChoose(target);
  };
  const shown = names.slice(0, NAMES_SHOWN).map(visible).join(", ");
  const more = names.length > NAMES_SHOWN ? ` +${names.length - NAMES_SHOWN} more` : "";
  return (
    <Sheet
      open
      className="move-to"
      title={`Move ${plural(names.length, "file")} to…`}
      onClose={onCancel}
      onKeyDown={(e) => e.stopPropagation()} // page shortcuts never see keys typed here
      footer={
        <>
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" form="move-to-form" className="primary" disabled={!target}>
            Preview move
          </button>
        </>
      }
    >
      <p className="move-to-files">
        {shown}
        {more}
      </p>
      <form id="move-to-form" onSubmit={submit}>
        <FolderPicker ref={input} label="Folder" value={folder} onChange={setFolder} />
      </form>
      <p className="hint">You see the planned moves before anything changes.</p>
    </Sheet>
  );
}
