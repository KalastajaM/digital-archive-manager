import type { JournalEntry, ResolvedOp } from "../api/client";
import { visible } from "../text";
import { KIND_LABEL, SINGLE_PATH } from "./PlanPreview";
import { MarkIcons } from "./MarkIcons";
import { browseInto, browseTo, ShowInBrowse } from "./maintenance/ShowInBrowse";
import { Tag, type TagTone } from "./ui/Tag";

/** How each journal state reads: a done op needs no tag (the batch says it). */
const STATE_TONE: Record<string, TagTone> = {
  planned: "red",
  failed: "red",
  unverified: "orange",
  undone: "grey",
};

const folderOf = (path: string) => path.slice(0, Math.max(0, path.lastIndexOf("/")));

/** Where the op's file is now, when the journal's path is stale (moved on, marked for
 * deletion or gone since), and Show in Browse wherever the file still is. Nothing for
 * an op that names no file (and for recovery rows, which carry no ``file_now``). */
function FileNow({ now }: { now: NonNullable<JournalEntry["file_now"]> }) {
  if (now.state === "missing" || now.path === null) {
    return (
      <span className="journal-now" title="Deleted, or moved outside dam, since this change">
        no longer in the archive
      </span>
    );
  }
  const to = now.is_dir || now.drive_id === null ? browseInto(now.path) : browseTo(now.path, now.drive_id);
  return (
    <>
      <span className="journal-show">
        <ShowInBrowse to={to} />
      </span>
      {now.state === "moved" && (
        <span className="journal-now">
          now at <code>{visible(now.path)}</code>
        </span>
      )}
      {now.state === "to_delete" && (
        <span className="journal-now">
          marked for deletion since, now in <code>{visible(folderOf(now.path))}</code>
        </span>
      )}
    </>
  );
}

/** Journal rows as "Move src → dst" (a folder made or removed, a link removed: its path
 * alone), with a tag when the op is not simply done, its error if any and, in Activity,
 * where its file is now (``FileNow``). */
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
            {e.file_now && <FileNow now={e.file_now} />}
            {e.error && <span className="plan-note journal-error">{visible(e.error)}</span>}
          </li>
        );
      })}
    </ol>
  );
}
