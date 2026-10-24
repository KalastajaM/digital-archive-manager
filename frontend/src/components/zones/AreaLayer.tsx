/** The areas of page 1 that took part in a suggestion, drawn over the page: a rule's areas
 * (the rule that gave the folder or name stronger, a rule that did not match dashed with the
 * reason), the lines that matched in them, the address area used and the line where the
 * person was found. Boxes are fractions of the page image, so the zoom never matters. */
import type { Area, PageBox } from "../../api/client";
import { visible } from "../../text";

export const percent = (box: PageBox) => ({
  left: `${box[0] * 100}%`,
  top: `${box[1] * 100}%`,
  width: `${(box[2] - box[0]) * 100}%`,
  height: `${(box[3] - box[1]) * 100}%`,
});

/** The label of an area: the rule's id (with the area's number when the rule has several),
 * and for an area that did not match, why. */
export function areaLabel(a: Area, areas: readonly Area[]): string {
  if (a.kind === "address") return a.rule_id ? `Address area of ${a.rule_id}` : "Address area";
  const several = areas.filter((x) => x.rule_id === a.rule_id && x.kind !== "address").length > 1;
  const name = several ? `${a.rule_id} (area ${a.index + 1})` : a.rule_id;
  return a.reason ? `${name}: ${a.reason}` : name;
}

export function AreaLayer({
  areas,
  person = null,
  personLine = null,
}: {
  areas: readonly Area[];
  /** The document's person, named on the line where they were found. */
  person?: string | null;
  personLine?: { box: PageBox } | null;
}) {
  return (
    <>
      {areas.map((a) => {
        const label = areaLabel(a, areas);
        const classes = ["area", `area-${a.kind}`, a.wins ? "area-wins" : "", a.matched ? "" : "area-off"];
        return (
          <span key={`${a.kind}-${a.rule_id}-${a.index}`}>
            <span
              className={classes.filter(Boolean).join(" ")}
              style={percent(a.box)}
              title={visible(label)}
              data-area={`${a.rule_id}:${a.index}`}
              data-kind={a.kind}
              data-matched={a.matched}
              data-wins={a.wins}
            >
              <span className="area-label">{visible(label)}</span>
            </span>
            {a.kind !== "address" &&
              a.lines.map((line, i) => (
                <span key={i} className="area-line" style={percent(line)} data-testid="area-line" />
              ))}
          </span>
        );
      })}
      {personLine && (
        <span className="area-line area-person" style={percent(personLine.box)} data-testid="person-line">
          <span className="area-label">{person ? `For: ${visible(person)}, found here` : "Found here"}</span>
        </span>
      )}
    </>
  );
}
