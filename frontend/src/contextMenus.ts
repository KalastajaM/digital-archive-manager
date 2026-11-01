/** Right-click menus app-wide: the browser's own menu is off everywhere except where text
 * is typed (text inputs, textareas, editable text: copy, paste and spelling still work)
 * or read to copy (``data-native-menu``: a file's text), and Shift+F10 or the ContextMenu key opens the focused element's own menu (a
 * ``contextmenu`` event at its lower left). The PDF preview is a frame of its own: its
 * viewer keeps its menu, which the app cannot replace. */
import { useEffect } from "react";

/** Where text is typed or copied: the browser's menu stays there. */
function editable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable || target.closest("[contenteditable=''], [contenteditable='true'], [data-native-menu]")) return true;
  if (target instanceof HTMLTextAreaElement) return true;
  if (target instanceof HTMLInputElement) {
    return !["checkbox", "radio", "button", "submit", "reset", "range", "color", "file", "image"].includes(target.type);
  }
  return false;
}

const isMenuKey = (e: KeyboardEvent) => e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey);

export function useContextMenuKeys() {
  useEffect(() => {
    const native = (e: MouseEvent) => {
      if (!editable(e.target)) e.preventDefault();
    };
    const keys = (e: KeyboardEvent) => {
      if (!isMenuKey(e) || editable(e.target)) return;
      const el = e.target instanceof HTMLElement ? e.target : null;
      if (!el || el === document.body) return;
      e.preventDefault();
      const box = el.getBoundingClientRect();
      el.dispatchEvent(
        new MouseEvent("contextmenu", {
          bubbles: true,
          cancelable: true,
          clientX: Math.round(box.left + 8),
          clientY: Math.round(box.bottom - 4),
        }),
      );
    };
    // bubbling: a row's own handler has run (and opened its menu) before the default goes
    document.addEventListener("contextmenu", native);
    document.addEventListener("keydown", keys);
    return () => {
      document.removeEventListener("contextmenu", native);
      document.removeEventListener("keydown", keys);
    };
  }, []);
}
