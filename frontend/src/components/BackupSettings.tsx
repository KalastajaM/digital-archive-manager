/** Settings → Backups: back up this archive's database and settings, and restore one. A
 * restore must answer "back up the current state first?" before anything is replaced. */
import { useState } from "react";
import {
  type Backup,
  errorText,
  navigation,
  restoreBackup,
  revealBackups,
  useBackups,
  useCreateBackup,
} from "../api/client";
import { clockTime, formatSize, longDay } from "../format";
import { visible } from "../text";
import { Sheet } from "./ui/Sheet";

const when = (iso: string) => {
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? iso : `${longDay(at)}, ${clockTime(at)}`;
};

export function BackupSettings() {
  const backups = useBackups();
  const create = useCreateBackup();
  const [restoring, setRestoring] = useState<Backup | null>(null);
  const [revealError, setRevealError] = useState<string | null>(null);
  const list = backups.data?.backups ?? [];

  return (
    <section aria-label="Backups">
      <h3>Backups</h3>
      <p className="hint">
        A backup holds this archive's database (index, tags, collections, notes, activity) and its settings (rules, trays, filing codes).
        Your documents are not in it. Backups are kept until you remove them from the folder yourself.
      </p>
      <div className="backup-actions">
        <button type="button" className="primary" disabled={create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? "Backing up…" : "Back up now"}
        </button>
        <button
          type="button"
          onClick={() => {
            setRevealError(null);
            revealBackups().catch((e: unknown) => setRevealError(errorText(e)));
          }}
        >
          Show folder
        </button>
      </div>
      {create.isSuccess && (
        <p className="first-run-ok" role="status">
          Backed up as {visible(create.data.name)}.
        </p>
      )}
      {create.isError && (
        <p className="error" role="alert">
          Could not back up: {visible(errorText(create.error))}
        </p>
      )}
      {revealError && (
        <p className="error" role="alert">
          {visible(revealError)}
        </p>
      )}
      {backups.isError && (
        <p className="error" role="alert">
          Could not load the backups: {visible(errorText(backups.error))}
        </p>
      )}
      {backups.data && list.length === 0 && <p className="hint">No backups yet.</p>}
      {list.length > 0 && (
        <ul className="backup-list" aria-label="Backups">
          {list.map((b) => (
            <li key={b.name} className="backup-row">
              <div>
                <strong>{when(b.created_at)}</strong>
                {b.kind === "before-restore" && <span className="hint"> · made before a restore</span>}
                <div className="hint">
                  {formatSize(b.size)}
                  {b.revision ? ` · database version ${visible(b.revision)}` : ""}
                </div>
                {b.problem && <div className="hint">{visible(b.problem)}</div>}
              </div>
              <button
                type="button"
                disabled={b.problem !== null || !backups.data?.can_restore}
                onClick={() => setRestoring(b)}
              >
                Restore…
              </button>
            </li>
          ))}
        </ul>
      )}
      {backups.data && !backups.data.can_restore && (
        <p className="hint">This window cannot restore a backup. Start dam with “dam serve” to restore.</p>
      )}
      {restoring && <RestoreSheet backup={restoring} onClose={() => setRestoring(null)} />}
    </section>
  );
}

function RestoreSheet({ backup, onClose }: { backup: Backup; onClose: () => void }) {
  const [busy, setBusy] = useState<"with" | "without" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const restore = (backupCurrent: boolean) => {
    setBusy(backupCurrent ? "with" : "without");
    setError(null);
    restoreBackup(backup.name, backupCurrent)
      .then(() => navigation.leave())
      .catch((e: unknown) => {
        setError(errorText(e));
        setBusy(null);
      });
  };
  return (
    <Sheet
      open
      title="Restore backup"
      onClose={() => {
        if (!busy) onClose();
      }}
      footer={
        <>
          <button type="button" disabled={busy !== null} onClick={onClose}>
            Cancel
          </button>
          <button type="button" disabled={busy !== null} onClick={() => restore(false)}>
            {busy === "without" ? "Restoring…" : "Restore without backup"}
          </button>
          <button type="button" className="primary" disabled={busy !== null} onClick={() => restore(true)}>
            {busy === "with" ? "Backing up and restoring…" : "Back up and restore"}
          </button>
        </>
      }
    >
      <p>
        Restore the backup from <strong>{when(backup.created_at)}</strong>? This replaces the database and the settings of this archive. Your
        documents are not changed.
      </p>
      <p className="hint">
        Activity and Undo go back to that moment. Files moved since then are found again when the archive is scanned. The current settings are
        moved aside to the backups folder, not deleted.
      </p>
      <p>
        <strong>Back up the current state first?</strong> Then you can return to it later.
      </p>
      {error && (
        <p className="error" role="alert">
          Could not restore: {visible(error)}
        </p>
      )}
    </Sheet>
  );
}
