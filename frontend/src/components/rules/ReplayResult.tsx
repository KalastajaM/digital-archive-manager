/** The proof under a rule: what it would have done to the documents filed so far. */
import type { Replay } from "../../api/client";
import { plural } from "../../format";
import { visible } from "../../text";

export const FAILS = "would fail: the pattern cannot be filled for it";

export function ReplayResult({
  replay,
  pending = false,
  error = null,
  onRetry,
}: {
  replay: Replay | undefined;
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
  const shadowed = new Map<string, number>();
  for (const s of replay.shadowed) shadowed.set(s.rule_id, (shadowed.get(s.rule_id) ?? 0) + 1);
  return (
    <section className="replay-result" aria-label="Test result" aria-busy={pending}>
      {replay.matched === 0 ? (
        <p className="hint">Not tested yet: no filed document matches it</p>
      ) : (
        <p>
          Matches {plural(replay.matched, "document")} you filed before: {replay.same} would land exactly where they
          are.
        </p>
      )}
      {replay.different.length > 0 && (
        <ul className="replay-different">
          {replay.different.map((d) => (
            <li key={d.drive_id}>{visible(`${d.path_now} → ${d.path_rule || FAILS}`)}</li>
          ))}
        </ul>
      )}
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
