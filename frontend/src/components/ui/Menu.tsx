import {
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { ChevronDown } from "lucide-react";
import { createPortal } from "react-dom";

export type MenuEntry =
  | {
      label: string;
      onSelect: () => void;
      disabled?: boolean;
      /** Why the entry is disabled: shown under its label (and its accessible description). */
      reason?: string;
      /** A toggle: shown with a check mark (``menuitemcheckbox``). */
      checked?: boolean;
      /** A colour dot before the label (an archive's colour). */
      swatch?: string;
      /** A glyph before the label (the check mark's place is kept, so labels line up). */
      icon?: ReactNode;
      /** Nesting level (a tree in a menu): indents the entry, 0 is flush. */
      indent?: number;
    }
  | "separator";

type Props = {
  /** The trigger's accessible name and tooltip; also names the menu. */
  label: string;
  icon: ReactNode;
  entries: MenuEntry[];
  /** "end" aligns the menu's right edge with the trigger (toolbar menus). */
  align?: "start" | "end";
  className?: string;
  /** Show this beside the icon, in a wider trigger (the sidebar's archive menu). With
   * ``icon={null}`` it is a pull-down button: the text and a chevron ("Put in tray");
   * ``label`` still names it for assistive technology. */
  text?: ReactNode;
  /** The trigger's CSS class (default: a square icon button). */
  triggerClassName?: string;
};

/** A Mac pull-down menu behind an icon button: ↑/↓ move, Enter picks, Esc closes (the
 * focus goes back to the trigger), a click outside closes. Keys pressed in the menu
 * never reach the page's shortcuts. The menu is portalled to the body with fixed
 * positioning, so a scrolling column (``overflow: auto``) never clips it; it is kept
 * inside the window, flipping left or up when it would run off an edge. */
export function Menu({ label, icon, entries, align = "start", className, text, triggerClassName }: Props) {
  const [open, setOpen] = useState(false);
  const pullDown = icon == null && text != null;
  const menuId = useId();
  const wrap = useRef<HTMLSpanElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<CSSProperties>({ position: "fixed" });

  useLayoutEffect(() => {
    if (!open || !trigger.current || !menu.current) return;
    const t = trigger.current.getBoundingClientRect();
    const w = menu.current.offsetWidth;
    const h = menu.current.offsetHeight;
    const gap = 4;
    const edge = 8;
    let left = align === "end" ? t.right - w : t.left;
    left = Math.max(edge, Math.min(left, window.innerWidth - w - edge));
    let top = t.bottom + gap;
    if (top + h > window.innerHeight - edge && t.top - gap - h >= edge) top = t.top - gap - h;
    setPlace({ position: "fixed", top, left, right: "auto" });
  }, [open, align]);

  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus({ preventScroll: true });
    const inside = (n: EventTarget | null) =>
      !!n && (wrap.current?.contains(n as Node) || menu.current?.contains(n as Node));
    const away = (e: MouseEvent) => {
      if (!inside(e.target)) setOpen(false);
    };
    // A fixed menu would float away from its trigger when the page scrolls under it.
    const scrolled = (e: Event) => {
      if (!inside(e.target)) setOpen(false);
    };
    const resized = () => setOpen(false);
    document.addEventListener("mousedown", away);
    window.addEventListener("scroll", scrolled, true);
    window.addEventListener("resize", resized);
    return () => {
      document.removeEventListener("mousedown", away);
      window.removeEventListener("scroll", scrolled, true);
      window.removeEventListener("resize", resized);
    };
  }, [open]);

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    e.stopPropagation();
    const items = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "Escape") close(true);
    else if (e.key === "ArrowDown") items[(at + 1) % items.length]?.focus();
    else if (e.key === "ArrowUp") items[(at - 1 + items.length) % items.length]?.focus();
    else if (e.key === "Home") items[0]?.focus();
    else if (e.key === "End") items.at(-1)?.focus();
    else if (e.key === "Tab") close(false);
    else return;
    if (e.key !== "Tab") e.preventDefault();
  };

  return (
    <span ref={wrap} className={className ? `menu-wrap ${className}` : "menu-wrap"}>
      <button
        ref={trigger}
        type="button"
        className={triggerClassName ?? (pullDown ? "menu-button" : "icon-button")}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        data-tip={open || pullDown ? undefined : label}
        onClick={() => setOpen((o) => !o)}
      >
        {!pullDown && (
          <span className="icon-button-glyph" aria-hidden="true">
            {icon}
          </span>
        )}
        {pullDown ? <span className="menu-button-text">{text}</span> : text}
        {pullDown && <ChevronDown size={12} aria-hidden="true" />}
      </button>
      {open &&
        createPortal(
          <div
            id={menuId}
            ref={menu}
            role="menu"
            aria-label={label}
            className={`menu menu-${align}`}
            style={place}
            onKeyDown={onKeyDown}
          >
            {entries.map((entry, i) =>
              entry === "separator" ? (
                <div key={i} role="separator" className="menu-separator" />
              ) : (
                <button
                  key={i}
                  type="button"
                  role={entry.checked === undefined ? "menuitem" : "menuitemcheckbox"}
                  aria-checked={entry.checked}
                  className="menu-item"
                  disabled={entry.disabled}
                  aria-describedby={entry.disabled && entry.reason ? `${menuId}-why-${i}` : undefined}
                  tabIndex={-1}
                  style={entry.indent ? { paddingLeft: `calc(4px + ${entry.indent} * 14px)` } : undefined}
                  onClick={() => {
                    close(true);
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
                  {entry.swatch && <span className="menu-swatch" style={{ background: entry.swatch }} aria-hidden="true" />}
                  <span className="menu-item-text">
                    {entry.label}
                    {entry.disabled && entry.reason && (
                      <span id={`${menuId}-why-${i}`} className="menu-reason" aria-hidden="true">
                        {entry.reason}
                      </span>
                    )}
                  </span>
                </button>
              ),
            )}
          </div>,
          document.body,
        )}
    </span>
  );
}
