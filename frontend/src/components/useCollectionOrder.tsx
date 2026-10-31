import { type DragEvent as ReactDragEvent, type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  type CollectionRow,
  errorText,
  useMoveCollectionOrder,
  useSetCollectionParent,
} from "../api/client";
import { COLLECTION_DRAG_TYPE, type DropTarget, readDragCollection } from "../dnd";
import { visible } from "../text";
import { changeToast } from "./collectionText";
import {
  collectionMoveRunning,
  dropZone,
  endCollectionMove,
  isWithin,
  moveRefusal,
  movedText,
  recreatedLinks,
  siblingsOf,
  startCollectionMove,
} from "./collectionTree";
import { ContextMenu } from "./ui/ContextMenu";
import { useToast } from "./Toasts";

/** Changing the order of collections and where they sit (the owner's order; Starred and
 * Important stay first and are never offered). One place for the sidebar, the collections
 * page and the collection's ⋯ menu. A collection dragged onto a row: the top third puts
 * it before the row, the bottom third after it (a drop line; into the row's parent when
 * that is another one), the middle third inside it (the row is highlighted). The heading
 * and the page's top strip take it to the top level, last. Keyboard: Alt+↑/↓ (and Alt+←
 * out one level) or Move up / Move down / Move out one level in the menus. Each move is
 * said in a toast (a polite live region). */

/** Dropping a collection on another moves it inside; on the section caption, to the
 * top. No confirm (as for member and group changes): the Ongoing sync only moves
 * app-owned entries, journaled, and moving it back reverses it; the toast says what
 * Ongoing did. A cycle or a closed parent is refused before the drop. */
export function useMoveCollection(list: CollectionRow[], onMoved: (target: CollectionRow | null) => void) {
  const setParent = useSetCollectionParent();
  const toast = useToast();
  const navigate = useNavigate();
  const find = (id: number) => list.find((c) => c.id === id) ?? null;
  const accept = (target: CollectionRow | null) => (id: number) => {
    const dragged = find(id);
    if (!dragged) return false; // not one this sidebar shows
    const refusal = moveRefusal(list, dragged, target);
    if (refusal) return visible(refusal);
    return collectionMoveRunning() ? "Another move is still running" : true;
  };
  const move = (target: CollectionRow | null) => (id: number) => {
    const dragged = find(id);
    if (!dragged || !startCollectionMove()) return; // shared with the page's Move to…
    const name = visible(dragged.name);
    const where = target === null ? null : visible(target.name);
    // The collection page shows the batch that ran (LastChange) and Activity has it.
    const open = { label: "Open", run: () => navigate(`/open-collection/${id}`) };
    setParent
      .mutateAsync({ id, parent_id: target?.id ?? null })
      .then((result) => {
        onMoved(target);
        toast({ ...changeToast(movedText(name, where, recreatedLinks(result)), result), actions: [open] });
      })
      .catch((err) => {
        const to = where === null ? "to the top level" : `into ${where}`;
        toast({ kind: "error", text: `Could not move ${name} ${to}: ${visible(errorText(err))}` });
      })
      .finally(endCollectionMove);
  };
  return { accept, move };
}


type Zone = "before" | "after";

export function useCollectionOrder(list: readonly CollectionRow[]) {
  const mutation = useMoveCollectionOrder();
  const toast = useToast();
  const running = useRef(false); // synchronous: a second drop sees it at once
  const find = (id: number) => list.find((c) => c.id === id) ?? null;

  /** Put ``id`` before or after ``anchor`` (a sibling, or a row of another parent: it goes
   * into that parent too); ``said``: the toast text when only the order changed. */
  const place = (id: number, anchor: number, where: Zone, said: string) => {
    const c = find(id);
    if (!c || running.current) return;
    running.current = true;
    const call = where === "before" ? { id, before_id: anchor } : { id, after_id: anchor };
    mutation
      .mutateAsync(call)
      .then((result) => {
        const now = result.collection.parent_id ?? null;
        if (now === (c.parent_id ?? null)) return toast({ kind: "info", text: said });
        const into = now === null ? null : visible(result.collection.path.slice(-2, -1)[0] ?? "");
        toast(changeToast(movedText(visible(c.name), into, recreatedLinks(result)), result));
      })
      .catch((err) => toast({ kind: "error", text: `Could not move ${visible(c.name)}: ${visible(errorText(err))}` }))
      .finally(() => {
        running.current = false;
      });
  };

  /** Whether a drag of ``id`` may be put beside the row ``target``: any other collection
   * unless the row's parent would be inside the dragged one (a cycle). */
  const sibling = (id: number, target: CollectionRow) => {
    const dragged = find(id);
    return !!dragged && dragged.id !== target.id && !isWithin(list, target.id, dragged.id);
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
  const parentRow = (c: CollectionRow) => (c.parent_id == null ? null : find(c.parent_id));
  const canOut = (c: CollectionRow) => parentRow(c) !== null;
  /** Out of its parent, to the parent's level, right after it. */
  const out = (c: CollectionRow) => {
    const parent = parentRow(c);
    if (!parent) return;
    const to = parent.parent_id == null ? "the top level" : visible(find(parent.parent_id)?.name ?? "");
    place(c.id, parent.id, "after", `Moved ${visible(c.name)} out of ${visible(parent.name)} to ${to}`);
  };
  return { sibling, drop, canStep, step, canOut, out };
}

export type CollectionOrder = ReturnType<typeof useCollectionOrder>;

/** Alt+↑ / Alt+↓ on a focused collection row moves it; the row keeps the focus. */
export function orderKeys(order: CollectionOrder, c: CollectionRow) {
  return (e: KeyboardEvent) => {
    if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown" && e.key !== "ArrowLeft")) return;
    e.preventDefault();
    if (e.key === "ArrowLeft") {
      order.out(c);
      return;
    }
    const dir = e.key === "ArrowUp" ? -1 : 1;
    if (!order.canStep(c, dir)) return;
    const row = e.currentTarget as HTMLElement;
    order.step(c, dir);
    // a moved row can lose the focus when the browser re-inserts it; found again in its
    // own list (the sidebar and Browse's tree both have a row for it)
    const list = row.closest("nav") ?? document;
    setTimeout(() => {
      const again = list.querySelector<HTMLElement>(`[data-collection-id="${c.id}"]`) ?? row;
      if (document.activeElement !== again) again.focus();
    }, 50);
  };
}

/** The drop line on a row: spread the props on the row (after its own drop props:
 * ``inner``) and mark it with ``zone`` (CSS shows the line). A collection dragged over
 * the top or bottom third of a row is put before or after it; over the middle third the
 * drag is the row's own (``inner``: files added, a collection moved inside). */
export function useReorderRow(order: CollectionOrder, c: CollectionRow, inner: DropTarget["props"] | null) {
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
    const z = dropZone(e.clientY, e.currentTarget.getBoundingClientRect());
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

/** A right-click menu with Move up / Move down for a collection row; ``first``: entries
 * that come before them (Browse's tree: Open, New collection inside…). */
export function useOrderMenu(order: CollectionOrder, first?: (c: CollectionRow) => { label: string; onSelect: () => void }[]) {
  const [menu, setMenu] = useState<{ x: number; y: number; c: CollectionRow } | null>(null);
  const element: ReactNode = menu && (
    <ContextMenu
      x={menu.x}
      y={menu.y}
      label={`Order of ${visible(menu.c.name)}`}
      entries={[
        ...(first?.(menu.c) ?? []),
        "separator",
        { label: "Move up", disabled: !order.canStep(menu.c, -1), reason: "Already first", onSelect: () => order.step(menu.c, -1) },
        { label: "Move down", disabled: !order.canStep(menu.c, 1), reason: "Already last", onSelect: () => order.step(menu.c, 1) },
        ...(order.canOut(menu.c) ? [{ label: "Move out one level", onSelect: () => order.out(menu.c) }] : []),
      ]}
      onClose={() => setMenu(null)}
    />
  );
  return {
    element,
    onContextMenu: (c: CollectionRow) => (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation(); // a nested row's menu, not its parent's
      setMenu({ x: e.clientX, y: e.clientY, c });
    },
  };
}

/** Whether a collection is being dragged in this page right now (a strip that only exists
 * for such a drag shows while it lasts). */
export function useCollectionDragging(): boolean {
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    const start = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes(COLLECTION_DRAG_TYPE)) setDragging(true);
    };
    const stop = () => setDragging(false);
    document.addEventListener("dragstart", start);
    document.addEventListener("dragend", stop);
    document.addEventListener("drop", stop);
    return () => {
      document.removeEventListener("dragstart", start);
      document.removeEventListener("dragend", stop);
      document.removeEventListener("drop", stop);
    };
  }, []);
  return dragging;
}
