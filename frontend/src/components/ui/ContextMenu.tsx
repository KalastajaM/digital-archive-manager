import { type KeyboardEvent, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { MenuEntry } from "./Menu";

type Props = {
  /** Where the pointer was (client coordinates). */
  x: number;
  y: number;
  /** The menu's accessible name. */
  label: string;
  /** "separator": a rule between groups (one at an end, or two in a row, is dropped). */
  entries: MenuEntry[];
  onClose: () => void;
};

/** The entries with no rule at either end and none doubled. */
function tidy(entries: MenuEntry[]): MenuEntry[] {
  const out: MenuEntry[] = [];
  for (const e of entries) {
    if (e === "separator" && (out.length === 0 || out.at(-1) === "separator")) continue;
    out.push(e);
  }
  if (out.at(-1) === "separator") out.pop();
  return out;
}

/** A right-click menu at the pointer: ↑/↓ move, Enter picks, Esc or a click outside
 * closes. Keys pressed in it never reach the page's shortcuts. Kept inside the window.
 * As the pull-down ``Menu``: a disabled entry says why under its label, a toggle shows
 * its check. */
export function ContextMenu({ x, y, label, entries, onClose }: Props) {
  const menu = useRef<HTMLDivElement>(null);
  const id = useId();
  const close = useRef(onClose);
  close.current = onClose; // a new function each render must not re-run the effect below
  const [place, setPlace] = useState({ left: x, top: y });

  useLayoutEffect(() => {
    const el = menu.current;
    if (!el) return;
    const edge = 8;
    setPlace({
      left: Math.max(edge, Math.min(x, window.innerWidth - el.offsetWidth - edge)),
      top: Math.max(edge, Math.min(y, window.innerHeight - el.offsetHeight - edge)),
    });
  }, [x, y]);

  useEffect(() => {
    menu.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus({ preventScroll: true });
    const shut = () => close.current();
    const away = (e: Event) => {
      if (!menu.current?.contains(e.target as Node)) shut();
    };
    document.addEventListener("mousedown", away);
    window.addEventListener("scroll", shut, true);
    window.addEventListener("resize", shut);
    return () => {
      document.removeEventListener("mousedown", away);
      window.removeEventListener("scroll", shut, true);
      window.removeEventListener("resize", shut);
    };
  }, []);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    e.stopPropagation();
    const items = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "Escape" || e.key === "Tab") onClose();
    else if (e.key === "ArrowDown") items[(at + 1) % items.length]?.focus();
    else if (e.key === "ArrowUp") items[(at - 1 + items.length) % items.length]?.focus();
    else return;
    e.preventDefault();
  };

  return createPortal(
    <div
      ref={menu}
      role="menu"
      aria-label={label}
      className="menu menu-context"
      style={{ position: "fixed", ...place }}
      onKeyDown={onKeyDown}
      onContextMenu={(e) => e.preventDefault()}
    >
      {tidy(entries).map((entry, i) =>
        entry === "separator" ? (
          <div key={i} role="separator" className="menu-separator" />
        ) : (
          <button
            key={i}
            type="button"
            role={entry.checked === undefined ? "menuitem" : "menuitemcheckbox"}
            aria-checked={entry.checked}
            className="menu-item"
            data-tip={entry.tip}
            disabled={entry.disabled}
            aria-describedby={entry.disabled && entry.reason ? `${id}-why-${i}` : undefined}
            tabIndex={-1}
            style={entry.indent ? { paddingLeft: `calc(4px + ${entry.indent} * 14px)` } : undefined}
            onClick={() => {
              onClose();
              entry.onSelect();
            }}
          >
            <span className="menu-check" aria-hidden="true">
              {entry.checked ? "✓" : ""}
            </span>
            {entry.icon && (
              <span className="menu-item-icon" aria-hidden="true">
                {entry.icon}
              </span>
            )}
            <span className="menu-item-text">
              {entry.label}
              {entry.disabled && entry.reason && (
                <span id={`${id}-why-${i}`} className="menu-reason" aria-hidden="true">
                  {entry.reason}
                </span>
              )}
            </span>
          </button>
        ),
      )}
    </div>,
    document.body,
  );
}
