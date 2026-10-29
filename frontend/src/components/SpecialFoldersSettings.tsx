/** Settings → Archive folders → Special folders (New look): the Inbox, Ongoing, Important and
 * To Delete folders with their names, and a Rename for each. Renaming asks for the new name,
 * previews every place the name is stored (what is renamed, rebuilt or stays as it is), then
 * renames. The change is one entry in Activity and the toast offers Undo. */
import { useQueryClient } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import { useState } from "react";
import {
  errorText,
  renameSpecialFolder,
  type SpecialFolderKey,
  type SpecialFolderRename,
  useStatus,
  useUndo,
} from "../api/client";
import { visible } from "../text";
import { undoAction, useBlockToastActions, useToast } from "./Toasts";
import { Sheet } from "./ui/Sheet";

export const SPECIAL_FOLDERS: { key: SpecialFolderKey; title: string; purpose: string }[] = [
  { key: "inbox", title: "Inbox", purpose: "New files wait here until you file them." },
  { key: "ongoing", title: "Ongoing", purpose: "dam shows your open collections here, as shortcuts." },
  { key: "important", title: "Important", purpose: "dam shows files marked Important here, as shortcuts." },
  { key: "quarantine", title: "To Delete", purpose: "Files marked for deletion wait here. You empty it." },
];

const HOW: Record<SpecialFolderRename["places"][number]["how"], string> = {
  renamed: "Renamed",
  rebuilt: "Rebuilt",
  unchanged: "Stays",
};

function RenameSheet({
  folderKey,
  title,
  current,
  onClose,
  onDone,
}: {
  folderKey: SpecialFolderKey;
  title: string;
  current: string;
  onClose: () => void;
  onDone: (r: SpecialFolderRename) => void;
}) {
  const [name, setName] = useState(current);
  const [checked, setChecked] = useState<SpecialFolderRename | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      if (checked === null) setChecked(await renameSpecialFolder(folderKey, name, true));
      else onDone(await renameSpecialFolder(folderKey, name, false));
    } catch (e) {
      setProblem(errorText(e));
    }
    setBusy(false);
  };
  return (
    <Sheet
      open
      title={`Rename the ${title} folder`}
      onClose={() => !busy && onClose()}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={!name.trim() || busy} onClick={() => void submit()}>
            {checked === null ? "Preview" : "Rename folder"}
          </button>
        </>
      }
    >
      <p className="first-run-hint">
        {`The folder is renamed on your disk, then the settings, rules and index follow. It is one entry in Activity that Undo takes back completely. dam stops for a few seconds while it opens the archive again.`}
      </p>
      <div className="field">
        <label htmlFor="special-folder-name">New name</label>
        <input
          id="special-folder-name"
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
      {checked && (
        <>
          <p className="first-run-ok" role="status">
            {`'${visible(checked.old)}' becomes '${visible(checked.new)}'. This is what changes:`}
          </p>
          <ul className="rename-places" aria-label="What changes">
            {checked.places.map((p) => (
              <li key={p.place} data-how={p.how}>
                <span className="rename-how">{HOW[p.how]}</span>
                <span className="rename-place">{visible(p.place)}</span>
                <span className="rename-what">{visible(p.what)}</span>
              </li>
            ))}
          </ul>
          {checked.warnings.map((w) => (
            <p key={w} className="first-run-hint rename-warning">
              {visible(w)}
            </p>
          ))}
          <p className="first-run-hint">{visible(checked.undo)}</p>
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

export function SpecialFoldersSettings() {
  const client = useQueryClient();
  const status = useStatus();
  const toast = useToast();
  const undo = useUndo();
  useBlockToastActions(undo.isPending);
  const [renaming, setRenaming] = useState<SpecialFolderKey | null>(null);
  const names = status.data?.special_folders;
  const reopened = () => void client.invalidateQueries();
  const done = (title: string, r: SpecialFolderRename) => {
    setRenaming(null);
    reopened();
    toast({
      kind: "info",
      text: `Renamed the ${title} folder to '${r.new}'.`,
      action: undoAction(() => {
        undo.mutate(r.batch_id as string, {
          onSuccess: () => toast({ kind: "info", text: `The ${title} folder is called '${r.old}' again.` }),
          onError: (e) => toast({ kind: "error", text: `Could not undo: ${visible(errorText(e))}` }),
        });
      }),
    });
  };
  const target = SPECIAL_FOLDERS.find((f) => f.key === renaming);
  return (
    <div className="special-folders" role="group" aria-labelledby="special-folders-title">
      <h4 id="special-folders-title">Special folders</h4>
      <p className="hint">
        The folders dam keeps in your archive. Give them names that suit you; everything that holds the name follows, and Undo in Activity puts it all back.
      </p>
      <ul className="special-folder-list" aria-label="Special folders">
        {SPECIAL_FOLDERS.map((f) => (
          <li key={f.key} className="special-folder-row">
            <div className="special-folder-text">
              <strong>{f.title}</strong>
              <span className="hint">{f.purpose}</span>
            </div>
            <code title={names?.[f.key]}>{names ? visible(names[f.key]) : "…"}</code>
            <button type="button" aria-label={`Rename the ${f.title} folder`} disabled={!names} onClick={() => setRenaming(f.key)}>
              Rename
            </button>
          </li>
        ))}
      </ul>
      {target && names && (
        <RenameSheet
          folderKey={target.key}
          title={target.title}
          current={names[target.key]}
          onClose={() => setRenaming(null)}
          onDone={(r) => done(target.title, r)}
        />
      )}
    </div>
  );
}
