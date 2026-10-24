/** The areas of page 1 that took part in a suggestion, drawn over the page: a rule's areas
 * (the rule that gave the folder or name stronger, a rule that did not match dashed with the
 * reason), the lines that matched in them, the address area used and the line where the
 * person was found. Boxes are fractions of the page image, so the zoom never matters.
 *
 * With ``onChange`` the areas can be changed: a click selects an area, a drag of a selected
 * area moves it, and its handles resize it. On release ``onChange`` gets the new box. */
import { type PointerEvent, useRef, useState } from "react";
import type { Area, PageBox } from "../../api/client";
import { isShortcut, useKeydown } from "../../keyboard";
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

const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"] as const;
type Mode = "move" | (typeof HANDLES)[number];

/** Smallest side of an area (a share of the page) and the least change that counts as one. */
const MIN_SIDE = 0.01;
const MIN_CHANGE = 0.002;

const clamp = (n: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, n));

/** ``box`` moved or resized by ``(dx, dy)`` (fractions of the page): a move stays on the
 * page, a resize drags the handle's edges and keeps both sides at least ``MIN_SIDE``. */
export function changedBox(box: PageBox, mode: Mode, dx: number, dy: number): PageBox {
  let [x0, y0, x1, y1] = box;
  if (mode === "move") {
    const mx = clamp(dx, -x0, 1 - x1);
    const my = clamp(dy, -y0, 1 - y1);
    return [x0 + mx, y0 + my, x1 + mx, y1 + my];
  }
  if (mode.includes("w")) x0 = clamp(x0 + dx, 0, x1 - MIN_SIDE);
  if (mode.includes("e")) x1 = clamp(x1 + dx, x0 + MIN_SIDE, 1);
  if (mode.includes("n")) y0 = clamp(y0 + dy, 0, y1 - MIN_SIDE);
  if (mode.includes("s")) y1 = clamp(y1 + dy, y0 + MIN_SIDE, 1);
  return [x0, y0, x1, y1];
}

type Editing = { key: string; mode: Mode; start: [number, number]; orig: PageBox; box: PageBox; rect: DOMRect };

const keyOf = (a: Area) => `${a.kind}:${a.rule_id}:${a.index}`;

export function AreaLayer({
  areas,
  person = null,
  personLine = null,
  onChange,
}: {
  areas: readonly Area[];
  /** The document's person, named on the line where they were found. */
  person?: string | null;
  personLine?: { box: PageBox } | null;
  /** Makes the areas changeable: called on release with the area and its new box. */
  onChange?: (area: Area, box: PageBox) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const live = useRef<Editing | null>(null);
  live.current = editing;

  useKeydown((e) => {
    if (e.key !== "Escape" || !isShortcut(e) || (selected === null && editing === null)) return;
    e.preventDefault();
    if (editing) setEditing(null);
    else setSelected(null);
  });

  const at = (e: PointerEvent<HTMLElement>, rect: DOMRect): [number, number] => [
    (e.clientX - rect.left) / rect.width,
    (e.clientY - rect.top) / rect.height,
  ];
  const begin = (e: PointerEvent<HTMLElement>, area: Area, mode: Mode) => {
    if (e.button !== 0) return;
    const layer = e.currentTarget.closest(".page-layer");
    const rect = layer?.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setEditing({ key: keyOf(area), mode, start: at(e, rect), orig: area.box, box: area.box, rect });
  };
  const move = (e: PointerEvent<HTMLElement>) => {
    const cur = live.current;
    if (!cur) return;
    const [x, y] = at(e, cur.rect);
    setEditing({ ...cur, box: changedBox(cur.orig, cur.mode, x - cur.start[0], y - cur.start[1]) });
  };
  const release = (e: PointerEvent<HTMLElement>, area: Area) => {
    const cur = live.current;
    if (!cur || cur.key !== keyOf(area)) return;
    const [x, y] = at(e, cur.rect);
    const box = changedBox(cur.orig, cur.mode, x - cur.start[0], y - cur.start[1]);
    setEditing(null);
    if (box.some((v, i) => Math.abs(v - cur.orig[i]) > MIN_CHANGE)) onChange?.(area, box);
  };

  return (
    <>
      {areas.map((a) => {
        const label = areaLabel(a, areas);
        const key = keyOf(a);
        const editable = onChange !== undefined;
        const isSelected = editable && selected === key;
        const box = editing?.key === key ? editing.box : a.box;
        const classes = [
          "area",
          `area-${a.kind}`,
          a.wins ? "area-wins" : "",
          a.matched ? "" : "area-off",
          editable ? "area-editable" : "",
          isSelected ? "area-selected" : "",
        ];
        return (
          <span key={key}>
            <span
              className={classes.filter(Boolean).join(" ")}
              style={percent(box)}
              title={visible(label)}
              data-area={`${a.rule_id}:${a.index}`}
              data-kind={a.kind}
              data-matched={a.matched}
              data-wins={a.wins}
              onMouseDown={editable ? (e) => e.stopPropagation() : undefined} // the frame's own pan stays off
              onPointerDown={
                editable
                  ? (e) => {
                      e.stopPropagation();
                      if (!isSelected) setSelected(key);
                      else begin(e, a, "move");
                    }
                  : undefined
              }
              onPointerMove={editable ? move : undefined}
              onPointerUp={editable ? (e) => release(e, a) : undefined}
              onPointerCancel={editable ? () => setEditing(null) : undefined}
            >
              <span className="area-label">{visible(label)}</span>
              {isSelected &&
                HANDLES.map((h) => (
                  <span
                    key={h}
                    className={`area-handle area-handle-${h}`}
                    data-handle={h}
                    onPointerDown={(e) => {
                      e.stopPropagation();
                      begin(e, a, h);
                    }}
                  />
                ))}
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
