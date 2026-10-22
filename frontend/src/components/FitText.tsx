/** A one-line text shortened to the width it is given, like Finder: a folder path loses
 * its middle ("70. Work/…/Brightwave"), a file name keeps its extension. The element
 * takes its width from the layout around it (a grid cell, a flex item), so give it
 * ``min-width: 0`` and ``overflow: hidden``. While shortened, the full text stays in the
 * DOM for screen readers (and keeps the element as wide as the layout would make it),
 * and is the hover ``title``. All elements share one ResizeObserver. */
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { truncateName, truncatePath } from "./truncateText";

type Box = { width: number; font: string };

let canvas: CanvasRenderingContext2D | null | undefined;
const widths = new Map<string, number>();

/** The text's width in ``font``, remembered (the same names and folders come back on
 * every resize). */
function measure(text: string, font: string): number {
  if (canvas === undefined) {
    try {
      canvas = document.createElement("canvas").getContext("2d");
    } catch {
      canvas = null; // no canvas (jsdom): nothing is shortened
    }
  }
  if (!canvas) return 0;
  const key = `${font}|${text}`;
  let w = widths.get(key);
  if (w === undefined) {
    canvas.font = font;
    w = canvas.measureText(text).width;
    if (widths.size > 5000) widths.clear();
    widths.set(key, w);
  }
  return w;
}

/** The room for text inside ``el``: its width less padding. The fractional width, not
 * ``clientWidth``: that rounds down, and a text exactly as wide as its box (a flex item
 * sized to its own text) would then never fit. */
function boxOf(el: HTMLElement): Box {
  const style = getComputedStyle(el);
  const width =
    el.getBoundingClientRect().width -
    (parseFloat(style.paddingLeft) || 0) -
    (parseFloat(style.paddingRight) || 0) -
    (parseFloat(style.borderLeftWidth) || 0) -
    (parseFloat(style.borderRightWidth) || 0);
  return { width, font: style.font };
}

const watched = new Map<Element, (box: Box) => void>();
let observer: ResizeObserver | null = null;
function watch(el: HTMLElement, onBox: (box: Box) => void): () => void {
  if (typeof ResizeObserver === "undefined") return () => {};
  observer ??= new ResizeObserver((entries) => {
    for (const e of entries) {
      const cb = watched.get(e.target);
      if (cb && e.target instanceof HTMLElement) cb(boxOf(e.target));
    }
  });
  watched.set(el, onBox);
  observer.observe(el);
  return () => {
    watched.delete(el);
    observer?.unobserve(el);
  };
}

export function FitText({ text, mode, className }: { text: string; mode: "path" | "name"; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [box, setBox] = useState<Box | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const take = (b: Box) => setBox((old) => (old && old.width === b.width && old.font === b.font ? old : b));
    take(boxOf(el));
    return watch(el, take);
  }, []);
  const shown = useMemo(() => {
    // no layout (width 0) or no canvas: show everything and let CSS clip it
    if (!box || box.width <= 0 || measure(text, box.font) === 0) return text;
    // half a pixel of slack: layout widths are rounded to 1/64 px, canvas widths are not
    const fits = (t: string) => measure(t, box.font) <= box.width + 0.5;
    return mode === "path" ? truncatePath(text, fits) : truncateName(text, fits);
  }, [text, mode, box]);
  const cut = shown !== text;
  return (
    <span ref={ref} className={className} title={cut ? text : undefined}>
      {cut ? (
        <>
          <span aria-hidden="true">{shown}</span>
          <span className="fit-full">{text}</span>
        </>
      ) : (
        text
      )}
    </span>
  );
}
