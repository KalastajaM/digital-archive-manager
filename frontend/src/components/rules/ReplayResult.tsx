/** The proof under a rule: what it would have done to the documents filed so far. */
import { createContext, useContext, useId, useState } from "react";
import type { Replay, RuleIn } from "../../api/client";
import { groupDigits, plural } from "../../format";
import { visible } from "../../text";
import { QuickLook, type QLFile } from "../QuickLook";

export const FAILS = "would fail: the pattern cannot be filled for it";

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

/** The document the rule is made from, judged on its own: matches, does not (and why), or
 * cannot be told yet. It is not part of any count below it. */
function SourceLine({ source }: { source: NonNullable<Replay["source"]> }) {
  const doc = <DocButton driveId={source.drive_id} path={source.path} />;
  if (source.matched === true)
    return (
      <p className="replay-source" data-state="matched">
        This rule matches this document: {doc}
      </p>
    );
  if (source.matched === false)
    return (
      <p className="replay-source replay-source-off" data-state="not-matched">
        This rule does not match this document: {doc}
        <span className="replay-reason">{visible(` (${source.reason})`)}</span>
      </p>
    );
  return (
    <p className="replay-source replay-source-unknown" data-state="unknown">
      Cannot tell yet if this rule matches this document: {doc}
      <span className="replay-reason">{visible(` (${source.reason})`)}</span>
    </p>
  );
}

/** What each reason a document could not be judged means and what happens next, in plain
 * words. The reasons are the server's (``NotCheckedOut.reason``); one not listed is shown
 * as it comes. */
const REASONS: Record<string, { title: string; text: string }> = {
  "page 1 not read yet": {
    title: "Page 1 not read yet",
    text: "dam reads page 1 of these in the background; the test picks them up when they are read.",
  },
  "person unknown": {
    title: "Person unknown",
    text: "The address area does not say who these are for, so a rule that files by person cannot be judged. Set For on them, or add the people in Settings.",
  },
  "no OCR engine": {
    title: "No OCR engine",
    text: "Page 1 of these is a picture and no OCR engine is installed to read it. Install one, then test again.",
  },
  missing: {
    title: "Missing",
    text: "These files are not in the archive any more, so page 1 cannot be read.",
  },
  "page 1 took too long to read": {
    title: "Took too long",
    text: "Reading page 1 of these took too long, so dam gave up on them for now.",
  },
  "no picture of page 1 can be made": {
    title: "No picture of page 1",
    text: "No picture of page 1 can be made for these, so a picture area cannot be judged.",
  },
  "not indexed yet": {
    title: "Not read yet",
    text: "dam has not read these documents yet; it does in the background.",
  },
};

/** The documents that could not be judged yet, grouped by why, each group with a line on what
 * it means and what happens next; closed until asked for. */
function NotChecked({ items }: { items: Replay["not_checked"] }) {
  if (items.length === 0) return null;
  const groups = new Map<string, Replay["not_checked"]>();
  for (const n of items) groups.set(n.reason, [...(groups.get(n.reason) ?? []), n]);
  return (
    <details className="replay-not-checked">
      <summary>Could not be judged yet ({items.length})</summary>
      {[...groups].map(([reason, list]) => {
        const known = REASONS[reason];
        return (
          <div key={reason} className="replay-group" data-reason={reason}>
            <p className="replay-group-title">{visible(`${known?.title ?? reason} (${list.length})`)}</p>
            {known && <p className="hint">{known.text}</p>}
            <ul className="replay-different">
              {list.map((n) => (
                <li key={n.path}>
                  <DocButton driveId={n.drive_id} path={n.path} />
                </li>
              ))}
            </ul>
          </div>
        );
      })}
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

/** The state of the test the server runs in the background (``state`` is null before it has
 * answered): documents gone through of how many, and how many wait for page 1. */
export type Progress = {
  state: "running" | "waiting" | "done" | "stopped" | "error" | null;
  looked: number;
  total: number;
  waiting: number;
};

/** "Checked 1 240 of 10 875 documents…" with a Stop button while it runs; what it waits for
 * when all are looked at; where it stopped. Nothing once it is finished. */
function TestProgress({
  progress,
  onStop,
  onTestAgain,
  onReadNow,
  readingNow,
}: {
  progress: Progress;
  onStop?: () => void;
  onTestAgain?: () => void;
  onReadNow?: () => void;
  readingNow?: boolean;
}) {
  const { state, looked, total, waiting } = progress;
  const readNow =
    onReadNow && waiting > 0 && (state === "running" || state === "waiting") ? (
      <p className="replay-read-now">
        {readingNow ? (
          <span className="busy" role="status">
            Reading page 1 of these {groupDigits(waiting)} now, one at a time…
          </span>
        ) : (
          <button type="button" onClick={onReadNow}>
            Read page 1 of these {groupDigits(waiting)} now
          </button>
        )}
      </p>
    ) : null;
  if (state === "running")
    return (
      <>
        <p className="busy replay-progress" role="status">
          {total > 0 ? `Checked ${groupDigits(looked)} of ${groupDigits(total)} documents…` : "Getting ready to test…"}{" "}
          {onStop && (
            <button type="button" onClick={onStop}>
              Stop
            </button>
          )}
        </p>
        {readNow}
      </>
    );
  if (state === "waiting")
    return (
      <>
        <p className="busy replay-progress" role="status">
          Checked all {groupDigits(total)} documents. Waiting for page 1 of {groupDigits(waiting)}…{" "}
          {onStop && (
            <button type="button" onClick={onStop}>
              Stop
            </button>
          )}
        </p>
        {readNow}
      </>
    );
  if (state === "stopped")
    return (
      <p className="hint replay-progress">
        Stopped at {groupDigits(looked)} of {groupDigits(total)} documents.{" "}
        {onTestAgain && (
          <button type="button" onClick={onTestAgain}>
            Test again
          </button>
        )}
      </p>
    );
  return null;
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
  progress,
  onStop,
  onTestAgain,
  onReadNow,
  readingNow,
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
  /** How far the background test has come. */
  progress?: Progress;
  /** End the test where it is (what it found so far stays). */
  onStop?: () => void;
  /** Test again from the start (after a stop). */
  onTestAgain?: () => void;
  /** Have page 1 of the documents the test waits for read now. */
  onReadNow?: () => void;
  readingNow?: boolean;
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
      {pending && <p className="hint replay-stale">Testing the rule as it is now. The result below is of the rule before your last change.</p>}
      {replay.source && <SourceLine source={replay.source} />}
      {replay.matched === 0 ? (
        <p className="hint">
          {notChecked.length > 0
            ? `${plural(notChecked.length, "document")} could not be judged yet, so no filed document is known to match. See below why.`
            : reading > 0
              ? "No filed document could be judged yet: page 1 of some is still being read."
              : "No filed document matches this rule yet, so it could not be tested against them."}
        </p>
      ) : (
        <p>
          Matches {plural(replay.matched, "document")} you filed before: {replay.same} would land exactly where they
          are.
          {notChecked.length > 0 && ` (${plural(notChecked.length, "document")} could not be judged yet)`}
        </p>
      )}
      {reading > 0 && !progress && (
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
      {progress && (
        <TestProgress
          progress={progress}
          onStop={onStop}
          onTestAgain={onTestAgain}
          onReadNow={onReadNow}
          readingNow={readingNow}
        />
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
