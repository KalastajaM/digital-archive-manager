/** Settings → Snapshots: take a snapshot of this archive's database and settings, export
 * one to keep elsewhere, import one, and restore one. A restore must answer "keep the
 * current state as a snapshot first?" before anything is replaced, and a snapshot of
 * another archive folder must be confirmed as such. */
import { useRef, useState } from "react";
import {
  errorText,
  navigation,
  restoreSnapshot,
  revealSnapshots,
  type Snapshot,
  snapshotDownloadUrl,
  useCreateSnapshot,
  useImportSnapshot,
  useSnapshots,
} from "../api/client";
import { clockTime, formatSize, longDay } from "../format";
import { visible } from "../text";
import { Sheet } from "./ui/Sheet";
import { TipButton } from "./ui/TipButton";

const when = (iso: string) => {
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? iso : `${longDay(at)}, ${clockTime(at)}`;
};

function marks(s: Snapshot): string[] {
  const out: string[] = [];
  if (s.kind === "before-restore") out.push("taken before a restore");
  if (s.kind === "before-relabel") out.push("taken before a label change");
  if (s.kind === "before-rename") out.push("taken before a special folder was renamed");
  if (s.kind === "before-groups") out.push("taken before the groups in collections became collections");
  if (s.kind === "before-merge") out.push("taken before a collection was merged into another");
  if (s.kind === "before-delete") out.push("taken before a collection was deleted");
  if (s.imported) out.push("imported");
  return out;
}

export function SnapshotSettings() {
  const snapshots = useSnapshots();
  const create = useCreateSnapshot();
  const add = useImportSnapshot();
  const picker = useRef<HTMLInputElement>(null);
  const [restoring, setRestoring] = useState<Snapshot | null>(null);
  const [revealError, setRevealError] = useState<string | null>(null);
  const list = snapshots.data?.snapshots ?? [];

  return (
    <section aria-label="Snapshots">
      <h3>Snapshots</h3>
      <p className="hint">
        A snapshot holds this archive's database (index, tags, collections, notes, activity) and its settings (rules, trays, filing codes). Your
        documents are not in it. Snapshots are kept in this archive's data folder on this computer, so they help when a change goes wrong but not
        when the disk fails: <strong>Export</strong> a snapshot (or copy its file from the folder) to keep it on another disk or in the cloud. dam never
        removes a snapshot.
      </p>
      <div className="snapshot-actions">
        <button type="button" className="primary" disabled={create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? "Taking snapshot…" : "Take snapshot"}
        </button>
        <TipButton
          tip="Add a snapshot file you saved earlier. It is checked first; nothing is restored yet."
          disabled={add.isPending}
          onClick={() => picker.current?.click()}
        >
          {add.isPending ? "Importing…" : "Import…"}
        </TipButton>
        <input
          ref={picker}
          type="file"
          accept=".zip,application/zip"
          hidden
          aria-label="Snapshot file to import"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) add.mutate(file);
          }}
        />
        <button
          type="button"
          onClick={() => {
            setRevealError(null);
            revealSnapshots().catch((e: unknown) => setRevealError(errorText(e)));
          }}
        >
          Show folder
        </button>
      </div>
      {create.isSuccess && (
        <p className="snapshot-note" role="status">
          Snapshot taken: {visible(create.data.name)}.
        </p>
      )}
      {add.isSuccess && (
        <p className="snapshot-note" role="status">
          Imported the snapshot from {when(add.data.created_at)}. Restore it from the list when you want it.
        </p>
      )}
      {create.isError && (
        <p className="error" role="alert">
          Could not take a snapshot: {visible(errorText(create.error))}
        </p>
      )}
      {add.isError && (
        <p className="error" role="alert">
          Could not import that file: {visible(errorText(add.error))}
        </p>
      )}
      {revealError && (
        <p className="error" role="alert">
          {visible(revealError)}
        </p>
      )}
      {snapshots.isError && (
        <p className="error" role="alert">
          Could not load the snapshots: {visible(errorText(snapshots.error))}
        </p>
      )}
      {snapshots.data && list.length === 0 && <p className="hint">No snapshots yet.</p>}
      {list.length > 0 && (
        <ul className="snapshot-list" aria-label="Snapshots">
          {list.map((s) => (
            <li key={s.name} className="snapshot-row">
              <div>
                <strong>{when(s.created_at)}</strong>
                {marks(s).length > 0 && <span className="hint"> · {marks(s).join(" · ")}</span>}
                <div className="hint">
                  {formatSize(s.size)}
                  {s.revision ? ` · database version ${visible(s.revision)}` : ""}
                </div>
                {s.other_folder && <div className="hint">Of another archive folder: {visible(s.archive_root ?? "unknown")}</div>}
                {s.problem && <div className="hint">{visible(s.problem)}</div>}
              </div>
              <div className="snapshot-row-actions">
                <a
                  className="button-link tip-end"
                  href={snapshotDownloadUrl(s.name)}
                  download={s.name}
                  data-tip="Save a copy of this snapshot (a zip file), for example on another disk. The same as copying it from the folder."
                >
                  Export
                </a>
                <TipButton
                  className="tip-end"
                  tip="Replace this archive's database and settings with this snapshot. You are asked first."
                  disabled={s.problem !== null || !snapshots.data?.can_restore}
                  disabledReason={s.problem ?? (snapshots.data?.can_restore ? null : "This window cannot restore a snapshot.")}
                  onClick={() => setRestoring(s)}
                >
                  Restore…
                </TipButton>
              </div>
            </li>
          ))}
        </ul>
      )}
      {snapshots.data && !snapshots.data.can_restore && (
        <p className="hint">This window cannot restore a snapshot. Start dam with “dam serve” to restore.</p>
      )}
      {restoring && <RestoreSheet snapshot={restoring} onClose={() => setRestoring(null)} />}
    </section>
  );
}

function RestoreSheet({ snapshot, onClose }: { snapshot: Snapshot; onClose: () => void }) {
  const [busy, setBusy] = useState<"with" | "without" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [otherOk, setOtherOk] = useState(false);
  const blocked = busy !== null || (snapshot.other_folder && !otherOk);
  const restore = (snapshotCurrent: boolean) => {
    setBusy(snapshotCurrent ? "with" : "without");
    setError(null);
    restoreSnapshot(snapshot.name, snapshotCurrent, snapshot.other_folder && otherOk)
      .then(() => navigation.leave())
      .catch((e: unknown) => {
        setError(errorText(e));
        setBusy(null);
      });
  };
  return (
    <Sheet
      open
      title="Restore snapshot"
      onClose={() => {
        if (!busy) onClose();
      }}
      footer={
        <>
          <button type="button" disabled={busy !== null} onClick={onClose}>
            Cancel
          </button>
          <button type="button" disabled={blocked} onClick={() => restore(false)}>
            {busy === "without" ? "Restoring…" : "Restore without snapshot"}
          </button>
          <button type="button" className="primary" disabled={blocked} onClick={() => restore(true)}>
            {busy === "with" ? "Taking snapshot and restoring…" : "Take snapshot and restore"}
          </button>
        </>
      }
    >
      <p>
        Restore the snapshot from <strong>{when(snapshot.created_at)}</strong>? This replaces the database and the settings of this archive. Your
        documents are not changed.
      </p>
      <p className="hint">
        Activity and Undo go back to that moment. Files moved since then are found again when the archive is scanned. The current settings are
        moved aside to the snapshots folder, not deleted. This archive's own folders, its protected paths and the folders never sent to AI are kept
        as they are now; the snapshot can add to those, not remove from them.
      </p>
      {snapshot.other_folder && (
        <label className="check">
          <input type="checkbox" checked={otherOk} disabled={busy !== null} onChange={(e) => setOtherOk(e.target.checked)} />
          <span>
            This snapshot is of another archive folder ({visible(snapshot.archive_root ?? "unknown")}). Restore it anyway and keep this archive's own
            folders. Do this only for the same documents, for example on a new computer.
          </span>
        </label>
      )}
      <p>
        <strong>Take a snapshot of the current state first?</strong> Then you can return to it later.
      </p>
      {error && (
        <p className="error" role="alert">
          Could not restore: {visible(error)}
        </p>
      )}
    </Sheet>
  );
}
