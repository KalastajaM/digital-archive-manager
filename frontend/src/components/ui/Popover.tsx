import { type CSSProperties, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type Props = {
  /** The button the popover belongs to: it sits below it (above when there is no room),
   * and the focus goes back to it when the popover closes. */
  anchor: HTMLElement | null;
  /** The dialog's accessible name. */
  label: string;
  /** Esc or a click outside. */
  onClose: () => void;
  children: ReactNode;
};

/** A small non-modal dialog anchored to a button (a confirmation that belongs to it):
 * portalled to the body with fixed positioning and kept inside the window, so it never
 * sits in the page flow. Esc and a click outside call ``onClose``; the button itself
 * is left to its own click handler (so a second click toggles). The child takes the
 * focus when it opens (the confirm button); when the popover goes away with the focus
 * inside it (or lost), the focus returns to the anchor. */
export function Popover({ anchor, label, onClose, children }: Props) {
  const pop = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<CSSProperties>({ position: "fixed", visibility: "hidden" });
  const close = useRef(onClose);
  close.current = onClose;

  useLayoutEffect(() => {
    const el = pop.current;
    if (!anchor || !el) return;
    const put = () => {
      const t = anchor.getBoundingClientRect();
      const w = el.offsetWidth;
      const h = el.offsetHeight;
      const gap = 6;
      const edge = 8;
      const left = Math.max(edge, Math.min(t.left, window.innerWidth - w - edge));
      let top = t.bottom + gap;
      if (top + h > window.innerHeight - edge && t.top - gap - h >= edge) top = t.top - gap - h;
      setPlace({ position: "fixed", top, left, right: "auto" });
    };
    put();
    window.addEventListener("resize", put);
    window.addEventListener("scroll", put, true);
    return () => {
      window.removeEventListener("resize", put);
      window.removeEventListener("scroll", put, true);
    };
  }, [anchor]);

  useEffect(() => {
    const away = (e: MouseEvent) => {
      const n = e.target as Node | null;
      if (n && (pop.current?.contains(n) || anchor?.contains(n))) return;
      close.current();
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [anchor]);

  // Back to the button, unless the focus already went somewhere on purpose.
  useEffect(() => {
    const box = pop.current;
    return () => {
      const at = document.activeElement;
      if (!at || at === document.body || box?.contains(at)) anchor?.focus({ preventScroll: true });
    };
  }, [anchor]);

  return createPortal(
    <div
      ref={pop}
      className="popover popover-fixed"
      role="dialog"
      aria-label={label}
      style={place}
      onKeyDown={(e) => {
        if (e.key !== "Escape") return;
        e.preventDefault();
        e.stopPropagation();
        close.current();
      }}
    >
      {children}
    </div>,
    document.body,
  );
}
