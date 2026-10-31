/** What each Today section gets from the layout: its fold, and the header
 * attributes for dragging and for Option-Up / Option-Down, plus the moves for visible
 * Move up / Move down buttons. After a keyboard move the card may land in another
 * column (a new element): the focus goes back to its header button so the keys can move
 * it on. */
import { useEffect, useRef, useState } from "react";
import type { CardFrame } from "./frame";
import { useCardDrag } from "./useCardDrag";
import type { CardLayout } from "../useCardLayout";

export function useCardFrames(layout: CardLayout, drag: ReturnType<typeof useCardDrag>) {
  const refocus = useRef<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  useEffect(() => {
    const id = refocus.current;
    if (id === null) return;
    refocus.current = null;
    const slot = [...document.querySelectorAll<HTMLElement>(".today-slot")].find((el) => el.dataset.cardId === id);
    slot?.querySelector<HTMLButtonElement>(".card-header button, .tn-head button")?.focus();
  }, [layout.columns]);

  const shift = (id: string, title: string, by: -1 | 1) => {
    if (!layout.canMove(id, by)) return false;
    refocus.current = id;
    layout.move(id, by);
    setAnnouncement(`${title} moved ${by < 0 ? "up" : "down"}`);
    return true;
  };
  const frame = (id: string, title: string): CardFrame => ({
    fold: { folded: layout.collapsed(id), onToggle: () => layout.toggle(id) },
    headerProps: {
      ...drag.header(id),
      // Option-Up / Option-Down with the focus in a card's header moves the card on.
      onKeyDown: (e) => {
        if (!e.altKey || e.metaKey || e.ctrlKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
        e.preventDefault();
        shift(id, title, e.key === "ArrowUp" ? -1 : 1);
      },
    },
  });
  return { frame, announcement, shift };
}
