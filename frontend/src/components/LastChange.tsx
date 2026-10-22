import { useId } from "react";
import type { CollectionChange } from "../api/client";
import { visible } from "../text";
import { changeLines } from "./collectionText";
import { collapseLinkSwaps, PlanList } from "./PlanPreview";

type Ops = NonNullable<CollectionChange["batch"]>["done"];

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The ops of a change in a few words: "1 link replaced, 2 folders created". */
export function summarizeOps(ops: Ops): string {
  const n = { replaced: 0, added: 0, removed: 0, renamed: 0, moved: 0, made: 0, gone: 0 };
  for (const item of collapseLinkSwaps(ops)) {
    if ("kept" in item) n.replaced++;
    else
      switch (item.op.kind) {
        case "symlink": n.added++; break;
        case "unlink_symlink": n.removed++; break;
        case "rename": n.renamed++; break;
        case "move": case "quarantine": n.moved++; break;
        case "mkdir": n.made++; break;
        case "remove_empty_dir": n.gone++; break;
      }
  }
  return [
    n.replaced && `${count(n.replaced, "link", "links")} replaced`,
    n.added && `${count(n.added, "link", "links")} added`,
    n.removed && `${count(n.removed, "link", "links")} removed`,
    n.renamed && `${count(n.renamed, "item", "items")} renamed`,
    n.moved && `${count(n.moved, "item", "items")} moved`,
    n.made && `${count(n.made, "folder", "folders")} created`,
    n.gone && `${count(n.gone, "empty folder", "empty folders")} removed`,
  ]
    .filter(Boolean)
    .join(", ");
}

/** "Rename: what happened in ##. Ongoing (recreated 3 links)" -> the folder and the note. */
const TITLE = /^.*?: what happened in (.*?)(\s*\(.*\))?$/;

/** What actually happened in ##. Ongoing after a collection change: the ops of the
 * batch that ran (never a preview), its problems and the collection's Ongoing status. */
export function LastChange({
  title,
  result,
  onDismiss,
  onUndo,
}: {
  title: string;
  result: Pick<CollectionChange, "problems" | "batch" | "ongoing_status">;
  /** When given, a Dismiss button hides the result (Activity keeps the record). */
  onDismiss?: () => void;
  /** When given, an Undo button undoes the batch this result shows. */
  onUndo?: () => void;
}) {
  const headingId = useId();
  const { problems, status } = changeLines(result);
  const ops = result.batch?.done ?? [];
  const parsed = TITLE.exec(title);
  const root = parsed?.[1] ?? "##. Ongoing";
  const heading = parsed ? `What changed in ${root}${parsed[2] ?? ""}` : title;
  const summary = summarizeOps(ops);
  return (
    <section className="plan-preview" aria-labelledby={headingId}>
      <div className="plan-preview-head">
        <h3 id={headingId}>{visible(heading)}</h3>
        {onUndo && (
          <button type="button" className="link-button" onClick={onUndo}>
            Undo
          </button>
        )}
        {onDismiss && (
          <button type="button" className="link-button" onClick={onDismiss}>
            Dismiss
          </button>
        )}
      </div>
      <p>{visible(summary ? `Updated ${root}: ${summary}` : `Nothing needed to change in ${root}.`)}</p>
      {ops.length > 0 && (
        <details className="change-details">
          <summary>Details</summary>
          <PlanList ops={ops} />
        </details>
      )}
      {problems.map((p, i) => (
        <p key={i} className="notice">
          {visible(p)}
        </p>
      ))}
      {status && <p className="notice">{visible(status)}</p>}
    </section>
  );
}
