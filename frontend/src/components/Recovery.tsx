import { CircleCheck, LifeBuoy } from "lucide-react";
import { createContext, type ReactNode, useContext, useRef, useState } from "react";
import { errorText, type JournalEntry, type RecoveryResult, useRecovery } from "../api/client";
import { visible } from "../text";
import { JournalList } from "./JournalList";
import { ConfirmPlan } from "./PlanPreview";

/** What POST /api/recovery does (dam.ops.undo.recover): it only reads the disk. */
export const RECOVERY_EXPLAINED =
  "Recovery checks the disk for each interrupted operation and records in the journal " +
  "whether it happened (done) or not (failed, or “needs manual check” when the disk " +
  "does not say). For operations that did happen it also updates the index to the new " +
  "path. It moves, renames or deletes no files.";

function RecoveryReport({ result }: { result: RecoveryResult }) {
  if (result.entries.length === 0 && result.index_errors.length === 0) {
    return (
      <p className="recovery-done">
        <CircleCheck size={14} aria-hidden="true" /> Nothing to recover.
      </p>
    );
  }
  return (
    <ul className="recovery-report" aria-label="Recovery result">
      {result.entries.map((e) => (
        <li key={e.id} className={`recovery-row recovery-${e.state}`}>
          <span className="recovery-what">
            {e.state} {e.kind}
          </span>{" "}
          <code>{visible(e.src ?? "")}</code> → <code>{visible(e.dst ?? "")}</code>
          {e.error && <span className="plan-note"> ({visible(e.error)})</span>}
        </li>
      ))}
      {result.index_errors.map((msg, i) => (
        <li key={`index-${i}`} className="recovery-row recovery-failed">
          Index error: {visible(msg)}
        </li>
      ))}
    </ul>
  );
}

type RecoveryState = {
  /** POST /api/recovery; a second call while one runs is ignored. */
  run: () => Promise<void>;
  pending: boolean;
  data: RecoveryResult | undefined;
  error: Error | null;
};

const RecoveryContext = createContext<RecoveryState | null>(null);

/** One recovery request and its result for the whole app: the banner and the Activity
 * panel share them, so the result survives navigation and only one run is in flight. */
export function RecoveryProvider({ children }: { children: ReactNode }) {
  const recovery = useRecovery();
  const running = useRef(false);
  const run = async () => {
    if (running.current) return;
    running.current = true;
    try {
      await recovery.mutateAsync();
    } catch {
      // shown from ``error``
    } finally {
      running.current = false;
    }
  };
  return (
    <RecoveryContext.Provider
      value={{ run, pending: recovery.isPending, data: recovery.data, error: recovery.error }}
    >
      {children}
    </RecoveryContext.Provider>
  );
}

function useSharedRecovery(): RecoveryState {
  const state = useContext(RecoveryContext);
  if (!state) throw new Error("RecoveryPanel needs a <RecoveryProvider>");
  return state;
}

/** Interrupted operations and **Run recovery** (behind a confirm). Renders nothing when
 * none are pending and no result is left to show. */
export function RecoveryPanel({ count, entries }: { count: number; entries?: JournalEntry[] }) {
  const recovery = useSharedRecovery();
  const [asking, setAsking] = useState(false);
  const confirm = async () => {
    await recovery.run();
    setAsking(false);
  };

  if (count === 0 && !recovery.data && !recovery.error) return null;
  return (
    <section className={count > 0 ? "banner recovery" : "banner recovery recovery-settled"} aria-label="Recovery">
      <LifeBuoy className="banner-icon" size={16} aria-hidden="true" />
      <div className="recovery-main">
        {count > 0 ? (
          <p>
            <strong>
              {count} interrupted operation{count === 1 ? "" : "s"} found.
            </strong>{" "}
            Recovery reads the disk to settle them; it never changes files.
          </p>
        ) : (
          <p>
            <strong>Recovery finished.</strong>
          </p>
        )}
        {entries && entries.length > 0 && <JournalList entries={entries} label="Interrupted operations" />}
        {recovery.error && (
          <p className="error" role="alert">
            {visible(errorText(recovery.error))}
          </p>
        )}
        {recovery.data && <RecoveryReport result={recovery.data} />}
      </div>
      {count > 0 && (
        <button type="button" onClick={() => setAsking(true)} disabled={recovery.pending}>
          Run recovery
        </button>
      )}
      {asking && (
        <ConfirmPlan
          planKey="recovery"
          title="Run recovery?"
          confirmLabel="Run recovery"
          ops={[]}
          busy={recovery.pending}
          onConfirm={() => void confirm()}
          onCancel={() => setAsking(false)}
        >
          <p>{RECOVERY_EXPLAINED}</p>
          {entries && entries.length > 0 && <JournalList entries={entries} />}
        </ConfirmPlan>
      )}
    </section>
  );
}
