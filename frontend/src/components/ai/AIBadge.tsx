/** The small "AI" marker on a value the AI suggested (Today's inbox card): hovering or
 * focusing it shows the confidence and the reason. */
import { visible } from "../../text";

const percent = (confidence: number | undefined) =>
  confidence === undefined ? null : `${Math.round(Math.min(1, Math.max(0, confidence)) * 100)}% sure`;

type Props = {
  /** The field as named in the sentence ("Name", "tray", "Due date"). */
  field: string;
  confidence?: number;
  reason: string;
};

export function AIBadge({ field, confidence, reason }: Props) {
  const sure = percent(confidence);
  const why = visible(reason);
  const name = visible(field);
  const label = `AI suggested ${name}${sure ? `: ${sure}` : ""}. ${why}`;
  return (
    <span className="ai-mark">
      <span className="ai-badge" tabIndex={0} aria-label={label} data-tip={`AI${sure ? ` · ${sure}` : ""} — ${why}`}>
        AI
      </span>
    </span>
  );
}

/** A suggestion the server refused for a field (``rejected``): what was left as it was. */
export function AIRejected({ field, reason }: { field: string; reason: string }) {
  return (
    <p className="hint ai-rejected">
      AI’s {visible(field)} not used: {visible(reason)}
    </p>
  );
}
