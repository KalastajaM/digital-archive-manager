/** A file's ★ Ongoing and ! Important icons, after its name in any row (spec §2: the
 * icon follows the file). Nothing for a file with no marks. */
import { Lock, LockOpen, Star } from "lucide-react";
import { createContext, useContext } from "react";
import { isUnlockedNow, type Mark, useIsBlocked, useLocks } from "../api/client";
import { useStarredOf } from "./useStarredFiles";

export const MARK_LABEL: Record<Mark, string> = { starred: "Starred", important: "Important" };
/** A built-in collection as the UI names it: "★ Starred" (stored as "Ongoing", its
 * folder in ``##. Ongoing``) and "! Important". */
export const BUILTIN_LABEL: Record<Mark, string> = { starred: "★ Starred", important: "! Important" };

/** The ! glyph of Important (also the sidebar row's and the toggle's icon): drawn, not
 * text, so it never becomes part of a name's text. */
export function ImportantGlyph({ large = false }: { large?: boolean }) {
  const size = large ? 16 : 12;
  return (
    <svg className="mark-bang" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3.5v11" stroke="currentColor" strokeWidth={large ? 3.2 : 3.6} strokeLinecap="round" fill="none" />
      <circle cx="12" cy="20" r={large ? 1.9 : 2.2} fill="currentColor" />
    </svg>
  );
}

export function StarGlyph({ size = 14, filled = true }: { size?: number; filled?: boolean }) {
  return <Star size={size} strokeWidth={1.75} fill={filled ? "currentColor" : "none"} aria-hidden="true" />;
}

/** The mark a whole list is already about (the ★ Ongoing or ! Important collection): its
 * icon would repeat on every row, so rows inside leave it out. */
export const OmitMark = createContext<Mark | null>(null);

/** The lock of a file: shut when its rename, move and To Delete are refused, open while it
 * is unlocked for now. Nothing for a file that is not locked. */
function LockIcon({ driveId, marks, path }: { driveId: string; marks: readonly Mark[] | null | undefined; path?: string | null }) {
  const blocked = useIsBlocked()(driveId, marks, path);
  const locks = useLocks();
  const important = marks?.includes("important") ?? false;
  const locked = important || (locks.data?.files.some((f) => f.drive_id === driveId) ?? false);
  if (blocked) {
    return (
      <span className="mark-icon mark-lock" role="img" aria-label="Locked" title="Locked: it cannot be renamed or moved until you unlock it">
        <Lock size={12} strokeWidth={2} aria-hidden="true" />
      </span>
    );
  }
  if (locked && isUnlockedNow(driveId)) {
    return (
      <span className="mark-icon mark-lock" role="img" aria-label="Unlocked for now" title="Unlocked until you leave this file">
        <LockOpen size={12} strokeWidth={2} aria-hidden="true" />
      </span>
    );
  }
  return null;
}

/** ``driveId`` (with the file's ``path`` when it may lie in a locked folder) adds the lock icon. */
export function MarkIcons({
  marks,
  omit,
  driveId,
  path,
}: {
  marks: readonly Mark[] | null | undefined;
  omit?: Mark;
  driveId?: string;
  path?: string | null;
}) {
  const inherited = useContext(OmitMark);
  const skip = omit ?? inherited;
  const shown = marks?.filter((m) => m !== skip);
  const lock = driveId ? <LockIcon driveId={driveId} marks={marks} path={path} /> : null;
  if (!shown || shown.length === 0) return lock ? <span className="mark-icons">{lock}</span> : null;
  marks = shown;
  return (
    <span className="mark-icons">
      {marks.includes("starred") && (
        <span className="mark-icon mark-starred" role="img" aria-label={MARK_LABEL.starred} title={MARK_LABEL.starred}>
          <StarGlyph size={12} />
        </span>
      )}
      {marks.includes("important") && (
        <span className="mark-icon mark-important" role="img" aria-label={MARK_LABEL.important} title={MARK_LABEL.important}>
          <ImportantGlyph />
        </span>
      )}
      {lock}
    </span>
  );
}

/** A tray item's ★ on Today, whose rows have the item's file IDs but not their marks: shown
 * when any of its files is starred. */
export function ItemStar({ files }: { files: readonly string[] }) {
  const starredOf = useStarredOf();
  return starredOf(files).length > 0 ? <MarkIcons marks={["starred"]} /> : null;
}
