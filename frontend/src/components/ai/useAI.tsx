/** The AI hooks for screens (spec §2): whether AI is on, the "Turn on AI" hint, and
 * ``useAISend``, which prepares a task, shows the "What will be sent" sheet and sends
 * only on its Send. Nothing is ever sent without that sheet. */
import { type ReactNode, useRef, useState } from "react";
import {
  type AIPrepared,
  type AITask,
  errorText,
  useAIPrepare,
  useAIRun,
  useAIStatus,
} from "../../api/client";
import { visible } from "../../text";
import { useToast } from "../Toasts";
import { SendSheet } from "./SendSheet";

export const TASK_LABEL: Record<AITask, string> = {
  "suggest-filing": "Suggest filing",
  "summarize-document": "Summarize document",
  "summarize-collection": "Summarize collection",
  "ask-archive": "Ask the archive",
};

/** The button that starts each task, as the sheet's "press it again" note names it. */
const ASK_BUTTON: Record<AITask, string> = {
  "suggest-filing": "Ask AI",
  "summarize-document": "Summarize with AI",
  "summarize-collection": "Summarize with AI",
  "ask-archive": "Ask…",
};

/** ``on``: AI buttons are shown. ``off``: the status says AI is off (no key, or switched
 * off), so the "Turn on AI" hint is shown. Neither while the status is unknown. */
export function useAIState() {
  const status = useAIStatus();
  const data = status.data;
  return {
    status: data,
    on: data !== undefined && data.enabled && data.has_key,
    off: data !== undefined && !(data.enabled && data.has_key),
  };
}

/** The one small hint shown in place of AI buttons while AI is off. */
export function AIHint({ what }: { what?: string }) {
  const { status, off } = useAIState();
  if (!off || !status) return null;
  if (status.has_key) {
    // switched off: the switch is in Activity → AI (or the CLI)
    return (
      <p className="hint ai-hint">
        Turn on AI{what ? ` ${what}` : ""}: Activity → AI, or <code>dam ai --on</code> (see “AI (optional)” in the
        README).
      </p>
    );
  }
  return (
    <p className="hint ai-hint">
      Turn on AI{what ? ` ${what}` : ""}: <code>dam ai --set-key</code> (see “AI (optional)” in the README).
    </p>
  );
}

export type AIResultInfo = { cached: boolean; costEur: number };

/** ``seq`` counts prepares: each one remounts the sheet, so its arming starts over (a
 * prepare again can answer with the same token). ``error``: the send failed, so the
 * token is spent; ``prepareError``: an Ask again / Prepare again failed, which leaves
 * the shown token as it was. */
type Open = {
  params: Record<string, unknown>;
  prepared: AIPrepared;
  error: string | null;
  prepareError: string | null;
  seq: number;
};

export const ALREADY_SENT = "Already sent: the answer is saved — Ask AI shows it again for free";

/** ``ask(params)`` prepares ``task`` (nothing is sent) and opens the sheet; Send (or
 * "Use this" for a result from earlier) runs exactly that token and hands the answer
 * to ``onResult``. Render ``sheet``. One call at a time (synchronous guard). */
export function useAISend<T = Record<string, unknown>>(
  task: AITask,
  onResult: (data: T, info: AIResultInfo) => void,
) {
  const prepare = useAIPrepare();
  const run = useAIRun();
  const status = useAIStatus();
  const toast = useToast();
  const [open, setOpen] = useState<Open | null>(null);
  const [busy, setBusy] = useState(false);
  // the text went out (a send, not a free "Use this"): closing cannot unsend it
  const [sending, setSending] = useState(false);
  const inFlight = useRef(false);
  const generation = useRef(0); // a cancelled sheet's late answer is dropped

  async function guarded(work: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      await work();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  const doPrepare = (params: Record<string, unknown>, inSheet: boolean) =>
    guarded(async () => {
      const gen = ++generation.current;
      try {
        const prepared = await prepare.mutateAsync({ task, params });
        if (gen === generation.current) setOpen({ params, prepared, error: null, prepareError: null, seq: gen });
      } catch (e) {
        if (inSheet) {
          // the sheet still shows its own token, unspent: it stays usable
          setOpen((o) => (o ? { ...o, prepareError: errorText(e) } : o));
          return;
        }
        if (gen !== generation.current) return;
        else toast({ kind: "error", text: `${TASK_LABEL[task]}: ${visible(errorText(e))}` });
      }
    });

  const send = () => {
    const current = open;
    if (!current || current.error !== null) return;
    if (current.prepared.blocked !== null) return;
    void guarded(async () => {
      const gen = generation.current;
      setSending(current.prepared.cached === null);
      try {
        const result = await run.mutateAsync({ task, token: current.prepared.token });
        if (gen !== generation.current) return;
        setOpen(null);
        onResult(result.data as T, { cached: result.cached, costEur: result.cost_eur });
      } catch (e) {
        // the token is spent (or refused): only "Prepare again" goes on from here
        if (gen === generation.current) setOpen((o) => (o ? { ...o, error: errorText(e), prepareError: null } : o));
      } finally {
        setSending(false);
      }
    });
  };

  const cancel = () => {
    generation.current += 1;
    // closed while the text is out: the call goes on and its answer is cached
    if (sending) toast({ kind: "info", text: ALREADY_SENT });
    setOpen(null);
  };

  const sheet: ReactNode = open && (
    <SendSheet
      key={open.seq}
      task={TASK_LABEL[task]}
      askButton={ASK_BUTTON[task]}
      prepared={open.prepared}
      status={status.data}
      busy={busy}
      sending={sending}
      error={open.error}
      prepareError={open.prepareError}
      onSend={send}
      onCancel={cancel}
      onAskAgain={() => void doPrepare({ ...open.params, refresh: true }, true)}
      onPrepareAgain={() => void doPrepare(open.params, true)}
    />
  );

  return {
    /** Prepare ``task`` for ``params`` and show the sheet. */
    ask: (params: Record<string, unknown>) => void doPrepare(params, false),
    busy,
    sheet,
  };
}
