import { type KeyboardEvent, type ReactNode, type Ref, useCallback, useEffect, useId, useRef } from "react";

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
};

/** A Mac-style sheet over the native modal <dialog>: ``dialog[open]`` while ``open``.
 * Focus is trapped by the browser. Mounted only while open, so closing resets it.
 * The title and the footer are fixed; only the body between them scrolls. */
export function Sheet({ open, title, onClose, children, footer, ref, onKeyDown, className }: Props) {
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
  return (
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
      <h2 id={headingId} className="sheet-title">
        {title}
      </h2>
      <div className="sheet-body">{children}</div>
      {footer && <div className="sheet-footer">{footer}</div>}
    </dialog>
  );
}
