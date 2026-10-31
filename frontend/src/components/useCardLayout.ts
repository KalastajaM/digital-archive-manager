/** Today's card layout: the order of the cards in their columns and which are folded,
 * kept in this browser's localStorage (``dam.today.layout.new.v1``).
 *
 * The order is stored as one sequence, top to bottom, with ``"|"`` between columns, so
 * Move up and Move down walk through every card (past the bottom of a column to the top
 * of the next). A saved card that no longer exists (a removed tray) is dropped; a card
 * the saved order does not know (a new tray) goes to the end of its default column.
 * Every storage access is in try/catch: private windows and blocked site data throw. */
import { useCallback, useMemo, useState } from "react";
import { archiveKey } from "../api/client";

export const LAYOUT_KEY = "dam.today.layout.new.v1";
/** A dragged Today card: never ``application/x-dam-files``, so a card can never be
 * dropped as files and files never as a card. */
export const CARD_DRAG_TYPE = "application/x-dam-card";

const BREAK = "|";

type Saved = { order: string[] | null; collapsed: Record<string, boolean> };
export type Place = { before: string } | { after: string } | { column: number };

export type CardLayout = {
  /** The card ids per column, in order. */
  columns: string[][];
  collapsed: (id: string) => boolean;
  toggle: (id: string) => void;
  /** Whether Move up (-1) or Move down (+1) can move the card further. */
  canMove: (id: string, by: -1 | 1) => boolean;
  move: (id: string, by: -1 | 1) => void;
  /** A drop: before or after another card, or at the end of a column. */
  place: (id: string, where: Place) => void;
  /** Back to the default order and folds; the saved layout is forgotten. */
  reset: () => void;
};

const EMPTY: Saved = { order: null, collapsed: {} };

function read(key: string): Saved {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(archiveKey(key));
  } catch {
    return EMPTY;
  }
  if (!raw) return EMPTY;
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object") return EMPTY;
    const { order, collapsed } = value as Record<string, unknown>;
    const folds: Record<string, boolean> = {};
    if (collapsed && typeof collapsed === "object" && !Array.isArray(collapsed)) {
      for (const [id, v] of Object.entries(collapsed)) if (typeof v === "boolean") folds[id] = v;
    }
    return {
      order: Array.isArray(order) ? order.filter((t): t is string => typeof t === "string") : null,
      collapsed: folds,
    };
  } catch {
    return EMPTY;
  }
}

function write(key: string, saved: Saved | null) {
  try {
    if (saved === null) localStorage.removeItem(archiveKey(key));
    else localStorage.setItem(archiveKey(key), JSON.stringify(saved));
  } catch {
    // Not saved: the layout still applies until the page reloads.
  }
}

/** The columns from the saved sequence and the defaults (see the module comment). */
function resolve(order: string[] | null, defaults: string[][]): string[][] {
  if (!order) return defaults.map((c) => [...c]);
  const known = new Set(defaults.flat());
  const columns: string[][] = defaults.map(() => []);
  const seen = new Set<string>();
  let at = 0;
  for (const token of order) {
    if (token === BREAK) {
      at = Math.min(at + 1, columns.length - 1);
    } else if (known.has(token) && !seen.has(token)) {
      seen.add(token);
      columns[at].push(token);
    }
  }
  defaults.forEach((column, i) => {
    for (const id of column) if (!seen.has(id)) columns[i].push(id);
  });
  return columns;
}

const sequence = (columns: string[][]) => columns.flatMap((c, i) => (i === 0 ? c : [BREAK, ...c]));

/** ``defaults``: the card ids per column in their default order. ``defaultCollapsed``:
 * the cards folded until the user says otherwise. ``hidden``: cards not shown now (they
 * keep their place); Move up and Move down step over them. */
export function useCardLayout(
  defaults: string[][],
  defaultCollapsed: Record<string, boolean> = {},
  hidden: string[] = [],
  key: string = LAYOUT_KEY,
): CardLayout {
  const [saved, setSaved] = useState<Saved>(() => read(key));
  const defaultsKey = JSON.stringify(defaults);
  // Keyed by the defaults' value: callers pass a new array on every render.
  const columns = useMemo(() => resolve(saved.order, JSON.parse(defaultsKey) as string[][]), [saved.order, defaultsKey]);

  // Saved folds and places are pruned to the cards that exist (a removed tray, or a card
  // the look no longer has, goes).
  const update = useCallback(
    (next: Saved) => {
      const known = new Set((JSON.parse(defaultsKey) as string[][]).flat());
      const folds = Object.fromEntries(Object.entries(next.collapsed).filter(([id]) => known.has(id)));
      const order = next.order && next.order.filter((t) => t === BREAK || known.has(t));
      const pruned = { order, collapsed: folds };
      setSaved(pruned);
      write(key, pruned);
    },
    [defaultsKey, key],
  );

  const collapsed = (id: string) => saved.collapsed[id] ?? defaultCollapsed[id] ?? false;
  // The saved order as it is: folding never freezes the default order (null stays null).
  const toggle = (id: string) =>
    update({ order: saved.order, collapsed: { ...saved.collapsed, [id]: !collapsed(id) } });

  const skip = new Set(hidden);
  /** A move goes past the hidden cards to the first shown card or column break. */
  const canMove = (id: string, by: -1 | 1) => {
    const seq = sequence(columns);
    const i = seq.indexOf(id);
    if (i < 0) return false;
    for (let j = i + by; j >= 0 && j < seq.length; j += by) if (!skip.has(seq[j])) return true;
    return false;
  };
  const move = (id: string, by: -1 | 1) => {
    if (!canMove(id, by)) return;
    const seq = sequence(columns);
    let i = seq.indexOf(id);
    // Swap past each hidden card, then once with the shown card or break beyond them.
    for (;;) {
      const next = seq[i + by];
      [seq[i], seq[i + by]] = [next, seq[i]];
      i += by;
      if (!skip.has(next)) break;
    }
    update({ order: seq, collapsed: saved.collapsed });
  };
  const place = (id: string, where: Place) => {
    const all = columns.flat();
    if (!all.includes(id)) return;
    const target = "column" in where ? null : "before" in where ? where.before : where.after;
    if (target === id) return;
    if (target !== null && !all.includes(target)) return;
    if ("column" in where && (where.column < 0 || where.column >= columns.length)) return;
    const next = columns.map((c) => c.filter((x) => x !== id));
    if ("column" in where) next[where.column].push(id);
    else {
      const column = next.find((c) => c.includes(target!))!;
      column.splice(column.indexOf(target!) + ("after" in where ? 1 : 0), 0, id);
    }
    update({ order: sequence(next), collapsed: saved.collapsed });
  };
  const reset = () => {
    setSaved(EMPTY);
    write(key, null);
  };

  return { columns, collapsed, toggle, canMove, move, place, reset };
}
