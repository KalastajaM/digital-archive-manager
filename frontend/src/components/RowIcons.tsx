import { AlignLeft, ListChecks, Pencil, Sparkles } from "lucide-react";
import type { TrayItem } from "../api/client";

/** What an item row says at a glance, before the date badge: a note, open to-dos (their
 * count), a summary (AI or written by the owner). Nothing when there is none of them. */
export function RowIcons({ item }: { item: Pick<TrayItem, "has_note" | "checklist_open" | "checklist_total" | "summary"> }) {
  const open = item.checklist_open;
  const todos = `${open} of ${item.checklist_total} to-dos open`;
  const summary = item.summary === "ai" ? "AI summary" : "Summary";
  if (!item.has_note && open === 0 && item.summary === null) return null;
  return (
    <span className="row-icons">
      {item.has_note && (
        <span className="row-icon" role="img" aria-label="Note" title="Note">
          <Pencil size={14} aria-hidden="true" />
        </span>
      )}
      {open > 0 && (
        <span className="row-icon" role="img" aria-label={todos} title={todos}>
          <ListChecks size={14} aria-hidden="true" />
          <span aria-hidden="true">{open}</span>
        </span>
      )}
      {item.summary !== null && (
        <span className="row-icon" role="img" aria-label={summary} title={summary}>
          {item.summary === "ai" ? (
            <Sparkles size={14} aria-hidden="true" />
          ) : (
            <AlignLeft size={14} aria-hidden="true" />
          )}
        </span>
      )}
    </span>
  );
}
