/** What a box drawn on page 1 can mean: the lines found in it and the choices. "Add another
 * box" keeps it, so a rule can need several areas; "Sender…" makes a rule from all the kept
 * boxes and the one just drawn (the rule sheet, with a replay as proof); the two address
 * choices keep the box as the area where the person a letter is for is looked for. */
import { X } from "lucide-react";
import { useState } from "react";
import {
  errorText,
  type Page1,
  type PageBox,
  type Rule,
  type RuleIn,
  useDraftZone,
  usePeople,
  useSavePeople,
  useSaveRule,
  useSenders,
  type ZoneDraft,
} from "../../api/client";
import { visible } from "../../text";
import { RuleSheet, rewriteNote } from "../rules/RuleSheet";
import { useToast } from "../Toasts";

/** A stored rule as the save call takes it, with changes. */
const ruleIn = (r: Rule, over: Partial<RuleIn>): RuleIn => ({
  id: r.id,
  when: {
    text_contains: r.when.text_contains,
    filename_matches: r.when.filename_matches,
    folder_is: r.when.folder_is,
    zones: r.when.zones,
    person: r.when.person,
  },
  then: r.then,
  person_zone: r.person_zone,
  sender: r.sender,
  ...over,
});

/** A box kept for the rule being made, with the lines of page 1 that lie in it. */
export type KeptBox = { box: PageBox; lines: string[] };

export function BoxPanel({
  driveId,
  box,
  kept,
  found,
  pending,
  error,
  rule,
  onAddAnother,
  onRemoveKept,
  onClose,
}: {
  driveId: string;
  /** The box just drawn (null: the kept boxes only, the next one is not drawn yet). */
  box: PageBox | null;
  kept: KeptBox[];
  found: Page1 | undefined;
  pending: boolean;
  error: unknown;
  /** The rule behind the current suggestion (offers "Address area for this sender"). */
  rule: Rule | null;
  onAddAnother: () => void;
  onRemoveKept: (index: number) => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const senders = useSenders();
  const people = usePeople();
  const savePeople = useSavePeople();
  const saveRule = useSaveRule();
  const draftZone = useDraftZone();
  const [naming, setNaming] = useState(false);
  const [sender, setSender] = useState("");
  const [draft, setDraft] = useState<ZoneDraft | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const lines = found?.lines ?? [];
  const boxes: PageBox[] = [...kept.map((k) => k.box), ...(box ? [box] : [])];
  const run = async (action: () => Promise<unknown>, done: string) => {
    setProblem(null);
    try {
      await action();
      toast({ kind: "info", text: done });
      onClose();
    } catch (e) {
      setProblem(errorText(e));
    }
  };
  const makeRule = async () => {
    setProblem(null);
    try {
      setDraft(await draftZone.mutateAsync({ drive_id: driveId, boxes, sender: sender.trim() || null }));
    } catch (e) {
      setProblem(errorText(e));
    }
  };

  return (
    <section className="box-panel" aria-label="The box">
      <header className="box-panel-head">
        <strong>Lines in the box</strong>
        <button type="button" className="icon-button" aria-label="Close the box" onClick={onClose}>
          <X size={14} aria-hidden="true" />
        </button>
      </header>
      {kept.length > 0 && (
        <ul className="box-kept" aria-label="Kept boxes">
          {kept.map((k, i) => (
            <li key={`${i}-${k.box.join(",")}`}>
              <span className="box-kept-text">
                <strong>Box {i + 1}</strong> {visible(k.lines.join(" / "))}
              </span>
              <button type="button" className="icon-button" aria-label={`Remove box ${i + 1}`} onClick={() => onRemoveKept(i)}>
                <X size={14} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {box &&
        (pending ? (
          <p className="busy" role="status">Reading the box…</p>
        ) : error ? (
          <p className="error" role="alert">{visible(errorText(error))}</p>
        ) : lines.length === 0 ? (
          <p className="hint">No text found in this box.</p>
        ) : (
          <ul className="box-lines">
            {lines.map((l, i) => (
              <li key={`${i}-${l.text}`}>{visible(l.text)}</li>
            ))}
          </ul>
        ))}
      {!naming ? (
        <div className="box-actions">
          <button type="button" onClick={() => setNaming(true)}>Sender…</button>
          {box && (
            <button type="button" disabled={pending || lines.length === 0} onClick={onAddAnother}>
              Add another box
            </button>
          )}
          {box && kept.length === 0 && rule && (
            <button
              type="button"
              disabled={saveRule.isPending}
              onClick={() =>
                void run(
                  () => saveRule.mutateAsync({ rule: ruleIn(rule, { person_zone: box }), replaces: rule.id }),
                  `Address area saved for rule ${rule.id}.`,
                )
              }
            >
              Address area for this sender
            </button>
          )}
          {box && kept.length === 0 && (
          <button
            type="button"
            disabled={!people.data || savePeople.isPending}
            onClick={() =>
              void run(
                () => savePeople.mutateAsync({ people: people.data?.people ?? [], address_zone: box }),
                "Address area saved for all letters.",
              )
            }
          >
            Address area for all letters
          </button>
          )}
        </div>
      ) : (
        <form
          className="box-sender"
          onSubmit={(e) => {
            e.preventDefault();
            void makeRule();
          }}
        >
          <div className="field">
            <label htmlFor={`box-sender-${driveId}`}>Sender (optional)</label>
            <input
              id={`box-sender-${driveId}`}
              value={sender}
              placeholder="Pohjola"
              onChange={(e) => setSender(e.target.value)}
            />
            {(senders.data?.length ?? 0) > 0 && (
              <ul className="assign-choices" aria-label="Senders you have used">
                {senders.data?.map((s) => (
                  <li key={s.sender}>
                    <button
                      type="button"
                      className="assign-choice"
                      aria-pressed={sender.trim() === s.sender}
                      onClick={() => setSender(s.sender)}
                    >
                      {visible(s.sender)}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className="hint">With a sender, the test also says how many of the letters you set as from it the box finds.</p>
          </div>
          <div className="actions">
            <button type="button" onClick={() => setNaming(false)}>Back</button>
            <button type="submit" className="primary" disabled={draftZone.isPending || boxes.length === 0}>Make a rule…</button>
          </div>
        </form>
      )}
      {rule && !rule.learned && !naming && <p className="hint">{visible(rewriteNote("Saving", rule.file))}</p>}
      {problem && <p className="error" role="alert">{visible(problem)}</p>}
      {draft && <RuleSheet initial={draft} onClose={() => setDraft(null)} />}
    </section>
  );
}
