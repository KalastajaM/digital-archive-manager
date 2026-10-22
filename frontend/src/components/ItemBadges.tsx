/** Labels and badges for a tray item, from what the API says about it (its level,
 * missing required fields and file state). Shared by Today and the Trays screen. */
import type { AttentionItem } from "../api/client";
import { fieldWord } from "../format";
import { visible } from "../text";

export type Level = AttentionItem["level"];
export type FileState = AttentionItem["file_state"];

export const LEVEL_LABEL: Record<Level, string> = {
  overdue: "Overdue",
  today: "Today",
  soon: "Soon",
  undated: "No date",
};

export const FILE_BADGE: Record<FileState, string | null> = {
  ok: null,
  missing: "file missing",
  to_delete: "file in ##. To Delete",
};

/** "needs a due date" (level undated), "needs <other required fields>", and the file
 * badge; nothing when there is nothing to say. */
export function ItemBadges({
  level,
  missingRequired,
  dateField,
  fileState,
}: {
  level: Level | null;
  missingRequired: string[];
  dateField: string | null | undefined;
  fileState: FileState;
}) {
  const fileBadge = FILE_BADGE[fileState];
  const otherMissing = missingRequired.filter((n) => !(level === "undated" && n === dateField));
  if (level !== "undated" && otherMissing.length === 0 && !fileBadge) return null;
  return (
    <p className="badges">
      {level === "undated" && <span className="badge badge-warn">needs a due date</span>}
      {otherMissing.length > 0 && (
        <span className="badge badge-warn">needs {otherMissing.map((n) => visible(fieldWord(n))).join(", ")}</span>
      )}
      {fileBadge && <span className="badge badge-error">{fileBadge}</span>}
    </p>
  );
}
