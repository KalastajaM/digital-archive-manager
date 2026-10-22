/** Labels and badges for a tray item, from what the API says about it (its level and
 * file state). Shared by Today and the Trays screen. */
import type { AttentionItem } from "../api/client";

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

/** The file badge (missing, or in ##. To Delete); nothing when the file is fine. A missing
 * required field is not announced: the field simply stays empty. */
export function ItemBadges({ fileState }: { fileState: FileState }) {
  const fileBadge = FILE_BADGE[fileState];
  if (!fileBadge) return null;
  return (
    <p className="badges">
      <span className="badge badge-error">{fileBadge}</span>
    </p>
  );
}
