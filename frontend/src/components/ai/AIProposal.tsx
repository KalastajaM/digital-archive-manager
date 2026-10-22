/** One AI proposal line (a collection's or a group's summary): the text, as plain text,
 * with Use and Discard. Nothing is saved until Use. */
import { visible } from "../../text";
import { Tag } from "../ui/Tag";

type Props = {
  /** Names the line ("AI summary of Quotes"). */
  label: string;
  text: string;
  busy?: boolean;
  onUse: () => void;
  onDiscard: () => void;
};

export function AIProposal({ label, text, busy, onUse, onDiscard }: Props) {
  return (
    <section className="ai-proposal" aria-label={visible(label)}>
      <p>
        <Tag tone="blue">AI</Tag> {visible(text)}
      </p>
      <div className="actions">
        <button type="button" disabled={busy} onClick={onDiscard}>
          Discard
        </button>
        <button type="button" className="primary" disabled={busy} onClick={onUse}>
          Use
        </button>
      </div>
    </section>
  );
}
