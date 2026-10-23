/** Getting documents in: "Choose files…" copies the chosen files into the inbox, and so
 * does a drop of files or folders from Finder (a folder's files land flat, its hidden
 * files left out). The originals stay where they are; a taken name gets _2; nothing is
 * overwritten. Each file is one journaled batch (Undo moves the copy to To Delete). */
import { type DragEvent as ReactDragEvent, type ReactNode, useRef, useState } from "react";
import { type ApiError, errorText, useUploadToInbox } from "../api/client";
import { type DropTarget, useDropTarget } from "../dnd";
import { plural } from "../format";
import { visible } from "../text";
import { undoAction, useToast } from "./Toasts";
import { useUndoConfirm } from "./UndoConfirm";

/** The biggest file the inbox takes (the server's limit, ``MAX_COPY_BYTES``). */
export const MAX_UPLOAD_MB = 200;

/** The most files one drop copies: a folder dropped by mistake (a whole Documents) is
 * refused instead of filling the inbox with hundreds of copies to undo one by one. */
export const MAX_DROP_FILES = 100;

/** Hidden and system files a dropped folder brings along; they are never copied. */
const isHidden = (name: string) => name.startsWith(".") || ["Thumbs.db", "desktop.ini", "Icon\r"].includes(name);

/** A drag from outside the app that carries files (Finder, Explorer, the desktop). A
 * drag started in dam carries its own ``application/x-dam-*`` type and is never one. */
function readOutsideFiles(e: DragEvent | ReactDragEvent): DataTransfer | null {
  const dt = e.dataTransfer;
  const types = Array.from(dt?.types ?? []);
  return types.includes("Files") && !types.some((t) => t.startsWith("application/x-dam-")) ? dt : null;
}

const fileOf = (entry: FileSystemFileEntry) => new Promise<File>((resolve, reject) => entry.file(resolve, reject));

async function childrenOf(dir: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> {
  const reader = dir.createReader();
  const all: FileSystemEntry[] = [];
  // readEntries hands out a folder in batches; an empty one means all were read
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
    if (batch.length === 0) return all;
    all.push(...batch);
  }
}

/** The files of a drop: the dropped files themselves and every file inside the dropped
 * folders, at any depth; hidden ones inside folders are counted and left out. The
 * entries are taken while the drop event lasts (the browser empties them after). */
function droppedFiles(dt: DataTransfer): () => Promise<{ files: File[]; hidden: number }> {
  const entries = Array.from(dt.items ?? [])
    .filter((item) => item.kind === "file")
    .map((item) => item.webkitGetAsEntry?.() ?? null);
  const loose = Array.from(dt.files ?? []);
  return async () => {
    if (entries.length === 0 || entries.some((e) => e === null)) return { files: loose, hidden: 0 };
    const files: File[] = [];
    let hidden = 0;
    const walk = async (entry: FileSystemEntry, inFolder: boolean) => {
      if (inFolder && isHidden(entry.name)) {
        hidden += 1;
        return;
      }
      if (entry.isFile) files.push(await fileOf(entry as FileSystemFileEntry));
      else if (entry.isDirectory) {
        for (const child of await childrenOf(entry as FileSystemDirectoryEntry)) await walk(child, true);
      }
    };
    for (const entry of entries as FileSystemEntry[]) await walk(entry, false);
    return { files, hidden };
  };
}

/** ``unavailable``: why nothing can be added now (no inbox folder yet); a drop is refused
 * with it. ``drop`` makes an element take files and folders dragged from Finder. */
export function useAddFiles(unavailable: string | null = null): {
  choose: () => void;
  busy: boolean;
  drop: DropTarget;
  view: ReactNode;
} {
  const upload = useUploadToInbox();
  const toast = useToast();
  const undo = useUndoConfirm();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const running = useRef(false);

  async function addAll(files: File[], hidden = 0) {
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
        text:
          `Copied ${plural(added.length, "file")} into the inbox.` +
          (hidden > 0 ? ` Left out ${plural(hidden, "hidden file")}.` : "") +
          (added.length > 1 ? " Undo each one from Activity." : ""),
        action: added.length === 1 ? undoAction(() => undo.open({ batchId: added[0] })) : undefined,
      });
    }
    if (problems.length > 0) toast({ kind: "error", text: `Not copied: ${problems.join("; ")}` });
  }

  async function addDropped(read: () => Promise<{ files: File[]; hidden: number }>) {
    let found: { files: File[]; hidden: number };
    try {
      found = await read();
    } catch (e) {
      toast({ kind: "error", text: `Could not read what was dropped: ${visible(errorText(e))}` });
      return;
    }
    const { files, hidden } = found;
    if (files.length > MAX_DROP_FILES) {
      toast({ kind: "error", text: `Not copied: that is ${plural(files.length, "file")}; drop at most ${MAX_DROP_FILES} at a time.` });
    } else if (files.length === 0) {
      toast({ kind: "info", text: hidden > 0 ? "Nothing copied: the folder holds only hidden files." : "Nothing copied: the folder is empty." });
    } else void addAll(files, hidden);
  }

  const drop = useDropTarget<DataTransfer>({
    read: readOutsideFiles,
    accept: () => unavailable ?? (busy ? "Still copying the last files" : true),
    onDrop: (dt) => void addDropped(droppedFiles(dt)),
  });

  return {
    choose: () => input.current?.click(),
    busy,
    drop,
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
