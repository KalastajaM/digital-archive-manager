/** One file's summary box (spec §3, §7.5): the summary the user wrote if it is current,
 * otherwise the AI one ("outdated (the file changed)" when the file changed since).
 * "Summarize with AI" opens the "What will be sent" sheet; the answer is only a
 * proposal until "Use this summary" saves it. A current summary the user wrote is never
 * replaced without the confirm sheet. Edit saves the user's own text. */
import { Sparkles } from "lucide-react";
import { useId, useRef, useState } from "react";
import {
  ApiError,
  type DocumentSummary,
  errorText,
  type FileSummaries,
  type SavedSummary,
  useFileSummary,
  usePutFileSummary,
} from "../../api/client";
import { visible } from "../../text";
import { ConfirmPlan } from "../PlanPreview";
import { Tag } from "../ui/Tag";
import { euro } from "../../format";
import { AIHint, type AIResultInfo, useAISend, useAIState } from "./useAI";

export const REPLACE_QUESTION = "Replace your summary with the AI one? Your text is not kept.";
export const OUTDATED = "outdated (the file changed)";

type Shown = { source: "ai" | "user"; saved: SavedSummary } | null;

/** What the box shows: the user's own summary while current, else the AI one, else an
 * outdated summary of the user's. */
export function shownSummary(s: FileSummaries | undefined): Shown {
  if (!s) return null;
  if (s.user && !s.user.outdated) return { source: "user", saved: s.user };
  if (s.ai) return { source: "ai", saved: s.ai };
  if (s.user) return { source: "user", saved: s.user };
  return null;
}

function Facts({ facts, label }: { facts: string[]; label: string }) {
  if (facts.length === 0) return null;
  return (
    <ul className="summary-facts" aria-label={label}>
      {facts.map((f, i) => (
        <li key={i}>{visible(f)}</li>
      ))}
    </ul>
  );
}

type Proposal = { data: DocumentSummary; info: AIResultInfo };

export function SummaryBox({ driveId, heading = "Summary" }: { driveId: string; heading?: string }) {
  const headingId = useId();
  const editId = useId();
  const query = useFileSummary(driveId);
  const save = usePutFileSummary();
  const ai = useAIState();
  const [held, setProposal] = useState<Proposal | null>(null);
  // AI switched off: nothing AI is shown (the proposal is back if it is switched on)
  const proposal = ai.on ? held : null;
  const [confirming, setConfirming] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false); // a double click saves once
  const send = useAISend<DocumentSummary>("summarize-document", (data, info) => {
    setError(null);
    setProposal({ data, info });
  });

  const shown = shownSummary(query.data);
  const userCurrent = !!query.data?.user && !query.data.user.outdated;

  const guarded = async (work: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null);
    try {
      await work();
    } catch (e) {
      setError(errorText(e));
    } finally {
      inFlight.current = false;
    }
  };

  const apply = (replace: boolean) =>
    guarded(async () => {
      if (!proposal) return;
      try {
        await save.mutateAsync({
          driveId,
          source: "ai",
          summary: proposal.data.summary,
          key_facts: proposal.data.key_facts,
          replace,
        });
      } catch (e) {
        // the user wrote a summary meanwhile: ask, never overwrite
        if (e instanceof ApiError && e.status === 409 && !replace) {
          setConfirming(true);
          return;
        }
        setConfirming(false); // the error shows on the box, as on a collection
        throw e;
      }
      setConfirming(false);
      setProposal(null);
    });

  const saveOwn = (text: string) =>
    guarded(async () => {
      await save.mutateAsync({
        driveId,
        source: "user",
        summary: text,
        key_facts: shown?.source === "user" ? shown.saved.key_facts : [],
        replace: true,
      });
      setEditing(null);
    });

  const askAI = () => send.ask({ drive_id: driveId });

  return (
    <section className="summary-box" aria-labelledby={headingId}>
      <header className="summary-box-head">
        <h3 id={headingId}>{heading}</h3>
        {shown && (
          <Tag tone={shown.source === "ai" ? "blue" : "grey"}>{shown.source === "ai" ? "by AI" : "yours"}</Tag>
        )}
      </header>
      {query.isError && (
        <p className="error" role="alert">
          Could not load the summary. {visible(errorText(query.error))}
        </p>
      )}
      {editing !== null ? (
        <form
          className="summary-edit"
          onSubmit={(e) => {
            e.preventDefault();
            void saveOwn(editing);
          }}
        >
          <label htmlFor={editId} className="visually-hidden">
            Your summary
          </label>
          <textarea
            id={editId}
            rows={3}
            maxLength={2000}
            value={editing}
            autoFocus
            onChange={(e) => setEditing(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                setEditing(null);
              }
            }}
          />
          <div className="actions">
            <button type="button" onClick={() => setEditing(null)}>
              Cancel
            </button>
            <button type="submit" className="primary" disabled={save.isPending || !editing.trim()}>
              Save
            </button>
          </div>
        </form>
      ) : shown ? (
        <>
          <p className="summary-text">{visible(shown.saved.summary)}</p>
          <Facts facts={shown.saved.key_facts} label="Key facts" />
          {shown.saved.outdated && <p className="hint summary-outdated">{OUTDATED}</p>}
        </>
      ) : (
        query.data && <p className="hint">No summary yet.</p>
      )}
      {proposal && (
        <section className="ai-summary summary-proposal" aria-label="AI summary">
          <h4>
            AI summary{" "}
            {proposal.info.cached ? (
              <Tag tone="blue">from earlier</Tag>
            ) : (
              <span className="hint">· {euro(proposal.info.costEur)}</span>
            )}
          </h4>
          <p>{visible(proposal.data.summary)}</p>
          <Facts facts={proposal.data.key_facts} label="Key facts (AI)" />
          <div className="actions">
            <button type="button" disabled={save.isPending} onClick={() => setProposal(null)}>
              Discard
            </button>
            <button
              type="button"
              className="primary"
              disabled={save.isPending}
              onClick={() => (userCurrent ? setConfirming(true) : void apply(false))}
            >
              Use this summary
            </button>
          </div>
        </section>
      )}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
      {editing === null && (
        <div className="actions summary-actions">
          {ai.on && !proposal && (
            <button type="button" className="ai-action" disabled={send.busy} onClick={askAI}>
              <Sparkles size={14} aria-hidden="true" />
              {shown?.saved.outdated ? "Summarize again…" : "Summarize with AI…"}
            </button>
          )}
          {query.data && (
            <button
              type="button"
              onClick={() => setEditing(shown?.saved.summary ?? "")}
            >
              {shown ? "Edit" : "Write a summary"}
            </button>
          )}
        </div>
      )}
      <AIHint what="to summarize" />
      {send.sheet}
      {confirming && proposal && (
        <ConfirmPlan
          planKey={`replace-summary-${driveId}`}
          title="Replace your summary?"
          ops={[]}
          busy={save.isPending}
          confirmLabel="Replace"
          onConfirm={() => void apply(true)}
          onCancel={() => setConfirming(false)}
        >
          <p>{REPLACE_QUESTION}</p>
        </ConfirmPlan>
      )}
    </section>
  );
}

