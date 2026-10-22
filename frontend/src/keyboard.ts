/** Shared rules for the single-key shortcuts. */
import { useEffect, useRef } from "react";

/** True while the user is typing: single-key shortcuts must not fire then. */
export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  if (target instanceof HTMLInputElement) {
    return !["checkbox", "radio", "button", "submit", "reset"].includes(target.type);
  }
  return false;
}

/** A modal dialog is open: page shortcuts are off, the dialog handles its own keys. */
export const dialogOpen = () => document.querySelector("dialog[open]") !== null;

export const isCmdEnter = (e: KeyboardEvent) => e.key === "Enter" && (e.metaKey || e.ctrlKey);

/** A plain key press (no modifiers) outside text fields and dialogs. */
export const isShortcut = (e: KeyboardEvent) =>
  !e.metaKey && !e.ctrlKey && !e.altKey && !isTyping(e.target) && !dialogOpen();

/** ``isShortcut`` for a control that may itself sit in an open dialog (Quick Look's
 * preview): its keys work when no dialog is open, or when it sits in the dialog the key
 * press happened in (the topmost one: the focus is trapped there). Behind a dialog,
 * or in a dialog under another one, they do not. */
export function isShortcutIn(e: KeyboardEvent, el: Element | null): boolean {
  if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return false;
  if (!dialogOpen()) return true;
  const own = el?.closest("dialog[open]");
  const target = e.target instanceof Element ? e.target.closest("dialog[open]") : null;
  return own != null && own === target;
}

/** Elements whose own Enter behaviour wins over the Enter = preview shortcut. */
export const OWN_ENTER =
  "button, a[href], summary, [role=option], select, textarea, input[type=checkbox]";

/** Listen for keydown on the document; the latest ``handler`` is always used.
 * Auto-repeated keydowns (a held key) never reach a shortcut handler. */
export function useKeydown(handler: (e: KeyboardEvent) => void) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      if (!e.repeat) ref.current(e);
    };
    document.addEventListener("keydown", listener);
    return () => document.removeEventListener("keydown", listener);
  }, []);
}

// Physical keys (``e.code``) currently down anywhere on the page (capture phase, so
// nothing can hide them). By code, not ``e.key``: the key value can change between
// keydown and keyup (Shift or Alt pressed meanwhile), which would leave it "held".
// macOS sends no keyup for other keys while Cmd is held, so releasing Meta clears all.
const held = new Set<string>();
if (typeof window !== "undefined") {
  window.addEventListener("keydown", (e) => held.add(e.code), true);
  window.addEventListener(
    "keyup",
    (e) => {
      if (e.key === "Meta") held.clear();
      else held.delete(e.code);
    },
    true,
  );
  window.addEventListener("blur", () => held.clear());
}

/** No key is held down right now. */
export const noKeysHeld = () => held.size === 0;
