/** Space opens Quick Look on the list's current document (a plain Space outside text
 * fields and controls, with no dialog open). Inside, Space or Esc closes it and ←/→ (or
 * j/k, ↑/↓) move through the list, moving the list's own selection along. */
import { createElement, type ReactNode, useEffect, useRef, useState } from "react";
import { dialogOpen, isShortcut, isTyping, useKeydown } from "../keyboard";
import { useDialogStatus } from "./FileLaunch";
import { type QLFile, QuickLook } from "./QuickLook";
import { useToast } from "./Toasts";
import { isTrashKey } from "./Trash";

export type { QLFile } from "./QuickLook";

/** What a screen's Trash gets from Quick Look (see ``onTrash``): ``close`` as the
 * confirm opens, ``report`` a refusal on the status line (a toast when Quick Look was
 * closed meanwhile, so it is never lost), ``reopen`` after Cancel from that confirm. */
export type QuickLookTrashUI = { close: () => void; report: (text: string) => void; reopen: () => void };

/** Controls whose own Space wins (press, toggle, open); list rows marked
 * ``data-quicklook`` give it to Quick Look. */
const OWN_SPACE = "button, a[href], summary, select, textarea, input, [role=option], [contenteditable]";

const NEXT = new Set(["ArrowRight", "ArrowDown", "j"]);
const PREVIOUS = new Set(["ArrowLeft", "ArrowUp", "k"]);

export type QuickLookState = {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  /** The <QuickLook> overlay while open, else null: render it anywhere in the screen. */
  view: ReactNode;
};

export function useQuickLook(
  files: QLFile[],
  index: number,
  setIndex: (index: number) => void,
  /** ``canOpen``: checked at each Space; false keeps Quick Look closed (e.g. while a
   * file call is in flight). ``onTrash``: Trash for the shown file (the bin and ⌘⌫);
   * the screen starts its Trash flow with ``ui``: Quick Look stays open through the dry
   * run, ``ui.close`` closes it as the confirm opens, and ``ui.report`` shows a refusal
   * on its status line. ``trashRefusal``: why the shown file cannot be trashed (shown,
   * never silent); ``trashBusy``: the screen's Trash call is running. */
  options: {
    canOpen?: () => boolean;
    onTrash?: (file: QLFile, ui: QuickLookTrashUI) => void;
    trashRefusal?: (file: QLFile) => string | null;
    trashBusy?: boolean;
  } = {},
): QuickLookState {
  const [wanted, setWanted] = useState(false);
  const isOpen = wanted && files.length > 0;
  const at = Math.max(0, Math.min(files.length - 1, index));
  // Where the focus was when it opened: it goes back there on close.
  const back = useRef<HTMLElement | null>(null);
  // Open as the Trash flow sees it (a dry run answers later than a key press).
  const openRef = useRef(false);
  openRef.current = isOpen;
  const toast = useToast();

  useEffect(() => {
    if (wanted && files.length === 0) setWanted(false);
  }, [wanted, files.length]);
  // Closed for Trash's confirm: the focus is that dialog's, and ``back`` is kept for
  // the reopen after Cancel (or the close that follows the apply).
  const forDialog = useRef(false);
  useEffect(() => {
    if (isOpen || !back.current) return;
    if (forDialog.current && dialogOpen()) return;
    const el = back.current;
    back.current = null;
    forDialog.current = false;
    if (el.isConnected && !dialogOpen()) el.focus();
  }, [isOpen]);
  // Quick Look's status line (owned here, so Trash's refusal can reach it).
  const status = useDialogStatus();

  const show = () => {
    const active = document.activeElement;
    back.current = active instanceof HTMLElement && active !== document.body ? active : null;
    forDialog.current = false;
    setWanted(true);
  };
  const allowed = () => files.length > 0 && options.canOpen?.() !== false;
  const open = () => {
    if (allowed()) show();
  };
  const close = () => setWanted(false);
  const { onTrash, trashRefusal } = options;
  const shown = files[at] as QLFile | undefined;
  const refusal = shown && trashRefusal ? trashRefusal(shown) : null;
  const trash = onTrash
    ? () => {
        if (!shown) return;
        if (refusal) {
          status.report({ kind: "error", text: refusal });
          return;
        }
        onTrash(shown, {
          close: () => {
            forDialog.current = true;
            setWanted(false);
          },
          report: (text) => {
            if (openRef.current) status.report({ kind: "error", text });
            else toast({ kind: "error", text }); // closed meanwhile: never lost
          },
          reopen: () => {
            forDialog.current = false;
            if (files.length > 0) setWanted(true);
            else if (back.current?.isConnected) back.current.focus();
          },
        });
      }
    : undefined;
  const step = (delta: number) => {
    const next = Math.max(0, Math.min(files.length - 1, at + delta));
    if (next !== at) setIndex(next);
  };

  useKeydown((e) => {
    if (!isOpen) {
      if (e.key !== " " || !isShortcut(e) || files.length === 0) return;
      const target = e.target instanceof Element ? e.target : null;
      if (target?.closest(OWN_SPACE) && !target.closest("[data-quicklook]")) return;
      // refused (``canOpen``): the Space is left to the page or the focused control
      if (!allowed()) return;
      e.preventDefault();
      show();
      return;
    }
    if (trash && isTrashKey(e, document.querySelector("dialog.quicklook[open]"))) {
      e.preventDefault();
      trash();
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
    // Space on one of Quick Look's own buttons (Close, Next, zoom…) presses that button.
    if (e.key === " " && e.target instanceof Element && e.target.closest("dialog button")) return;
    if (e.key === " " || e.key === "Escape") close();
    else if (NEXT.has(e.key)) step(1);
    else if (PREVIOUS.has(e.key)) step(-1);
    else return;
    e.preventDefault();
  });

  const view = isOpen
    ? createElement(QuickLook, {
        files,
        index: at,
        onIndex: setIndex,
        onClose: close,
        status,
        trash: trash && { run: trash, refusal, busy: !!options.trashBusy },
      })
    : null;
  return { isOpen, open, close, view };
}
