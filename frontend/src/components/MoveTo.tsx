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
  type MoveBody,
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
import { type DropMode, FOLDERS_MOVE_ONLY, MODE_HINT, MODE_LABEL, DROP_MODES } from "../dropModes";
import { FolderPicker } from "./FolderPicker";
import { startedCopyJob } from "./CopyJobProgress";
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
  /** A drop on a folder: how the files get there (default Move). Link makes a shortcut
   * there and the file stays; Copy makes a duplicate. Undo of a Link removes the link
   * the app made; Undo of a Copy moves the copy to To Delete. */
  mode?: DropMode;
  /** With ``mode``: the sheet offers the choice, each way with the reason it is off (null:
   * on). Without it the request is plainly a move. */
  modes?: Record<DropMode, string | null>;
  /** The dragged rows are links in ##. Ongoing / ##. Important: the sheet names the real
   * file that moves, is linked or copied. */
  fromRows?: "ongoing" | "important";
  /** ``ids`` holds one folder, which moves with everything in it (Move only: Link and
   * Copy are off). Across disks it is copied file by file as a background job. */
  folderMove?: true;
};
type Pending = MoveRequest & { ops: ResolvedOp[]; error?: string | null };

const modeOf = (r: MoveRequest): DropMode => r.mode ?? "move";

/** A move of the folder ``id`` into ``folder``: Move only, with why Link and Copy are off. */
export function folderMoveRequest(id: string, folder: string): MoveRequest {
  return { ids: [id], folder, folderMove: true, modes: { move: null, link: FOLDERS_MOVE_ONLY, copy: FOLDERS_MOVE_ONLY } };
}

/** The name of the folder a folder plan moves: its move (one disk) or the putting aside
 * of the original (across disks). */
function movedFolderName(ops: ResolvedOp[]): string | null {
  const src = ops.find((op) => (op.kind === "move" || op.kind === "quarantine") && op.src)?.src;
  return src ? baseName(src) : null;
}
const VERB: Record<DropMode, string> = { move: "move", link: "link", copy: "copy" };
const parentOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");

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
  // a plain move sends no ``mode`` (the server's default), as it always did
  const body = (r: MoveRequest): MoveBody =>
    r.mode === undefined || r.mode === "move"
      ? ({ drive_ids: r.ids, folder: r.folder } as MoveBody)
      : { drive_ids: r.ids, folder: r.folder, mode: r.mode };
  const previewCall = (r: MoveRequest) =>
    r.name === undefined
      ? preview.mutateAsync(body(r))
      : renamePreview.mutateAsync({ drive_id: r.ids[0], name: r.name, folder: r.folder });
  const applyCall = (r: MoveRequest) =>
    r.name === undefined
      ? apply.mutateAsync(body(r))
      : rename.mutateAsync({ drive_id: r.ids[0], name: r.name, folder: r.folder });

  async function previewMove(request: MoveRequest) {
    let ops: ResolvedOp[];
    try {
      ops = await previewCall(request);
    } catch (e) {
      const text = `Cannot ${request.name === undefined ? VERB[modeOf(request)] : "change"}: ${visible(errorText(e))}`;
      if (onRefused) onRefused(text);
      else toast({ kind: "error", text });
      return;
    }
    if (ops.length === 0) {
      const nothing =
        request.name !== undefined
          ? "Nothing to change"
          : modeOf(request) === "link"
            ? `Nothing to link: already in ${folderLabel(request.folder)}`
            : `Nothing to move: already in ${folderLabel(request.folder)}`;
      if (onRefused) onRefused(request.nothing ?? nothing);
      else toast({ kind: "info", text: request.nothing ?? nothing });
      return;
    }
    setConfirm({ ...request, ops });
  }

  /** The choice in the sheet: preview the same files the other way; the sheet stays
   * open, and a way that cannot be previewed says why right there. */
  async function switchMode(pending: Pending, mode: DropMode) {
    if (mode === modeOf(pending)) return;
    const next: MoveRequest = { ...pending, mode };
    try {
      const ops = await previewCall(next);
      if (ops.length === 0) {
        setConfirm({ ...pending, error: `${MODE_LABEL[mode]}: nothing to do, the files are already in ${folderLabel(pending.folder)}` });
        return;
      }
      setConfirm({ ...next, ops, error: null });
    } catch (e) {
      setConfirm({ ...pending, error: `Cannot ${VERB[mode]}: ${visible(errorText(e))}` });
    }
  }

  async function applyMove(pending: Pending) {
    setConfirm(null);
    let result: MoveResult;
    try {
      result = await applyCall(pending);
    } catch (e) {
      toast({ kind: "error", text: `Could not ${pending.name === undefined ? VERB[modeOf(pending)] : "change"}: ${visible(errorText(e))}` });
      return;
    }
    if (result.job_id) {
      startedCopyJob(result.job_id); // a copy across disks: the progress view takes over
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
    const mode = modeOf(pending);
    const kind = mode === "link" ? "symlink" : mode;
    const moved = result.done.filter((op) => op.kind === kind);
    const renamed = result.done.find((op) => op.kind === "rename");
    if (result.done.length > 0) {
      const what = moved.length === 1 ? visible(baseName(moved[0].dst)) : plural(moved.length, "file");
      const target = { batchId: result.batch_id };
      const there = folderLabel(pending.folder);
      const said =
        moved.length === 0 && renamed
          ? `Renamed to ${visible(baseName(renamed.dst))}`
          : pending.folderMove && moved.length === 1
            ? `Moved folder ${visible(baseName(moved[0].dst))} to ${there}`
          : mode === "link"
            ? `Linked ${what} in ${there}`
            : mode === "copy"
              ? `Copied ${what} to ${there}`
              : `Moved ${what} to ${there}`;
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
      // a link or a copy moves nothing: the original stays listed, the folder reloads
      announceMoved(mode === "move" ? movedIds(result, pending) : []);
    }
  }

  const renaming = confirm?.name !== undefined;
  const renameOnly = renaming && !confirm?.ops.some((op) => op.kind === "move");
  const mode = confirm ? modeOf(confirm) : "move";
  const folderName = confirm?.folderMove ? movedFolderName(confirm.ops) : null;
  const count = confirm ? (folderName !== null ? visible(folderName) : plural(confirm.ids.length, "file")) : "";
  const there = confirm ? folderLabel(confirm.folder) : "";
  const view: ReactNode = confirm ? (
    <ConfirmPlan
      planKey={snapshotKey({ ids: confirm.ids, folder: confirm.folder, name: confirm.name, mode, ops: confirm.ops })}
      title={
        !renaming
          ? mode === "link"
            ? `Link ${count} in ${there}?`
            : mode === "copy"
              ? `Copy ${count} to ${there}?`
              : `Move ${count} to ${there}?`
          : renameOnly
            ? `Rename to ${visible(confirm.name ?? "")}?`
            : `Move to ${there} as ${visible(confirm.name ?? "")}?`
      }
      confirmLabel={
        renameOnly
          ? "Rename"
          : confirm.ops.some((op) => op.kind === "copy_across")
            ? "Copy and move"
            : confirm.folderMove
              ? "Move folder"
              : mode === "link"
              ? "Make links"
              : MODE_LABEL[mode]
      }
      intro={
        <>
          {confirm.modes && (
            <ModeChoice
              modes={confirm.modes}
              mode={mode}
              busy={busy}
              onChoose={(m) => void guarded(() => switchMode(confirm, m))}
            />
          )}
          {confirm.error && (
            <p className="error" role="alert">
              {confirm.error}
            </p>
          )}
          {confirm.fromRows && <FromRows pending={confirm} mode={mode} />}
          {renaming ? (
            <p>
              A name already taken there gets a suffix such as <code>_2</code>. Undo puts the file back as it was.
            </p>
          ) : confirm.folderMove ? (
            <p>Everything in the folder moves with it. Undo puts it back.</p>
          ) : mode === "link" ? (
            <p>
              Each link is a shortcut that opens the file; the file itself stays where it is. A name already taken
              there gets a suffix such as <code>_2</code>. Undo removes the links.
            </p>
          ) : mode === "copy" ? (
            <p>
              This makes a second copy of {confirm.ids.length === 1 ? "the file" : "each file"}; the original stays.
              A name already taken there gets a suffix such as <code>_2</code>. Undo moves the copies to To Delete.
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

/** Move / Link / Copy, as radio buttons in the sheet: a way that is off says why. */
function ModeChoice({
  modes,
  mode,
  busy,
  onChoose,
}: {
  modes: Record<DropMode, string | null>;
  mode: DropMode;
  busy: boolean;
  onChoose: (mode: DropMode) => void;
}) {
  return (
    <fieldset className="drop-modes" disabled={busy}>
      <legend className="visually-hidden">How the files get there</legend>
      {DROP_MODES.map((m) => (
        <label key={m} className="drop-mode" data-off={modes[m] ? "" : undefined} data-mode={m}>
          <input
            type="radio"
            name="drop-mode"
            value={m}
            checked={mode === m}
            disabled={modes[m] !== null && mode !== m}
            onChange={() => onChoose(m)}
          />
          <span className="drop-mode-name">{MODE_LABEL[m]}</span>
          <span className="drop-mode-hint">{modes[m] ?? MODE_HINT[m]}</span>
        </label>
      ))}
    </fieldset>
  );
}

/** The dragged rows were links in ##. Ongoing / ##. Important: say which real file acts,
 * and where it is now (the first op's source), so it is clear the filed document moves. */
function FromRows({ pending, mode }: { pending: Pending; mode: DropMode }) {
  const source = pending.ops.find((op) => op.src)?.src ?? null;
  if (!source) return null;
  const where = folderLabel(parentOf(source));
  const rows = pending.fromRows === "important" ? "##. Important" : "##. Ongoing";
  return (
    <p className="drop-from-rows">
      {mode === "move" ? (
        <>
          You dragged {pending.ids.length === 1 ? "a link" : "links"} from {rows}. This moves the filed document itself
          (currently in <strong>{visible(where)}</strong>) to <strong>{folderLabel(pending.folder)}</strong>, not just the
          link. It stays in its collections, and the link in Ongoing follows.
        </>
      ) : (
        <>
          You dragged {pending.ids.length === 1 ? "a link" : "links"} from {rows}. The {mode === "link" ? "link" : "copy"} is made
          from the filed document itself (in <strong>{visible(where)}</strong>), which stays there.
        </>
      )}
    </p>
  );
}

type SheetProps = {
  /** The names of the files to move (shown, up to a few). */
  names: string[];
  /** The sheet's title (default "Move N files to…"; a folder: "Move <name> to…"). */
  title?: string;
  /** The folder the picker starts with (e.g. the other pane's). */
  initial: string;
  onCancel: () => void;
  onChoose: (folder: string) => void;
};

const NAMES_SHOWN = 5;

/** "Move to…": pick the folder (type to filter, any existing or new folder), then the
 * move flow previews it. */
export function MoveToSheet({ names, title, initial, onCancel, onChoose }: SheetProps) {
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
      title={title ?? `Move ${plural(names.length, "file")} to…`}
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
