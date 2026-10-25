/** A file's lock, next to its name: Unlock / Lock / "Unlocked until you leave this file"
 * with Lock again. A locked file can be viewed and described (tags, notes, marks, trays),
 * but its rename, move and To Delete are off; the server refuses them too.
 *
 * Unlock "For now" lasts until this file is left (another file selected, the panel closed,
 * another page, a reload): this component going away locks it again. Only an ordinary
 * locked file can be unlocked "For good"; an Important file only for now. */
import { Lock, LockOpen } from "lucide-react";
import { useState } from "react";
import { type Mark, useFileLock } from "../api/client";
import { visible } from "../text";
import { IconButton } from "./ui/IconButton";

export function LockControl({
  driveId,
  marks,
  path,
}: {
  driveId: string;
  marks?: readonly Mark[];
  path?: string | null;
}) {
  const lock = useFileLock(driveId, marks, path, true);
  const [asking, setAsking] = useState(false);

  if (lock.unlockedNow) {
    return (
      <span className="lock-control" role="group" aria-label="Lock">
        <span className="lock-state" role="status">
          Unlocked until you leave this file
        </span>
        <IconButton
          icon={<LockOpen />}
          label="Lock again"
          tip="Unlocked for now. Click to lock this file again now"
          disabled={lock.busy}
          onClick={() => {
            setAsking(false);
            lock.relock();
          }}
        />
      </span>
    );
  }
  if (lock.locked) {
    const unlockNow = () => {
      setAsking(false);
      void lock.unlock("now");
    };
    return (
      <span className="lock-control" role="group" aria-label="Lock">
        {asking ? (
          <>
            <span className="lock-ask">Unlock</span>
            <button type="button" disabled={lock.busy} onClick={unlockNow}>
              For now
            </button>
            <button
              type="button"
              disabled={lock.busy}
              onClick={() => {
                setAsking(false);
                void lock.unlock("for_good");
              }}
            >
              For good
            </button>
            <button type="button" onClick={() => setAsking(false)}>
              Cancel
            </button>
          </>
        ) : (
          <IconButton
            icon={<Lock />}
            label="Unlock"
            tip={
              lock.important
                ? "Locked: an Important file is always locked. Click to unlock it for now; it locks again when you leave this file"
                : "Locked. Click to unlock this file so it can be renamed or moved"
            }
            disabled={lock.busy}
            onClick={() => (lock.important ? unlockNow() : setAsking(true))}
          />
        )}
        {lock.error && (
          <span className="error" role="alert">
            {visible(lock.error)}
          </span>
        )}
      </span>
    );
  }
  return (
    <span className="lock-control" role="group" aria-label="Lock">
      <IconButton
        icon={<LockOpen />}
        label="Lock"
        tip="Not locked. Click to lock this file so it cannot be renamed or moved by mistake"
        disabled={lock.busy}
        onClick={() => void lock.lock()}
      />
      {lock.error && (
        <span className="error" role="alert">
          {visible(lock.error)}
        </span>
      )}
    </span>
  );
}
