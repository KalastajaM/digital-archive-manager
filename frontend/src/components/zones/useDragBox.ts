/** Drawing a box by dragging over page 1 (the Draw a box tool of a preview, and a sample
 * letter in Settings). The surface's handlers go on an element that covers the page image;
 * the box is in fractions of it (origin top left), so the zoom never matters. */
import { type PointerEvent, useState } from "react";
import type { PageBox } from "../../api/client";

type Drag = { x0: number; y0: number; x1: number; y1: number };

/** Smallest side of a box (a share of the page): a click or a twitch draws nothing. */
const MIN_SIDE = 0.01;
const clamp = (n: number) => Math.min(1, Math.max(0, n));

const boxOf = (d: Drag): PageBox => [Math.min(d.x0, d.x1), Math.min(d.y0, d.y1), Math.max(d.x0, d.x1), Math.max(d.y0, d.y1)];

/** A pointer's place on the layer under it, as fractions of it (null: it has no size). */
function point(e: PointerEvent<HTMLElement>): [number, number] | null {
  const r = e.currentTarget.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return null;
  return [clamp((e.clientX - r.left) / r.width), clamp((e.clientY - r.top) / r.height)];
}

/** ``onDrawn`` gets each box drawn on release. ``drawing``: the box being drawn, if any. */
export function useDragBox(onDrawn: (box: PageBox) => void) {
  const [drag, setDrag] = useState<Drag | null>(null);
  const surface = {
    onMouseDown: (e: { stopPropagation: () => void }) => e.stopPropagation(), // the frame's own pan stays off while drawing
    onPointerDown: (e: PointerEvent<HTMLElement>) => {
      if (e.button !== 0) return;
      const at = point(e);
      if (!at) return;
      e.currentTarget.setPointerCapture?.(e.pointerId);
      setDrag({ x0: at[0], y0: at[1], x1: at[0], y1: at[1] });
    },
    onPointerMove: (e: PointerEvent<HTMLElement>) => {
      const at = point(e);
      if (drag && at) setDrag({ ...drag, x1: at[0], y1: at[1] });
    },
    onPointerUp: (e: PointerEvent<HTMLElement>) => {
      if (!drag) return;
      const at = point(e) ?? [drag.x1, drag.y1];
      const drawn = boxOf({ ...drag, x1: at[0], y1: at[1] });
      setDrag(null);
      if (drawn[2] - drawn[0] < MIN_SIDE || drawn[3] - drawn[1] < MIN_SIDE) return;
      onDrawn(drawn);
    },
    onPointerCancel: () => setDrag(null),
  };
  return { drawing: drag ? boxOf(drag) : null, cancel: () => setDrag(null), surface };
}
