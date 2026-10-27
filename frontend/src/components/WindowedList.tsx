/** A long list that renders only the rows near the view, so a folder of thousands of
 * files does not build thousands of rows. The rows above and below stand in as spacers
 * of their (measured, else estimated) height, so the scroll bar stays true. The pinned
 * row (the current one) is always rendered: its ``aria-current``, focus and
 * ``scrollIntoView`` work wherever it is. Short lists, and a list with no laid-out
 * height (jsdom), render every row. */
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";

/** Lists this long or longer are windowed. */
export const WINDOW_FROM = 300;
/** How far above and below the view rows stay rendered, in pixels. */
const OVERSCAN = 800;
/** A row's height before any row is measured. */
const ESTIMATE = 30;

/** What to render: runs of rows ``[from, to)`` and spacers between them, in order. */
export type Part = { from: number; to: number } | { spacer: number };

/** The rows of ``heights`` to render for a view of ``height`` pixels starting ``top``
 * pixels below the first row, plus ``pin`` wherever it is. */
export function rowWindow(heights: number[], top: number, height: number, pin: number | null): Part[] {
  const n = heights.length;
  const offs = new Array<number>(n + 1);
  offs[0] = 0;
  for (let k = 0; k < n; k++) offs[k + 1] = offs[k] + heights[k];
  // the first row whose bottom is below y
  const rowAt = (y: number) => {
    let lo = 0;
    let hi = n;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (offs[mid + 1] > y) hi = mid;
      else lo = mid + 1;
    }
    return lo;
  };
  const start = Math.min(n, rowAt(top - OVERSCAN));
  const end = Math.max(start, Math.min(n, rowAt(top + height + OVERSCAN) + 1));
  const runs: [number, number][] = [[start, end]];
  if (pin !== null && pin >= 0 && pin < n && (pin < start || pin >= end)) {
    runs.push([pin, pin + 1]);
    runs.sort((a, b) => a[0] - b[0]);
  }
  const parts: Part[] = [];
  let at = 0;
  for (const [from, to] of runs) {
    if (from > at) parts.push({ spacer: offs[from] - offs[at] });
    if (to > from) parts.push({ from, to });
    at = Math.max(at, to);
  }
  if (n > at) parts.push({ spacer: offs[n] - offs[at] });
  return parts;
}

type Props<T> = {
  entries: T[];
  /** A row's identity: a measured height stays with its row when the list changes. */
  keyOf: (entry: T) => string;
  /** The row that is always rendered (the current one), or null. */
  pin: number | null;
  /** One row: a single ``<li>``. ``pos`` is its place in ``entries``. */
  render: (entry: T, pos: number) => ReactNode;
  /** Rendered before the rows, always (the new folder's row). */
  head?: ReactNode;
  listRef: (el: HTMLUListElement | null) => void;
  className: string;
  "aria-label": string;
};

/** The ``<ul>`` of a long list. Its parent element is the one that scrolls. */
export function WindowedList<T>({ entries, keyOf, pin, render, head, listRef, className, "aria-label": label }: Props<T>) {
  const ul = useRef<HTMLUListElement | null>(null);
  const heights = useRef(new Map<string, number>());
  const [view, setView] = useState({ top: 0, height: 0 });
  const [, setMeasured] = useState(0);
  const long = entries.length >= WINDOW_FROM;
  const hasHead = head != null && head !== false;

  // the view: where the scrolling parent is, relative to the first row
  useEffect(() => {
    const list = ul.current;
    const scroller = list?.parentElement;
    if (!long || !list || !scroller) return;
    // scroll events come once a frame at most; the state only changes with the view
    const read = () => {
      const headHeight = hasHead ? ((list.firstElementChild as HTMLElement | null)?.offsetHeight ?? 0) : 0;
      const rowsAt =
        list.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop + headHeight;
      const next = { top: Math.round(scroller.scrollTop - rowsAt), height: scroller.clientHeight };
      setView((old) => (old.top === next.top && old.height === next.height ? old : next));
    };
    read();
    scroller.addEventListener("scroll", read, { passive: true });
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(read) : null;
    observer?.observe(scroller);
    return () => {
      scroller.removeEventListener("scroll", read);
      observer?.disconnect();
    };
  }, [long, hasHead]);

  const windowed = long && view.height > 0;
  let parts: Part[] = [{ from: 0, to: entries.length }];
  if (windowed) {
    const known = [...heights.current.values()];
    const estimate = known.length > 0 ? known.reduce((a, b) => a + b, 0) / known.length : ESTIMATE;
    parts = rowWindow(
      entries.map((e) => heights.current.get(keyOf(e)) ?? estimate),
      view.top,
      view.height,
      pin,
    );
  }

  // measure the rendered rows; a changed height renders the window again
  useLayoutEffect(() => {
    const list = ul.current;
    if (!windowed || !list) return;
    const rows = [...list.children].filter((el) => !el.classList.contains("entries-spacer")).slice(hasHead ? 1 : 0);
    let changed = false;
    let r = 0;
    for (const part of parts) {
      if ("spacer" in part) continue;
      for (let k = part.from; k < part.to; k++, r++) {
        const el = rows[r] as HTMLElement | undefined;
        if (!el) continue;
        const key = keyOf(entries[k]);
        const h = el.getBoundingClientRect().height;
        if (Math.abs((heights.current.get(key) ?? -1) - h) > 0.5) {
          heights.current.set(key, h);
          changed = true;
        }
      }
    }
    if (changed) setMeasured((m) => m + 1);
  });

  return (
    <ul
      ref={(el) => {
        ul.current = el;
        listRef(el);
      }}
      className={className}
      aria-label={label}
    >
      {head}
      {parts.flatMap<ReactNode>((part, p) =>
        "spacer" in part
          ? [<li key={`spacer:${p}`} className="entries-spacer" aria-hidden="true" style={{ height: part.spacer }} />]
          : entries.slice(part.from, part.to).map((entry, j) => render(entry, part.from + j)),
      )}
    </ul>
  );
}
