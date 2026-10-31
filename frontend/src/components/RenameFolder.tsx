/** "Rename…" for a folder in Browse: asks for the new name, previews every place that stores
 * the folder's path (what is renamed, rebuilt or stays with it), then renames it in place. The
 * change is one entry in Activity and the toast offers Undo, which puts back the folder and
 * every path that followed it. */
import { CircleAlert } from "lucide-react";
import { type FormEvent, type ReactNode, useState } from "react";
import { errorText, type FolderRename, previewFolderRename, useRenameFolder, useUndo } from "../api/client";
import { visible } from "../text";
import { RenamePlaces } from "./SpecialFoldersSettings";
import { undoAction, useBlockToastActions, useToast } from "./Toasts";
import { Sheet } from "./ui/Sheet";

type Folder = { drive_id: string; name: string; path: string };

/** ``path`` with the folder ``from`` (or a path under it) replaced by ``to``; any other path
 * as it is. */
export function followRename(path: string, from: string, to: string): string {
  if (path === from) return to;
  return path.startsWith(`${from}/`) ? to + path.slice(from.length) : path;
}

/** The Rename sheet: ``open`` it for a folder. ``onRenamed(from, to)``: the folder's path
 * changed (also back again by Undo), so a pane showing it can follow. */
export function useRenameFolderSheet(onRenamed?: (from: string, to: string) => void): {
  open: (folder: Folder) => void;
  view: ReactNode;
} {
  const [folder, setFolder] = useState<Folder | null>(null);
  const toast = useToast();
  const undo = useUndo();
  useBlockToastActions(undo.isPending);
  const done = (r: FolderRename) => {
    setFolder(null);
    onRenamed?.(r.path, r.new_path);
    toast({
      kind: "info",
      text: `Renamed the folder ${visible(r.old)} to ${visible(r.new)}.`,
      action: undoAction(() => {
        undo.mutate(r.batch_id as string, {
          onSuccess: () => {
            onRenamed?.(r.new_path, r.path);
            toast({ kind: "info", text: `The folder is called ${visible(r.old)} again.` });
          },
          onError: (e) => toast({ kind: "error", text: `Could not undo: ${visible(errorText(e))}` }),
        });
      }),
    });
  };
  return {
    open: setFolder,
    view: folder && <RenameFolderSheet key={folder.drive_id} folder={folder} onClose={() => setFolder(null)} onDone={done} />,
  };
}

function RenameFolderSheet({ folder, onClose, onDone }: { folder: Folder; onClose: () => void; onDone: (r: FolderRename) => void }) {
  const [name, setName] = useState(folder.name);
  const [checked, setChecked] = useState<FolderRename | null>(null);
  const [checking, setChecking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const rename = useRenameFolder();
  const busy = checking || rename.isPending;
  const trimmed = name.trim();
  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (busy || !trimmed || trimmed === folder.name) return;
    setProblem(null);
    try {
      if (checked === null) {
        setChecking(true);
        setChecked(await previewFolderRename(folder.drive_id, trimmed));
      } else {
        onDone(await rename.mutateAsync({ driveId: folder.drive_id, name: trimmed }));
      }
    } catch (err) {
      setProblem(errorText(err));
    }
    setChecking(false);
  };
  return (
    <Sheet
      open
      title={`Rename folder ${visible(folder.name)}`}
      onClose={() => !busy && onClose()}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" form="rename-folder-form" className="primary" disabled={!trimmed || trimmed === folder.name || busy}>
            {checked === null ? "Preview" : "Rename folder"}
          </button>
        </>
      }
    >
      <form id="rename-folder-form" onSubmit={(e) => void submit(e)}>
        <p className="first-run-hint">
          {`The folder is renamed on your disk, then the index, rules, filing codes and settings that hold its path follow. It is one entry in Activity that Undo takes back completely. dam stops for a few seconds while it opens the archive again.`}
        </p>
        <div className="field">
          <label htmlFor="rename-folder-name">New name</label>
          <input
            id="rename-folder-name"
            type="text"
            value={name}
            autoComplete="off"
            spellCheck={false}
            autoFocus
            onFocus={(e) => e.currentTarget.select()}
            onChange={(e) => {
              setName(e.target.value);
              setChecked(null);
              setProblem(null);
            }}
          />
        </div>
      </form>
      {checked && (
        <>
          <p className="first-run-ok" role="status">
            {`'${visible(checked.path)}' becomes '${visible(checked.new_path)}'. This is what changes:`}
          </p>
          <RenamePlaces checked={checked} />
        </>
      )}
      {problem && (
        <p className="first-run-problem" role="alert">
          <CircleAlert size={14} aria-hidden="true" /> {visible(problem)}
        </p>
      )}
    </Sheet>
  );
}
