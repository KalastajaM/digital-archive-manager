/** Ask (spec §3): a question about the archive, answered from its best-matching files.
 * Ask… prepares the question (retrieval is code only, no tokens) and shows the "What
 * will be sent" sheet with the question and the snippets; nothing is sent before Send.
 * "Nothing in the archive matches" is a blocked prepare: it costs nothing. Each answer
 * has numbered citations; one opens Quick Look on that file. Answers are kept for this
 * session only (never saved), newest first. */
import { useQueryClient } from "@tanstack/react-query";
import { MessageCircleQuestion } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { type AskAnswer, type AskEntry, errorText, type FileDetail, get, useAskSession } from "../api/client";
import { euro } from "../components/ai/SendSheet";
import { AIHint, useAISend, useAIState } from "../components/ai/useAI";
import { useToast } from "../components/Toasts";
import { EmptyState } from "../components/ui/EmptyState";
import { Tag } from "../components/ui/Tag";
import { Toolbar } from "../components/ui/Toolbar";
import { type QLFile, useQuickLook } from "../components/useQuickLook";
import { MarkIcons } from "../components/MarkIcons";
import { visible } from "../text";

const QUESTION_MAX = 1000;

/** The answer's text with each "[n]" of a known citation as a button. */
function AnswerText({ entry, onCite }: { entry: AskEntry; onCite: (index: number) => void }) {
  const { answer, citations } = entry.answer;
  const parts: ReactNode[] = [];
  let last = 0;
  for (const m of answer.matchAll(/\[(\d+)\]/g)) {
    const n = Number(m[1]);
    if (n < 1 || n > citations.length) continue;
    parts.push(visible(answer.slice(last, m.index)));
    parts.push(
      <button
        key={`${m.index}`}
        type="button"
        className="ask-cite"
        aria-label={`Source ${n}: ${visible(citations[n - 1].name)}`}
        onClick={() => onCite(n - 1)}
      >
        [{n}]
      </button>,
    );
    last = m.index + m[0].length;
  }
  parts.push(visible(answer.slice(last)));
  return <p className="ask-answer-text">{parts}</p>;
}

function Answer({ entry, onCite }: { entry: AskEntry; onCite: (index: number) => void }) {
  const headingId = useId();
  const rejected = Object.values(entry.answer.rejected ?? {});
  return (
    <article className="ask-answer" aria-labelledby={headingId}>
      <h3 id={headingId} className="ask-question">
        {visible(entry.question)}
      </h3>
      <AnswerText entry={entry} onCite={onCite} />
      {entry.answer.citations.length > 0 && (
        <ol className="ask-sources" aria-label="Sources">
          {entry.answer.citations.map((c, i) => (
            <li key={i}>
              <button type="button" className="link-button" onClick={() => onCite(i)}>
                [{i + 1}] {visible(c.name)}
              </button>
              <MarkIcons marks={c.marks} />
              {c.quote && <q className="ask-quote">{visible(c.quote)}</q>}
            </li>
          ))}
        </ol>
      )}
      {rejected.length > 0 && <p className="hint">{rejected.map(visible).join("; ")}</p>}
      <p className="hint ask-cost">
        {entry.cached ? <Tag tone="blue">from earlier</Tag> : `Cost: ${euro(entry.costEur)}`}
      </p>
    </article>
  );
}

type Look = { files: QLFile[]; index: number; pending: boolean };

export default function Ask() {
  const fieldId = useId();
  const ai = useAIState();
  const session = useAskSession();
  const client = useQueryClient();
  const toast = useToast();
  const [question, setQuestion] = useState("");
  const asked = useRef(""); // the question the open sheet is for
  const send = useAISend<AskAnswer>("ask-archive", (answer, info) => {
    session.add({ question: asked.current, answer, costEur: info.costEur, cached: info.cached });
    setQuestion("");
  });

  const [look, setLook] = useState<Look>({ files: [], index: 0, pending: false });
  const quickLook = useQuickLook(look.files, look.index, (index) => setLook((l) => ({ ...l, index })));
  useEffect(() => {
    if (!look.pending) return;
    setLook((l) => ({ ...l, pending: false }));
    quickLook.open();
  }, [look.pending, quickLook]);
  const resolving = useRef(false);

  /** Quick Look on citation ``index`` of ``entry``, with its other sources beside it. */
  const cite = async (entry: AskEntry, index: number) => {
    if (resolving.current) return;
    resolving.current = true;
    try {
      const files = await Promise.all(
        entry.answer.citations.map((c) =>
          client.fetchQuery({
            queryKey: ["file", c.drive_id],
            queryFn: () => get<FileDetail>(`/api/files/${encodeURIComponent(c.drive_id)}`),
          }),
        ),
      );
      setLook({
        files: files.map(({ record: r }) => ({ drive_id: r.drive_id, name: r.name, path: r.path, ext: r.ext })),
        index,
        pending: true,
      });
    } catch (e) {
      toast({ kind: "error", text: `Could not open the source: ${visible(errorText(e))}` });
    } finally {
      resolving.current = false;
    }
  };

  const submit = () => {
    const q = question.trim();
    if (!q || send.busy) return;
    asked.current = q;
    send.ask({ question: q });
  };

  return (
    <div className="ask">
      <Toolbar title="Ask" subtitle="Answers are kept for this session only" />
      <div className="ask-body">
        <AIHint what="to ask the archive" />
        {ai.on && (
          <form
            className="ask-form"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <label htmlFor={fieldId}>Question</label>
            <textarea
              id={fieldId}
              rows={2}
              maxLength={QUESTION_MAX}
              value={question}
              placeholder="When is the Northpower bill due?"
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit();
                }
              }}
            />
            <p className="hint">
              The best-matching snippets of your archive are shown before anything is sent. Excluded folders are never
              searched.
            </p>
            <div className="actions">
              <button type="submit" className="primary" disabled={!question.trim() || send.busy}>
                Ask…
              </button>
            </div>
          </form>
        )}
        {session.answers.length === 0 ? (
          ai.on && (
            <EmptyState
              icon={<MessageCircleQuestion size={40} strokeWidth={1.25} />}
              title="Ask your archive a question."
              hint="The answer cites the files it comes from; click a source to look at it."
            />
          )
        ) : (
          <section className="ask-answers" aria-label="Answers">
            {session.answers.map((entry) => (
              <Answer key={entry.id} entry={entry} onCite={(i) => void cite(entry, i)} />
            ))}
          </section>
        )}
      </div>
      {send.sheet}
      {quickLook.view}
    </div>
  );
}
