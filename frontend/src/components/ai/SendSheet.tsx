/** "What will be sent" (spec §2.1): the task, the model, the worst-case cost, this
 * month's spend against the budget, and the exact text, before anything goes out. Send
 * runs the prepared token, so what is shown is what is sent. Arming as ``ConfirmPlan``:
 * Cancel has the focus, Cmd+Enter sends only after ``CONFIRM_KEY_DELAY_MS`` and a key
 * release. A result from earlier is shown at once ("from earlier", free), with Ask
 * again to send anew. */
import type { AIPrepared, AIStatus } from "../../api/client";
import { visible, visibleText } from "../../text";
import { useArmedConfirm } from "../PlanPreview";
import { euro } from "../../format";
import { Sheet } from "../ui/Sheet";
import { Tag } from "../ui/Tag";
import { AIWait, secondsText } from "./AIWait";

/** One value of an answer, as plain text (hidden characters shown). */
function plain(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return visibleText(value);
  if (Array.isArray(value)) return value.map(plain).join(", ") || "—";
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    return entries.length ? entries.map(([k, v]) => `${visible(k)}: ${plain(v)}`).join("; ") : "—";
  }
  return String(value);
}

/** An answer's fields, as text: never markup, links or actions (spec §2.8). */
export function ResultView({ data }: { data: Record<string, unknown> }) {
  const shown = Object.entries(data).filter(([k]) => k !== "confidence" && k !== "rejected");
  return (
    <dl className="ai-result">
      {shown.map(([k, v]) => (
        <div key={k}>
          <dt>{visible(k.replace(/_/g, " "))}</dt>
          <dd>{plain(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** This month's spend against the budget (and this call's worst case), as a meter. */
export function Budget({ status, estimate }: { status: AIStatus | undefined; estimate: number }) {
  if (!status) return null;
  const { month_spend_eur: spent, budget_eur: budget } = status;
  const pct = (n: number) => `${budget > 0 ? Math.min(100, Math.max(0, (n / budget) * 100)) : 100}%`;
  return (
    <div className="ai-budget">
      <div
        className="ai-budget-bar"
        role="meter"
        aria-label="This month's AI spend"
        aria-valuemin={0}
        aria-valuemax={budget}
        aria-valuenow={spent}
        aria-valuetext={`${euro(spent)} of ${euro(budget)}`}
      >
        <span className="ai-budget-spent" style={{ width: pct(spent) }} />
        <span className="ai-budget-call" style={{ width: pct(Math.min(estimate, Math.max(0, budget - spent))) }} />
      </div>
      <p className="hint">
        {euro(spent)} of {euro(budget)} this month
      </p>
    </div>
  );
}

type Props = {
  /** The task's name ("Suggest filing"). */
  task: string;
  /** The button that opened the sheet (named in the note about closing it). */
  askButton: string;
  prepared: AIPrepared;
  status: AIStatus | undefined;
  busy: boolean;
  /** The text is out (not a free "Use this"): Cancel becomes "Close (already sent)". */
  sending: boolean;
  /** Why the last send failed; the token is then spent. */
  error: string | null;
  /** Why an Ask again / Prepare again failed (the shown token stays usable). */
  prepareError: string | null;
  onSend: () => void;
  onCancel: () => void;
  onAskAgain: () => void;
  onPrepareAgain: () => void;
};

export function SendSheet({
  task,
  askButton,
  prepared,
  status,
  busy,
  sending,
  error,
  prepareError,
  onSend,
  onCancel,
  onAskAgain,
  onPrepareAgain,
}: Props) {
  const cached = prepared.cached;
  const spent = error !== null;
  const canSend = prepared.blocked === null && !spent && !busy;
  const armed = useArmedConfirm({ onConfirm: () => canSend && onSend(), onCancel, busy });
  return (
    <Sheet
      open
      className="confirm ai-sheet"
      title="What will be sent"
      onClose={onCancel}
      onKeyDown={armed.onKeyDown}
      footer={
        <>
          <button ref={armed.cancelRef} type="button" onClick={onCancel} autoFocus>
            {sending ? "Close (already sent)" : "Cancel"}
          </button>
          {spent ? (
            <button type="button" className="primary" onClick={onPrepareAgain} disabled={busy}>
              Prepare again
            </button>
          ) : cached ? (
            <>
              <button type="button" onClick={onAskAgain} disabled={busy}>
                Ask again
              </button>
              <button type="button" className="primary" onClick={onSend} disabled={busy}>
                Use this
              </button>
            </>
          ) : (
            <button type="button" className="primary" onClick={onSend} disabled={!canSend}>
              {busy ? "Waiting for Claude…" : "Send"}
            </button>
          )}
        </>
      }
    >
      <dl className="ai-facts">
        <div>
          <dt>Task</dt>
          <dd>{task}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd>
            <code>{visible(prepared.model)}</code>
          </dd>
        </div>
        <div>
          <dt>Cost</dt>
          <dd>
            {cached
              ? "nothing (from earlier)"
              : prepared.blocked !== null
                ? "nothing (not sent)"
                : `at most ${euro(prepared.estimate_eur)}`}
          </dd>
        </div>
        {!cached && prepared.blocked === null && (
          <div>
            <dt>Gives up after</dt>
            <dd>{secondsText(prepared.timeout_s)}</dd>
          </div>
        )}
      </dl>
      <Budget status={status} estimate={cached ? 0 : prepared.estimate_eur} />
      {sending && busy && <AIWait model={prepared.model} limitS={prepared.timeout_s} />}
      {sending && (
        <p className="notice">
          Sent. You can close this: the answer is paid for and is saved when it arrives, and closing does not stop it.
          Press “{askButton}” again and choose “Use this” to see it, at no extra cost.
        </p>
      )}
      {prepareError !== null && (
        <p className="error" role="alert">
          {visible(prepareError)}
        </p>
      )}
      {error !== null && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
      {prepared.blocked !== null && (
        <p className="error" role="alert">
          Can’t send: {visible(prepared.blocked)}
        </p>
      )}
      {cached ? (
        <section className="ai-cached" aria-label="Answer from earlier">
          <p>
            <Tag tone="blue">from earlier</Tag> An answer for this same text was saved: using it costs nothing.
            Ask again sends the text anew.
          </p>
          <ResultView data={cached} />
        </section>
      ) : prepared.payload_text ? (
        <>
          <h3 className="ai-payload-head">The text</h3>
          <pre className="ai-payload" aria-label="Text that will be sent" tabIndex={0}>
            {visibleText(prepared.payload_text)}
          </pre>
          {prepared.system && (
            <details className="ai-system">
              <summary>Instructions sent with it</summary>
              <pre className="ai-payload">{visibleText(prepared.system)}</pre>
            </details>
          )}
        </>
      ) : (
        <p>Nothing will be sent.</p>
      )}
      {prepared.notes.length > 0 && (
        <ul className="ai-notes" aria-label="Left out">
          {prepared.notes.map((note) => (
            <li key={note} className="hint">
              {visible(note)}
            </li>
          ))}
        </ul>
      )}
    </Sheet>
  );
}
