/** Drag and drop of Today's cards (Classic) and sections (New) by their headers. */
import { type DragEvent, useState } from "react";
import { DRAG_TYPE } from "../../dnd";
import { CARD_DRAG_TYPE, type CardLayout, type Place } from "../useCardLayout";

/** Whether a drag is a Today card: it carries ``CARD_DRAG_TYPE`` and no files (a file
 * drag is never taken as a card, even with a card type beside its files). */
export function isCardDrag(e: DragEvent): boolean {
  const types = Array.from(e.dataTransfer?.types ?? []);
  return types.includes(CARD_DRAG_TYPE) && !types.includes(DRAG_TYPE);
}

type DropAt = { id: string; side: "before" | "after" } | { column: number };

/** Drag and drop of the cards by their headers, with where a drop would land. */
export function useCardDrag(layout: CardLayout) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [dropAt, setDropAt] = useState<DropAt | null>(null);
  const end = () => {
    setDragging(null);
    setDropAt(null);
  };
  const over = (e: DragEvent, at: DropAt) => {
    if (!isCardDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "move";
    setDropAt((now) => (JSON.stringify(now) === JSON.stringify(at) ? now : at));
  };
  const drop = (e: DragEvent, where: Place) => {
    if (!isCardDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    const id = e.dataTransfer.getData(CARD_DRAG_TYPE);
    if (id) layout.place(id, where);
    end();
  };
  /** Above or below the middle of the card under the pointer. */
  const side = (e: DragEvent): "before" | "after" => {
    const box = e.currentTarget.getBoundingClientRect();
    return box.height > 0 && e.clientY > box.top + box.height / 2 ? "after" : "before";
  };
  return {
    dragging,
    dropAt,
    header: (id: string) => ({
      draggable: true,
      onDragStart: (e: DragEvent) => {
        // A link or button inside the header keeps its own drag (or none).
        if (e.target !== e.currentTarget) return;
        e.dataTransfer.setData(CARD_DRAG_TYPE, id);
        e.dataTransfer.effectAllowed = "move";
        setDragging(id);
      },
      onDragEnd: end,
    }),
    slot: (id: string) => ({
      onDragOver: (e: DragEvent) => over(e, { id, side: side(e) }),
      onDrop: (e: DragEvent) => {
        const at = side(e);
        drop(e, at === "before" ? { before: id } : { after: id });
      },
    }),
    // Over the column itself (a gap between cards, or under the last one): before the
    // first card whose middle is below the pointer, else at the end of the column.
    column: (column: number) => {
      const gap = (e: DragEvent): string | null => {
        const slots = e.currentTarget.querySelectorAll<HTMLElement>(":scope > .today-slot");
        for (const slot of slots) {
          const box = slot.getBoundingClientRect();
          if (box.height > 0 && e.clientY < box.top + box.height / 2) return slot.dataset.cardId ?? null;
        }
        return null;
      };
      return {
        onDragOver: (e: DragEvent) => {
          const id = gap(e);
          over(e, id === null ? { column } : { id, side: "before" });
        },
        onDrop: (e: DragEvent) => {
          const id = gap(e);
          drop(e, id === null ? { column } : { before: id });
        },
      };
    },
  };
}
