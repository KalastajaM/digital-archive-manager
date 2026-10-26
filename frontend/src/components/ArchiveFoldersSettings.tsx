/** Settings → Archive folders: the main folder and the extra folders attached to this
 * archive (another disk, a cloud drive). An extra folder can be detached (its files leave
 * the archive; nothing on the disk changes) and attached again, or forgotten: it leaves
 * the list and its label is free again. */
import { useQueryClient } from "@tanstack/react-query";
import { CircleAlert, HardDrive } from "lucide-react";
import { useEffect, useState } from "react";
import {
  type ArchiveFolder,
  addArchiveFolder,
  attachArchiveFolder,
  detachArchiveFolder,
  errorText,
  type FolderChange,
  useArchiveFolders,
} from "../api/client";
import { visible } from "../text";
import { Sheet } from "./ui/Sheet";

const statusOf = (f: ArchiveFolder) => (!f.attached ? "Detached" : f.connected ? "Connected" : "Not connected");

/** Shown when the server could not reopen the archive itself (as in first-run setup). */
function RestartNotice() {
  return (
    <p className="first-run-problem" role="status">
      <CircleAlert size={14} aria-hidden="true" /> One more step: stop dam (Ctrl+C in the terminal) and run <code>dam serve</code> again.
    </p>
  );
}

/** Detach an attached folder (optionally forgetting it), or forget a detached one. */
function DetachSheet({ folder, onClose, onDone }: { folder: ArchiveFolder; onClose: () => void; onDone: (c: FolderChange) => void }) {
  const detached = !folder.attached;
  const [ticked, setTicked] = useState(false);
  const forget = detached || ticked;
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const label = folder.label ?? "";
  // A forget also removes the rows of files no longer on the disk, which the list does not
  // count (a detached folder's are all such): a dry run says how many it really removes.
  const [forgets, setForgets] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    detachArchiveFolder(label, true, true).then(
      (c) => live && setForgets(c.files),
      (e) => live && setProblem(errorText(e)),
    );
    return () => {
      live = false;
    };
  }, [label]);
  const counting = forget && forgets === null;
  const run = async () => {
    setBusy(true);
    setProblem(null);
    try {
      onDone(await detachArchiveFolder(label, forget));
    } catch (e) {
      setProblem(errorText(e));
      setBusy(false);
    }
  };
  return (
    <Sheet
      open
      title={detached ? "Forget folder" : "Detach folder"}
      onClose={() => !busy && onClose()}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="primary danger" disabled={busy || counting} onClick={() => void run()}>
            {detached ? "Forget" : "Detach"}
          </button>
        </>
      }
    >
      {detached ? (
        forgets === null ? (
          <p className="first-run-hint">Counting its files…</p>
        ) : (
          <p>{`Forget '${visible(label)}'? It is removed from this list, with the tags, notes and collection places of its ${forgets} files, and its label can be used again. Nothing on the disk changes.`}</p>
        )
      ) : (
        <>
          <p>{`Detach '${visible(label)}'? Its ${folder.files} files leave the archive until you attach it again. Nothing on the disk changes.`}</p>
          <label className="check">
            <input type="checkbox" checked={ticked} disabled={busy} onChange={(e) => setTicked(e.target.checked)} />
            Also forget their tags, notes and collection places
          </label>
          {ticked && (
            <p className="first-run-hint">
              The folder is also removed from this list, so its label can be used again.
              {forgets !== null && forgets !== folder.files && ` This forgets ${forgets} files, counting those no longer on the disk.`}
            </p>
          )}
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

/** Label and path, checked with a dry run before anything is attached. */
function AddSheet({ onClose, onDone }: { onClose: () => void; onDone: (c: FolderChange) => void }) {
  const [label, setLabel] = useState("");
  const [path, setPath] = useState("");
  const [checked, setChecked] = useState<FolderChange | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const ready = label.trim() !== "" && path.trim() !== "";
  const edit = (set: (v: string) => void) => (e: { target: { value: string } }) => {
    set(e.target.value);
    setChecked(null); // what was checked is no longer what is typed
    setProblem(null);
  };
  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      if (checked === null) setChecked(await addArchiveFolder(label.trim(), path.trim(), true));
      else onDone(await addArchiveFolder(label.trim(), path.trim(), false));
    } catch (e) {
      setProblem(errorText(e));
    }
    setBusy(false);
  };
  return (
    <Sheet
      open
      title="Add folder"
      onClose={() => !busy && onClose()}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={!ready || busy} onClick={() => void submit()}>
            {checked === null ? "Check" : "Add folder"}
          </button>
        </>
      }
    >
      <p className="first-run-hint">
        Another folder, on this or another disk or a cloud drive, becomes part of this archive. Its files stay where they are.
      </p>
      <div className="field">
        <label htmlFor="add-folder-label">Label</label>
        <input id="add-folder-label" type="text" value={label} autoComplete="off" placeholder="For example Scans" onChange={edit(setLabel)} />
      </div>
      <div className="field">
        <label htmlFor="add-folder-path">Folder path</label>
        <input
          id="add-folder-path"
          type="text"
          value={path}
          spellCheck={false}
          autoComplete="off"
          placeholder="For example /Volumes/Scans"
          onChange={edit(setPath)}
        />
      </div>
      {checked && (
        <p className="first-run-ok" role="status">
          {`'${visible(checked.label)}' will be added from ${visible(checked.path)}. dam will index it in the background.`}
        </p>
      )}
      {problem && (
        <p className="first-run-problem" role="alert">
          <CircleAlert size={14} aria-hidden="true" /> {visible(problem)}
        </p>
      )}
    </Sheet>
  );
}

export function ArchiveFoldersSettings() {
  const client = useQueryClient();
  const folders = useArchiveFolders();
  const [detaching, setDetaching] = useState<ArchiveFolder | null>(null);
  const [adding, setAdding] = useState(false);
  const [restart, setRestart] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // Files come and go with a folder, so every list that shows files is stale.
  const changed = (c: FolderChange) => {
    setDetaching(null);
    setAdding(false);
    setRestart(c.restart_needed);
    void client.invalidateQueries();
  };
  const attach = async (label: string) => {
    setProblem(null);
    try {
      changed(await attachArchiveFolder(label));
    } catch (e) {
      setProblem(errorText(e));
    }
  };
  return (
    <section aria-label="Archive folders">
      <h3>Archive folders</h3>
      <p className="hint">
        An archive can have more than one folder, for example on another disk or a cloud drive. Detaching one takes its files out of the
        archive without touching the disk.
      </p>
      {restart && <RestartNotice />}
      {folders.isError && (
        <p className="error" role="alert">
          Could not load the folders: {visible(errorText(folders.error))}
        </p>
      )}
      {problem && (
        <p className="error" role="alert">
          {visible(problem)}
        </p>
      )}
      <ul className="archive-list" aria-label="Archive folders">
        {(folders.data?.folders ?? []).map((f) => (
          <li key={f.label ?? "main"} className="archive-row">
            <div className="archive-row-head">
              {f.label !== null && <HardDrive size={14} aria-hidden="true" />}
              <strong>{f.label === null ? "Main folder" : visible(f.label)}</strong>
              {f.label !== null && <span className="archive-this">{statusOf(f)}</span>}
            </div>
            <code title={f.path}>{f.path}</code>
            {f.label !== null && (
              <div className="archive-forget-actions">
                {f.attached ? (
                  <button type="button" onClick={() => setDetaching(f)}>
                    Detach
                  </button>
                ) : (
                  <>
                    <button type="button" onClick={() => void attach(f.label as string)}>
                      Attach again
                    </button>
                    <button type="button" onClick={() => setDetaching(f)}>
                      Forget
                    </button>
                  </>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="archive-forget-actions">
        <button type="button" onClick={() => setAdding(true)}>
          Add folder
        </button>
      </div>
      {detaching && <DetachSheet folder={detaching} onClose={() => setDetaching(null)} onDone={changed} />}
      {adding && <AddSheet onClose={() => setAdding(false)} onDone={changed} />}
    </section>
  );
}
