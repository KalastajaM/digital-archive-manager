import { type DragEvent as ReactDragEvent, type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { type CollectionRow, errorText, useMoveCollectionOrder } from "../api/client";
import { type DropTarget, readDragCollection } from "../dnd";
import { visible } from "../text";
import { dropZone, siblingsOf } from "./collectionTree";
import { ContextMenu } from "./ui/ContextMenu";
import { useToast } from "./Toasts";

/** Changing the order of collections among their siblings (the owner's order; Starred
 * and Important stay first and are never offered). One place for the sidebar, the
 * collections page and the collection's ⋯ menu: drag with a drop line, Alt+↑/↓ and
 * "Move up" / "Move down". Each move is said in a toast (a polite live region). */

type Zone = "before" | "after";

export function useCollectionOrder(list: readonly CollectionRow[]) {
  const mutation = useMoveCollectionOrder();
  const toast = useToast();
  const running = useRef(false); // synchronous: a second drop sees it at once
  const find = (id: number) => list.find((c) => c.id === id) ?? null;

  /** Put ``id`` before or after the sibling ``anchor``; ``said``: the toast text. */
  const place = (id: number, anchor: number, where: Zone, said: string) => {
    const c = find(id);
    if (!c || running.current) return;
    running.current = true;
    const call = where === "before" ? { id, before_id: anchor } : { id, after_id: anchor };
    mutation
      .mutateAsync(call)
      .then(() => toast({ kind: "info", text: said }))
      .catch((err) => toast({ kind: "error", text: `Could not move ${visible(c.name)}: ${visible(errorText(err))}` }))
      .finally(() => {
        running.current = false;
      });
  };

  /** A sibling a drag of ``id`` may be put beside (never itself or another parent's). */
  const sibling = (id: number, target: CollectionRow) => {
    const dragged = find(id);
    return !!dragged && dragged.id !== target.id && (dragged.parent_id ?? null) === (target.parent_id ?? null);
  };

  const drop = (id: number, target: CollectionRow, where: Zone) =>
    place(id, target.id, where, `Moved ${visible(find(id)?.name ?? "")} ${where} ${visible(target.name)}`);

  const canStep = (c: CollectionRow, dir: -1 | 1) => {
    const sibs = siblingsOf(list, c);
    const i = sibs.findIndex((x) => x.id === c.id);
    return i >= 0 && i + dir >= 0 && i + dir < sibs.length;
  };
  const step = (c: CollectionRow, dir: -1 | 1) => {
    if (!canStep(c, dir)) return;
    const sibs = siblingsOf(list, c);
    const to = sibs[sibs.findIndex((x) => x.id === c.id) + dir];
    place(c.id, to.id, dir < 0 ? "before" : "after", `Moved ${visible(c.name)} ${dir < 0 ? "up" : "down"}`);
  };
  return { sibling, drop, canStep, step };
}

export type CollectionOrder = ReturnType<typeof useCollectionOrder>;

/** Alt+↑ / Alt+↓ on a focused collection row moves it; the row keeps the focus. */
export function orderKeys(order: CollectionOrder, c: CollectionRow) {
  return (e: KeyboardEvent) => {
    if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault();
    const dir = e.key === "ArrowUp" ? -1 : 1;
    if (!order.canStep(c, dir)) return;
    const row = e.currentTarget as HTMLElement;
    order.step(c, dir);
    // a moved row can lose the focus when the browser re-inserts it
    setTimeout(() => {
      const again = document.querySelector<HTMLElement>(`[data-collection-id="${c.id}"]`) ?? row;
      if (document.activeElement !== again) again.focus();
    }, 50);
  };
}

/** The drop line on a row: spread the props on the row (after its own drop props, when
 * it has some: ``inner``) and mark it with ``zone`` (CSS shows the line). A collection
 * dragged over the edge of a sibling is put before or after it; anywhere else the drag
 * is the row's own (``inner``: files added, a collection moved inside). ``halves``: no
 * middle, for rows that only reorder. */
export function useReorderRow(order: CollectionOrder, c: CollectionRow, inner: DropTarget["props"] | null, halves = false) {
  const [zone, setZone] = useState<Zone | null>(null);
  useEffect(() => {
    const end = () => setZone(null);
    document.addEventListener("dragend", end, true);
    document.addEventListener("drop", end, true);
    return () => {
      document.removeEventListener("dragend", end, true);
      document.removeEventListener("drop", end, true);
    };
  }, []);
  const zoneOf = (e: ReactDragEvent): { id: number; zone: Zone } | null => {
    const id = readDragCollection(e);
    if (id === null || !order.sibling(id, c)) return null;
    const z = dropZone(e.clientY, e.currentTarget.getBoundingClientRect(), halves);
    return z === null ? null : { id, zone: z };
  };
  const props = {
    onDragEnter: (e: ReactDragEvent) => {
      const hit = zoneOf(e);
      setZone(hit?.zone ?? null);
      if (hit) e.preventDefault(); // (the inner target keeps its enter/leave count)
      inner?.onDragEnter(e);
    },
    onDragOver: (e: ReactDragEvent) => {
      const hit = zoneOf(e);
      setZone(hit?.zone ?? null);
      if (hit) {
        e.preventDefault();
        e.stopPropagation();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
      } else inner?.onDragOver(e);
    },
    onDragLeave: (e: ReactDragEvent) => {
      setZone(null);
      inner?.onDragLeave(e);
    },
    onDrop: (e: ReactDragEvent) => {
      const hit = zoneOf(e);
      setZone(null);
      if (hit) {
        e.preventDefault();
        e.stopPropagation();
        order.drop(hit.id, c, hit.zone);
      } else inner?.onDrop(e);
    },
  };
  // the inner highlight ("move inside") is off while the line shows
  const mark = zone ? { "data-reorder": zone, "data-drop": undefined, "data-tip": undefined } : {};
  return { zone, props: { ...(inner ?? {}), ...props, ...mark } };
}

/** A right-click menu with Move up / Move down for a collection row. */
export function useOrderMenu(order: CollectionOrder) {
  const [menu, setMenu] = useState<{ x: number; y: number; c: CollectionRow } | null>(null);
  const element: ReactNode = menu && (
    <ContextMenu
      x={menu.x}
      y={menu.y}
      label={`Order of ${visible(menu.c.name)}`}
      entries={[
        { label: "Move up", disabled: !order.canStep(menu.c, -1), onSelect: () => order.step(menu.c, -1) },
        { label: "Move down", disabled: !order.canStep(menu.c, 1), onSelect: () => order.step(menu.c, 1) },
      ]}
      onClose={() => setMenu(null)}
    />
  );
  return {
    element,
    onContextMenu: (c: CollectionRow) => (e: React.MouseEvent) => {
      e.preventDefault();
      setMenu({ x: e.clientX, y: e.clientY, c });
    },
  };
}
