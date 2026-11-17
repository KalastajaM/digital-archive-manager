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
  changeMainFolder,
  detachArchiveFolder,
  errorText,
  type FolderChange,
  type MainFolderChange,
  useArchiveFolders,
} from "../api/client";
import { visible } from "../text";
import { ExpiredFolderSettings } from "./ExpiredFolderSettings";
import { VersionsFolderSettings } from "./VersionsFolderSettings";
import { FolderPathInput } from "./FolderPathInput";
import { RelabelSheet } from "./RelabelSheet";
import { SpecialFoldersSettings } from "./SpecialFoldersSettings";
import { Sheet } from "./ui/Sheet";

const statusOf = (f: ArchiveFolder) =>
  !f.attached ? "Detached" : f.connected ? "Connected" : "Not connected";

/** Shown when the server could not reopen the archive itself (as in first-run setup). */
function RestartNotice() {
  return (
    <p className="first-run-problem" role="status">
      <CircleAlert size={14} aria-hidden="true" /> One more step: stop dam
      (Ctrl+C in the terminal) and run <code>dam serve</code> again.
    </p>
  );
}

/** Detach an attached folder (optionally forgetting it), or forget a detached one. */
function DetachSheet({
  folder,
  onClose,
  onDone,
}: {
  folder: ArchiveFolder;
  onClose: () => void;
  onDone: (c: FolderChange) => void;
}) {
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
          <button
            type="button"
            className="primary danger"
            disabled={busy || counting}
            onClick={() => void run()}
          >
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
            <input
              type="checkbox"
              checked={ticked}
              disabled={busy}
              onChange={(e) => setTicked(e.target.checked)}
            />
            Also forget their tags, notes and collection places
          </label>
          {ticked && (
            <p className="first-run-hint">
              The folder is also removed from this list, so its label can be
              used again.
              {forgets !== null &&
                forgets !== folder.files &&
                ` This forgets ${forgets} files, counting those no longer on the disk.`}
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
function AddSheet({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (c: FolderChange) => void;
}) {
  const [label, setLabel] = useState("");
  const [path, setPath] = useState("");
  const [checked, setChecked] = useState<FolderChange | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const ready = label.trim() !== "" && path.trim() !== "";
  const edit =
    (set: (v: string) => void) => (e: { target: { value: string } }) => {
      set(e.target.value);
      setChecked(null); // what was checked is no longer what is typed
      setProblem(null);
    };
  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      if (checked === null)
        setChecked(await addArchiveFolder(label.trim(), path.trim(), true));
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
          <button
            type="button"
            className="primary"
            disabled={!ready || busy}
            onClick={() => void submit()}
          >
            {checked === null ? "Check" : "Add folder"}
          </button>
        </>
      }
    >
      <p className="first-run-hint">
        Another folder, on this or another disk or a cloud drive, becomes part
        of this archive. Its files stay where they are.
      </p>
      <div className="field">
        <label htmlFor="add-folder-label">Label</label>
        <input
          id="add-folder-label"
          type="text"
          value={label}
          autoComplete="off"
          placeholder="For example Scans"
          onChange={edit(setLabel)}
        />
      </div>
      <div className="field">
        <label htmlFor="add-folder-path">Folder path</label>
        <FolderPathInput
          id="add-folder-path"
          value={path}
          spellCheck={false}
          autoComplete="off"
          placeholder="For example /Volumes/Scans"
          onChange={(v) => edit(setPath)({ target: { value: v } })}
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

/** Point the archive at another main folder: the same documents, moved or reached by another
 * path. A dry run first says how many of the index's top-level folders the new folder lacks. */
function MainFolderSheet({
  current,
  onClose,
  onDone,
}: {
  current: string;
  onClose: () => void;
  onDone: (restart: boolean) => void;
}) {
  const [path, setPath] = useState("");
  const [checked, setChecked] = useState<MainFolderChange | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      if (checked === null)
        setChecked(await changeMainFolder(path.trim(), true));
      else onDone((await changeMainFolder(path.trim(), false)).restart_needed);
    } catch (e) {
      setProblem(errorText(e));
    }
    setBusy(false);
  };
  const lacks = checked !== null && checked.missing > 0;
  return (
    <Sheet
      open
      title="Change main folder"
      onClose={() => !busy && onClose()}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className={lacks ? "primary danger" : "primary"}
            disabled={path.trim() === "" || busy}
            onClick={() => void submit()}
          >
            {checked === null
              ? "Check"
              : lacks
                ? "Use it anyway"
                : "Use this folder"}
          </button>
        </>
      }
    >
      <p className="first-run-hint">
        Use this when you moved the documents folder, or reach it by another
        path. dam keeps the tags, notes, trays and collections of files that are
        at the same place inside the new folder. Nothing on the disk changes.
      </p>
      <p>
        Now: <code>{current}</code>
      </p>
      <div className="field">
        <label htmlFor="main-folder-path">New folder path</label>
        <FolderPathInput
          id="main-folder-path"
          value={path}
          spellCheck={false}
          autoComplete="off"
          placeholder="For example /Users/Shared/Digital Archive"
          onChange={(v) => {
            setPath(v);
            setChecked(null);
            setProblem(null);
          }}
        />
      </div>
      {checked && !lacks && (
        <p className="first-run-ok" role="status">
          {`The folder has all ${checked.known} top-level folders dam knows. dam will scan it in the background.`}
        </p>
      )}
      {lacks && (
        <p className="first-run-problem" role="alert">
          <CircleAlert size={14} aria-hidden="true" />
          {` ${checked.missing} of the ${checked.known} top-level folders dam knows are not in this folder (${checked.examples.map((n) => visible(n)).join(", ")}${checked.missing > checked.examples.length ? ", …" : ""}). Their files would show as missing, and their tags and notes wait until the folders are back. Is this the right folder?`}
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
  const [relabelling, setRelabelling] = useState<ArchiveFolder | null>(null);
  const [adding, setAdding] = useState(false);
  const [changingMain, setChangingMain] = useState(false);
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
        An archive can have more than one folder, for example on another disk or
        a cloud drive. Detaching one takes its files out of the archive without
        touching the disk.
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
              <strong>
                {f.label === null ? "Main folder" : visible(f.label)}
              </strong>
              {f.label !== null && (
                <span className="archive-this">{statusOf(f)}</span>
              )}
            </div>
            <code title={f.path}>{f.path}</code>
            {f.label === null && (
              <div className="archive-forget-actions">
                <button type="button" onClick={() => setChangingMain(true)}>
                  Change folder…
                </button>
              </div>
            )}
            {f.label !== null && (
              <div className="archive-forget-actions">
                <button type="button" onClick={() => setRelabelling(f)}>
                  Change label
                </button>
                {f.attached ? (
                  <button type="button" onClick={() => setDetaching(f)}>
                    Detach
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => void attach(f.label as string)}
                    >
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
      {detaching && (
        <DetachSheet
          folder={detaching}
          onClose={() => setDetaching(null)}
          onDone={changed}
        />
      )}
      {changingMain && (
        <MainFolderSheet
          current={
            (folders.data?.folders ?? []).find((f) => f.label === null)?.path ??
            ""
          }
          onClose={() => setChangingMain(false)}
          onDone={(restart_needed) => {
            setChangingMain(false);
            changed({ label: "", path: "", files: 0, restart_needed });
          }}
        />
      )}
      {adding && <AddSheet onClose={() => setAdding(false)} onDone={changed} />}
      <SpecialFoldersSettings />
      <ExpiredFolderSettings />
      <VersionsFolderSettings />
      {relabelling && (
        <RelabelSheet
          folder={relabelling}
          onClose={() => setRelabelling(null)}
          onDone={(r) => {
            setRelabelling(null);
            changed({
              label: r.new_label,
              path: relabelling.path,
              files: 0,
              restart_needed: r.restart_needed,
            });
          }}
        />
      )}
    </section>
  );
}
