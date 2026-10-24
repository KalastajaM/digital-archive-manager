/** The proof under a rule: what it would have done to the documents filed so far. */
import { useId } from "react";
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

/** The scores of a picture rule's replay: the lowest of the documents it matched and the
 * highest of the ones it did not, so the gap between them (or the lack of one) can be seen. */
function Scores({ scores, needed }: { scores: Replay["scores"]; needed: number | null }) {
  if (!scores || scores.length === 0) return null;
  const matched = scores.filter((s) => s.matched);
  const others = scores.filter((s) => !s.matched);
  const row = (s: (typeof scores)[number]) => (
    <li key={`${s.matched}-${s.path}`}>
      <span className={s.matched ? "replay-score" : "replay-score replay-score-off"}>{s.score.toFixed(2)}</span>
      {visible(s.path)}
    </li>
  );
  return (
    <section className="replay-scores" aria-label="Picture scores">
      <p>
        How well the picture matched{needed !== null ? ` (${needed.toFixed(2)} is needed)` : ""}:
      </p>
      {matched.length > 0 && (
        <>
          <p className="hint">Lowest of the documents it matched</p>
          <ul aria-label="Matched documents">{matched.map(row)}</ul>
        </>
      )}
      {others.length > 0 && (
        <>
          <p className="hint">Highest of the documents it did not match</p>
          <ul aria-label="Documents not matched">{others.map(row)}</ul>
        </>
      )}
    </section>
  );
}

export function ReplayResult({
  replay,
  before = null,
  sender = null,
  needed = null,
  pending = false,
  error = null,
  onRetry,
}: {
  replay: Replay | undefined;
  /** The same rule before the change being made: how it did, to compare with. */
  before?: Replay | null;
  /** The rule's sender: with it, the documents marked as from that sender are compared. */
  sender?: string | null;
  /** The lowest score a picture area of the rule needs (shown with the scores). */
  needed?: number | null;
  pending?: boolean;
  error?: string | null;
  onRetry?: () => void;
}) {
  const id = useId();
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
    <section className="replay-result" aria-labelledby={`${id}-title`} aria-busy={pending}>
      <h4 id={`${id}-title`}>Test against your filed documents</h4>
      {replay.matched === 0 ? (
        <p className="hint">
          {notChecked.length > 0 || reading > 0
            ? `Not tested yet: ${notChecked.length} not checked yet`
            : "No filed document matches this rule yet, so it could not be tested against them."}
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
      {before && (
        <p className="hint">
          Before the change it matched {plural(before.matched, "document")}
          {before.marked && before.marked.total > 0 ? `, and found ${before.marked.found} of the ${before.marked.total} you set as from ${sender ?? "this sender"}` : ""}.
        </p>
      )}
      <Scores scores={replay.scores ?? []} needed={needed} />
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
