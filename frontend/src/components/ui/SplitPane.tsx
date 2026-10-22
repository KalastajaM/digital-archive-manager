/** A draggable divider between a list and its detail pane. ``useSplitWidth`` keeps the
 * list's (or, with ``edge: "end"``, the right-hand pane's) width, remembered per screen
 * in this browser; ``<Splitter>`` is the separator to render inside the grid host. */
import { type CSSProperties, type KeyboardEvent, type PointerEvent, type RefObject, useRef, useState } from "react";

export type SplitOptions = {
  /** Smallest and largest width, in ``unit``. ``max`` may be ``Infinity`` (px): then only
   * the other pane's minimum limits it. */
  min: number;
  max: number;
  /** The width when nothing is remembered, and the one a double-click restores. */
  initial: number;
  /** "%" of the host's width (default) or "px". */
  unit?: "%" | "px";
  /** Which pane the width belongs to: the first (default) or the last. */
  edge?: "start" | "end";
};

export type Split = {
  width: number;
  hostRef: RefObject<HTMLDivElement | null>;
  /** The host's style: it carries the width as ``--split``. */
  hostStyle: CSSProperties;
  opts: Required<SplitOptions>;
  set: (width: number) => void;
  preview: (width: number) => void;
  reset: () => void;
};

/** The room the other pane keeps when the width is in px. */
const OTHER_MIN = 320;

function clampTo(o: Required<SplitOptions>, n: number, hostWidth?: number): number {
  const max = o.unit === "px" && hostWidth ? Math.max(o.min, Math.min(o.max, hostWidth - OTHER_MIN)) : o.max;
  return Math.max(o.min, Math.min(max, Math.round(n)));
}

function read(key: string, o: Required<SplitOptions>): number {
  try {
    const n = Number(localStorage.getItem(key));
    return n > 0 ? clampTo(o, n) : o.initial;
  } catch {
    return o.initial;
  }
}

function write(key: string, width: number) {
  try {
    localStorage.setItem(key, String(width));
  } catch {
    // storage blocked: the width lasts for this page only
  }
}

function forget(key: string) {
  try {
    localStorage.removeItem(key);
  } catch {
    // storage blocked: nothing was kept
  }
}

export function useSplitWidth(key: string, options: SplitOptions): Split {
  const opts: Required<SplitOptions> = { unit: "%", edge: "start", ...options };
  const [width, setWidth] = useState(() => read(key, opts));
  const hostRef = useRef<HTMLDivElement>(null);
  const hostWidth = () => hostRef.current?.getBoundingClientRect().width;
  return {
    width,
    hostRef,
    hostStyle: { "--split": `${width}${opts.unit}` } as CSSProperties,
    opts,
    // While dragging only the state moves; the drop remembers it.
    preview: (w) => setWidth(clampTo(opts, w, hostWidth())),
    set: (w) => {
      const next = clampTo(opts, w, hostWidth());
      setWidth(next);
      write(key, next);
    },
    reset: () => {
      setWidth(opts.initial);
      forget(key);
    },
  };
}

export function Splitter({ split, label }: { split: Split; label: string }) {
  const { opts, width } = split;
  const end = opts.edge === "end";
  const step = opts.unit === "%" ? 2 : 16;
  /** The width the pointer asks for, from the host's box. */
  const fromPointer = (clientX: number, rect: DOMRect) => {
    const px = end ? rect.right - clientX : clientX - rect.left;
    return opts.unit === "%" ? (px / rect.width) * 100 : px;
  };
  const onPointerDown = (e: PointerEvent) => {
    const host = split.hostRef.current;
    if (!host || e.button !== 0) return;
    e.preventDefault();
    const rect = host.getBoundingClientRect();
    const move = (m: globalThis.PointerEvent) => split.preview(fromPointer(m.clientX, rect));
    const up = (m: globalThis.PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      split.set(fromPointer(m.clientX, rect));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    e.stopPropagation();
    // The arrow points the way the divider moves; at the end edge that shrinks the pane.
    const dir = (e.key === "ArrowRight" ? 1 : -1) * (end ? -1 : 1);
    split.set(width + dir * step);
  };
  return (
    <div
      className={end ? "splitter splitter-end" : "splitter"}
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuemin={opts.min}
      aria-valuemax={Number.isFinite(opts.max) ? opts.max : undefined}
      aria-valuenow={width}
      tabIndex={0}
      title="Drag to resize, double-click to reset"
      onPointerDown={onPointerDown}
      onDoubleClick={split.reset}
      onKeyDown={onKeyDown}
    />
  );
}
