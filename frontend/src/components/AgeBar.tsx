/** The inbox's age at a glance: one bar split into this week, last week and older (by
 * each file's arrival in the inbox), with the numbers in a legend. */
import { useId } from "react";

type Props = { thisWeek: number; lastWeek: number; older: number };

const BUCKETS = [
  { key: "thisWeek", label: "this week", tone: "green" },
  { key: "lastWeek", label: "last week", tone: "orange" },
  { key: "older", label: "older", tone: "red" },
] as const;

const percent = (part: number, total: number) => `${Math.round((part / total) * 10_000) / 100}%`;

export function AgeBar(props: Props) {
  const legendId = useId();
  const total = props.thisWeek + props.lastWeek + props.older;
  const label = BUCKETS.map((b) => `${props[b.key]} ${b.label}`).join(", ");
  return (
    <div className="age-bar">
      <div className="age-bar-track" role="img" aria-label={label} aria-describedby={legendId}>
        {total > 0 &&
          BUCKETS.filter((b) => props[b.key] > 0).map((b) => (
            <span
              key={b.key}
              className={`age-bar-segment age-bar-${b.tone}`}
              style={{ width: percent(props[b.key], total) }}
            />
          ))}
      </div>
      <ul className="age-bar-legend" id={legendId} aria-label="Inbox age">
        {BUCKETS.map((b) => (
          <li key={b.key}>
            <span className={`age-bar-swatch age-bar-${b.tone}`} aria-hidden="true" />
            {props[b.key]} {b.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
