import { type KeyboardEvent, type ReactNode, type Ref, useCallback, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

type Props = {
  open: boolean;
  title: string;
  /** Esc or the dialog's own cancel event. Clicking the backdrop does nothing: a sheet
   * over a plan must be answered, never dismissed by a stray click. */
  onClose: () => void;
  children: ReactNode;
  /** The foot: Cancel first, the primary action last. It stays in view below the
   * body, which scrolls on its own when the content is taller than the window. */
  footer?: ReactNode;
  /** The underlying <dialog>, for callers that manage focus or timing themselves. */
  ref?: Ref<HTMLDialogElement>;
  /** Runs before the sheet's own Esc handling; ``preventDefault`` to take over. */
  onKeyDown?: (e: KeyboardEvent<HTMLDialogElement>) => void;
  className?: string;
  /** A line under the title (the rule sheet: what the rule is made from). */
  subtitle?: ReactNode;
  /** A × at the right of the title that closes the sheet like Esc. */
  closeButton?: boolean;
};

/** A Mac-style sheet over the native modal <dialog>: ``dialog[open]`` while ``open``.
 * Focus is trapped by the browser. Mounted only while open, so closing resets it.
 * The title and the footer are fixed; only the body between them scrolls. Rendered into the
 * page's body, so a sheet opened from inside another (a folder picker in the rule sheet)
 * never takes the outer one's styles; its events still reach its React parents. */
export function Sheet({ open, title, onClose, children, footer, ref, onKeyDown, className, subtitle, closeButton }: Props) {
  const inner = useRef<HTMLDialogElement | null>(null);
  const headingId = useId();
  const setRef = useCallback(
    (el: HTMLDialogElement | null) => {
      inner.current = el;
      if (typeof ref === "function") ref(el);
      else if (ref) ref.current = el;
    },
    [ref],
  );
  useEffect(() => {
    const dialog = inner.current;
    if (!open || !dialog) return;
    if (!dialog.open) dialog.showModal();
    // Like showModal in a real browser: the dialog itself has the focus unless a child takes it.
    if (!dialog.contains(document.activeElement)) dialog.focus();
    return () => {
      if (dialog.open) dialog.close();
    };
  }, [open]);
  if (!open) return null;
  return createPortal(
    <dialog
      ref={setRef}
      className={className ? `sheet ${className}` : "sheet"}
      aria-labelledby={headingId}
      tabIndex={-1}
      onCancel={(e) => {
        e.preventDefault();
        e.stopPropagation(); // a stacked sheet's Esc never closes the one underneath
        onClose();
      }}
      onKeyDown={(e) => {
        onKeyDown?.(e);
        if (!e.defaultPrevented && e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
      }}
    >
      {subtitle !== undefined || closeButton ? (
        <header className="sheet-head">
          <div className="sheet-head-text">
            <h2 id={headingId} className="sheet-title">
              {title}
            </h2>
            {subtitle !== undefined && <span className="sheet-subtitle">{subtitle}</span>}
          </div>
          {closeButton && (
            <button type="button" className="sheet-close" aria-label="Close" title="Close (Esc)" onClick={onClose}>
              ×
            </button>
          )}
        </header>
      ) : (
        <h2 id={headingId} className="sheet-title">
          {title}
        </h2>
      )}
      <div className="sheet-body">{children}</div>
      {footer && <div className="sheet-footer">{footer}</div>}
    </dialog>,
    document.body,
  );
}
