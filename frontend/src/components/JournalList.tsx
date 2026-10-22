import type { JournalEntry, ResolvedOp } from "../api/client";
import { visible } from "../text";
import { KIND_LABEL, SINGLE_PATH } from "./PlanPreview";
import { MarkIcons } from "./MarkIcons";
import { Tag, type TagTone } from "./ui/Tag";

/** How each journal state reads: a done op needs no tag (the batch says it). */
const STATE_TONE: Record<string, TagTone> = {
  planned: "red",
  failed: "red",
  unverified: "orange",
  undone: "grey",
};

/** Journal rows as "Move src → dst" (a folder made or removed, a link removed: its path
 * alone), with a tag when the op is not simply done, and its error if any. */
export function JournalList({ entries, label }: { entries: JournalEntry[]; label?: string }) {
  return (
    <ol className="plan journal" aria-label={label}>
      {entries.map((e) => {
        const kind = e.kind as ResolvedOp["kind"];
        const single = SINGLE_PATH.has(kind) || e.src === null;
        return (
          <li key={e.id} className={`plan-op journal-op journal-${e.state}`}>
            <span className="plan-kind">{KIND_LABEL[kind] ?? e.kind}</span>
            <span className="journal-paths">
              {single ? (
                <>
                  {/* the journal keeps a made folder in dst, a removed one or a removed
                   * link in src (and the link's old target in dst) */}
                  <code>{visible((kind === "mkdir" ? e.dst : e.src) || e.dst || "")}</code>
                  {kind === "unlink_symlink" && e.dst && (
                    <span className="journal-target"> (was a link to {visible(e.dst)})</span>
                  )}
                </>
              ) : (
                <>
                  <code>{visible(e.src ?? "")}</code>
                  <span className="journal-arrow" aria-hidden="true">
                    {" "}
                    →{" "}
                  </span>
                  <code>{visible(e.dst ?? "")}</code>
                </>
              )}
              <MarkIcons marks={e.marks} />
            </span>
            {e.state !== "done" && (
              <Tag tone={STATE_TONE[e.state] ?? "grey"} className={`op-state op-${e.state}`}>
                {e.state}
              </Tag>
            )}
            {e.error && <span className="plan-note journal-error">{visible(e.error)}</span>}
          </li>
        );
      })}
    </ol>
  );
}
