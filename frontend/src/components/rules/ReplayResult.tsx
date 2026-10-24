/** The proof under a rule: what it would have done to the documents filed so far. */
import type { Replay } from "../../api/client";
import { plural } from "../../format";
import { visible } from "../../text";

export const FAILS = "would fail: the pattern cannot be filled for it";

/** A list of documents (paths) that were not looked at, with the reason for each; closed
 * until asked for. */
function NotChecked({ items }: { items: Replay["not_checked"] }) {
  if (items.length === 0) return null;
  return (
    <details className="replay-not-checked">
      <summary>Not checked yet ({items.length})</summary>
      <ul className="replay-different">
        {items.map((n) => (
          <li key={n.path}>{visible(`${n.path}: ${n.reason}`)}</li>
        ))}
      </ul>
    </details>
  );
}

export function ReplayResult({
  replay,
  sender = null,
  pending = false,
  error = null,
  onRetry,
}: {
  replay: Replay | undefined;
  /** The rule's sender: with it, the documents marked as from that sender are compared. */
  sender?: string | null;
  pending?: boolean;
  error?: string | null;
  onRetry?: () => void;
}) {
  if (error)
    return (
      <div className="error" role="alert">
        <p>{visible(error)}</p>
        {onRetry && <button type="button" onClick={onRetry}>Try again</button>}
      </div>
    );
  if (!replay) return <p className="busy" role="status">Testing against your filed documents…</p>;
  const notChecked = replay.not_checked ?? [];
  const reading = replay.reading ?? 0;
  const marked = replay.marked ?? null;
  const shadowed = new Map<string, number>();
  for (const s of replay.shadowed) shadowed.set(s.rule_id, (shadowed.get(s.rule_id) ?? 0) + 1);
  return (
    <section className="replay-result" aria-label="Test result" aria-busy={pending}>
      {replay.matched === 0 ? (
        <p className="hint">
          Not tested yet:{" "}
          {notChecked.length > 0 || reading > 0
            ? `${notChecked.length} not checked yet`
            : "no filed document matches it"}
        </p>
      ) : (
        <p>
          Matches {plural(replay.matched, "document")} you filed before: {replay.same} would land exactly where they
          are.
          {notChecked.length > 0 && ` (${notChecked.length} not checked yet)`}
        </p>
      )}
      {reading > 0 && (
        <p className="busy" role="status">
          Reading page 1 of {plural(reading, "document")}…
        </p>
      )}
      {replay.different.length > 0 && (
        <ul className="replay-different">
          {replay.different.map((d) => (
            <li key={d.drive_id}>{visible(`${d.path_now} → ${d.path_rule || FAILS}`)}</li>
          ))}
        </ul>
      )}
      {marked && marked.total > 0 && (
        <>
          <p>
            Finds {marked.found} of the {marked.total} documents you set as from {visible(sender ?? "this sender")}.
          </p>
          {marked.missed.length > 0 && (
            <>
              <p className="hint">It misses:</p>
              <ul className="replay-different replay-missed">
                {marked.missed.map((path) => (
                  <li key={path}>{visible(path)}</li>
                ))}
              </ul>
            </>
          )}
          <NotChecked items={marked.not_checked} />
        </>
      )}
      <NotChecked items={notChecked} />
      {[...shadowed].map(([id, n]) => (
        <p key={id} className="hint">
          For {n} of them rule {visible(id)} comes first
        </p>
      ))}
      {replay.inbox > 0 && <p>It also catches {plural(replay.inbox, "document")} in the inbox now.</p>}
      {replay.truncated && (
        <p className="hint">
          Checked {replay.checked} of {replay.total} documents
        </p>
      )}
    </section>
  );
}
