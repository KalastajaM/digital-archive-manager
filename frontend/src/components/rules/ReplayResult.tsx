/** The proof under a rule: what it would have done to the documents filed so far. */
import { createContext, useContext, useId, useState } from "react";
import type { Replay, RuleIn } from "../../api/client";
import { plural } from "../../format";
import { visible } from "../../text";
import { QuickLook, type QLFile } from "../QuickLook";

export const FAILS = "would fail: the pattern cannot be filled for it";

/** How many of the matches (lowest first) and of the near misses (highest first) the test
 * lists, as the backend picks them. */
const KEEP_MATCHED = 20;
const KEEP_NEAR = 10;

/** ``first`` and ``rest`` (a replay that went on after ``first.next_after``) as one: the
 * counts add up and the lists join, so the test never starts over. The documents marked
 * as from the sender are compared on the first call only. */
export function mergeReplay(first: Replay, rest: Replay): Replay {
  const scores = [...(first.scores ?? []), ...(rest.scores ?? [])];
  const matched = scores.filter((x) => x.matched).sort((a, b) => a.score - b.score || a.path.localeCompare(b.path));
  const near = scores.filter((x) => !x.matched).sort((a, b) => b.score - a.score || a.path.localeCompare(b.path));
  return {
    ...rest,
    matched: first.matched + rest.matched,
    same: first.same + rest.same,
    inbox: first.inbox + rest.inbox,
    checked: first.checked + rest.checked,
    different: [...first.different, ...rest.different],
    shadowed: [...first.shadowed, ...rest.shadowed],
    not_checked: [...(first.not_checked ?? []), ...(rest.not_checked ?? [])],
    marked: first.marked ?? rest.marked,
    scores: [...matched.slice(0, KEEP_MATCHED), ...near.slice(0, KEEP_NEAR)],
  };
}

/** Opens a document of the test result in the preview, with the tested rule drawn on it. */
const OpenDocument = createContext<(doc: { drive_id: string; path: string }) => void>(() => {});

/** A path of the test result: a button that opens the document. */
function DocButton({ driveId, path }: { driveId: string; path: string }) {
  const open = useContext(OpenDocument);
  if (!driveId) return <>{visible(path)}</>;
  return (
    <button
      type="button"
      className="link-button replay-path"
      title="Open this document with the rule's areas drawn on it"
      onClick={() => open({ drive_id: driveId, path })}
    >
      {visible(path)}
    </button>
  );
}

const qlFile = (d: { drive_id: string; path: string }): QLFile => {
  const name = d.path.slice(d.path.lastIndexOf("/") + 1);
  return { drive_id: d.drive_id, name, path: d.path, ext: name.includes(".") ? name.slice(name.lastIndexOf(".") + 1).toLowerCase() : null };
};

/** A list of documents (paths) that were not looked at, with the reason for each; closed
 * until asked for. */
function NotChecked({ items }: { items: Replay["not_checked"] }) {
  if (items.length === 0) return null;
  return (
    <details className="replay-not-checked">
      <summary>Not checked yet ({items.length})</summary>
      <ul className="replay-different">
        {items.map((n) => (
          <li key={n.path}>
            <DocButton driveId={n.drive_id} path={n.path} />
            {visible(`: ${n.reason}`)}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** The scores of a picture rule's test: the lowest of the documents it matched (listed as
 * "Matched") and the highest of the ones that came close but did not match, set apart so a
 * non-match is never read as a result. */
function Scores({ scores, needed }: { scores: Replay["scores"]; needed: number | null }) {
  if (!scores || scores.length === 0) return null;
  const matched = scores.filter((s) => s.matched);
  const near = scores.filter((s) => !s.matched);
  const row = (s: (typeof scores)[number]) => (
    <li key={`${s.matched}-${s.path}`}>
      <span className={s.matched ? "replay-score" : "replay-score replay-score-off"}>{s.score.toFixed(2)}</span>
      <DocButton driveId={s.drive_id} path={s.path} />
    </li>
  );
  const limit = near[0]?.needed ?? needed;
  return (
    <section className="replay-scores" aria-label="Picture scores">
      {matched.length > 0 && (
        <>
          <p className="replay-scores-title">
            Matched{needed !== null ? ` (${needed.toFixed(2)} is needed)` : ""}
          </p>
          <p className="hint">The lowest scores of the documents it matched</p>
          <ul aria-label="Matched documents">{matched.map(row)}</ul>
        </>
      )}
      {near.length > 0 && (
        <div className="replay-near">
          <p className="replay-scores-title">
            Close, but not matched{limit != null ? ` (below ${limit.toFixed(2)})` : ""}
          </p>
          <p className="hint">These were not matched. Only the ones within 0.15 of the score needed are listed.</p>
          <ul aria-label="Documents close to matching">{near.map(row)}</ul>
        </div>
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
  rule,
  onTestRest,
  restPending = false,
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
  /** The rule being tested: documents of the result open with its areas drawn on them. */
  rule?: RuleIn;
  /** Continue a test that stopped at its time budget, from where it stopped. */
  onTestRest?: () => void;
  restPending?: boolean;
}) {
  const id = useId();
  const [opened, setOpened] = useState<QLFile | null>(null);
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
    <OpenDocument.Provider value={(d) => setOpened(qlFile(d))}>
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
            <li key={d.drive_id}>
              <DocButton driveId={d.drive_id} path={d.path_now} />
              {visible(` → ${d.path_rule || FAILS}`)}
            </li>
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
                {marked.missed.map((m) => (
                  <li key={m.path}>
                    <DocButton driveId={m.drive_id} path={m.path} />
                  </li>
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
          {onTestRest && replay.next_after != null && (
            <>
              {" "}
              <button type="button" disabled={restPending} onClick={onTestRest}>
                {restPending ? "Testing the rest…" : "Test the rest"}
              </button>
            </>
          )}
        </p>
      )}
    </section>
    {opened && (
      <QuickLook
        files={[opened]}
        index={0}
        onIndex={() => {}}
        onClose={() => setOpened(null)}
        boxTool={rule ? { testRule: rule } : {}}
      />
    )}
    </OpenDocument.Provider>
  );
}
