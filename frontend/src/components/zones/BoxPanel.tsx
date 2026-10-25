/** The boxes drawn on page 1 and what they can mean. Every box is kept as it is drawn, is
 * numbered, and is listed with the words found in it (or "No text found", or its picture)
 * and its own remove button. Each box is matched by its **Words** or by its **Picture**
 * (for a letterhead that is only a logo). "Make a rule…" makes a rule from all the boxes
 * (the rule sheet, with a replay as proof, and where who the letter is from can be given);
 * the two address choices keep the one box as the area where the person a letter is for is
 * looked for (a person is found from text only, so they never take a picture). */
import { X } from "lucide-react";
import { useState } from "react";
import {
  errorText,
  pngSrc,
  type PageBox,
  type Rule,
  type RuleIn,
  useDraftZone,
  usePeople,
  useSavePeople,
  useSaveRule,
  type ZoneDraft,
} from "../../api/client";
import { visible, withoutNoise } from "../../text";
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

/** A box drawn on page 1. ``lines``: the text found in it (null while it is being read);
 * ``picture``: the crop as a base64 PNG once the box is matched by its picture. */
export type KeptBox = {
  id: number;
  box: PageBox;
  lines: string[] | null;
  mode: "words" | "picture";
  picture?: string;
  /** Why the box could not be read or cut, shown in its row. */
  problem?: string;
};

/** The text of a box as listed: its lines without OCR noise. */
export const boxWords = (k: KeptBox): string[] => (k.lines ?? []).map(withoutNoise).filter((l) => l !== "");

export function BoxPanel({
  driveId,
  boxes,
  rule,
  onMode,
  onRemove,
  onClose,
}: {
  driveId: string;
  boxes: KeptBox[];
  /** The rule behind the current suggestion (offers "Address area for this rule's letters"). */
  rule: Rule | null;
  onMode: (index: number, mode: "words" | "picture") => void;
  onRemove: (index: number) => void;
  /** Drops all the boxes and closes the panel. */
  onClose: () => void;
}) {
  const toast = useToast();
  const people = usePeople();
  const savePeople = useSavePeople();
  const saveRule = useSaveRule();
  const draftZone = useDraftZone();
  const [draft, setDraft] = useState<ZoneDraft | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  // a words box without text cannot make an area: choose its picture, or remove it
  const textBoxes = boxes.filter((k) => k.mode === "words" && boxWords(k).length > 0).map((k) => k.box);
  const pictureBoxes = boxes.filter((k) => k.mode === "picture" && k.picture).map((k) => k.box);
  const reading = boxes.some((k) => k.lines === null || (k.mode === "picture" && !k.picture && !k.problem));
  const needsText = pictureBoxes.length > 0 && textBoxes.length === 0;
  // the address area is one box matched by its words
  const only = boxes.length === 1 && boxes[0].mode === "words" ? boxes[0] : null;

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
      setDraft(
        await draftZone.mutateAsync({
          drive_id: driveId,
          boxes: textBoxes,
          ...(pictureBoxes.length > 0 ? { picture_boxes: pictureBoxes } : {}),
        }),
      );
    } catch (e) {
      setProblem(errorText(e));
    }
  };

  return (
    <section className="box-panel" aria-label="The boxes">
      <header className="box-panel-head">
        <strong>Boxes on page 1</strong>
        <button
          type="button"
          className="icon-button"
          aria-label="Close and drop the boxes"
          title="Close this panel and drop all the boxes you drew"
          onClick={onClose}
        >
          <X size={14} aria-hidden="true" />
        </button>
      </header>
      <ul className="box-kept" aria-label="Boxes">
        {boxes.map((k, i) => (
          <li key={k.id}>
            <span className="box-kept-text">
              <strong>Box {i + 1}</strong>{" "}
              <span className="box-mode" role="group" aria-label={`What box ${i + 1} matches`}>
                {(["words", "picture"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    className="link-button"
                    aria-pressed={k.mode === m}
                    onClick={() => k.mode !== m && onMode(i, m)}
                  >
                    {m === "words" ? "Words" : "Picture"}
                  </button>
                ))}
              </span>{" "}
              {k.mode === "picture" ? (
                k.picture ? (
                  <img className="box-kept-picture" src={pngSrc(k.picture)} alt={`Picture of box ${i + 1}`} />
                ) : (
                  <span className="busy" role="status">Cutting the picture…</span>
                )
              ) : k.lines === null ? (
                <span className="busy" role="status">Reading the box…</span>
              ) : boxWords(k).length === 0 ? (
                <span className="hint">No text found</span>
              ) : (
                visible(boxWords(k).join(" / "))
              )}
              {k.problem && <span className="error" role="alert"> {visible(k.problem)}</span>}
            </span>
            <button type="button" className="icon-button" aria-label={`Remove box ${i + 1}`} onClick={() => onRemove(i)}>
              <X size={14} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
      {needsText && (
        <p className="hint">Add a text box to make this faster and surer: a picture alone takes longer to test and is less sure.</p>
      )}
      <div className="box-actions">
        <button
          type="button"
          className="primary"
          disabled={draftZone.isPending || reading || (textBoxes.length === 0 && pictureBoxes.length === 0)}
          onClick={() => void makeRule()}
        >
          Make a rule…
        </button>
        {only && rule && (
          <button
            type="button"
            disabled={saveRule.isPending}
            onClick={() =>
              void run(
                () => saveRule.mutateAsync({ rule: ruleIn(rule, { person_zone: only.box }), replaces: rule.id }),
                `Address area saved for rule ${rule.id}.`,
              )
            }
          >
            Address area for this rule's letters
          </button>
        )}
        {only && (
          <button
            type="button"
            disabled={!people.data || savePeople.isPending}
            onClick={() =>
              void run(
                () => savePeople.mutateAsync({ people: people.data?.people ?? [], address_zone: only.box }),
                "Address area saved for all letters.",
              )
            }
          >
            Address area for all letters
          </button>
        )}
      </div>
      {rule && !rule.learned && <p className="hint">{visible(rewriteNote("Saving", rule.file))}</p>}
      {problem && <p className="error" role="alert">{visible(problem)}</p>}
      {draft && <RuleSheet initial={draft} nearDriveId={driveId} sourceDriveId={driveId} onClose={() => setDraft(null)} />}
    </section>
  );
}
