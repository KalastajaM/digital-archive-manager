/** The collection tree beside Browse's panes (the New look): Important and Starred first, then
 * the open collections as they nest, in their own order. A click lists the collection's files
 * in Browse (a `collection:` search, or `is:starred` / `is:important`); files dropped on a
 * collection are added to it, as on the sidebar's rows.
 *
 * Keyboard (the tree view pattern, as the folder tree): ↑ and ↓ move, → opens a collection
 * (or steps into it), ← closes it (or steps out), Home and End go to the first and last, Enter
 * picks. */
import { Archive, ChevronRight, Layers, Plus } from "lucide-react";
import { type KeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode, useEffect, useState } from "react";
import { type CollectionRow, useCollections } from "../api/client";
import type { ScopePick, ScopeState } from "../browseScope";
import { readDragFiles, readDragSource, useDropTarget } from "../dnd";
import { visible } from "../text";
import { childrenOf } from "./collectionTree";
import { ImportantGlyph, StarGlyph } from "./MarkIcons";
import { DeleteCollectionSheet } from "./DeleteCollectionSheet";
import { MergeCollectionSheet } from "./MergeCollectionSheet";
import { NewCollectionSheet } from "./NewCollectionSheet";
import { useToast } from "./Toasts";
import { IconButton } from "./ui/IconButton";
import { useAddToCollection } from "./useAddToCollection";
import { useCollectionOrder, useOrderMenu } from "./useCollectionOrder";

type Pick = (pick: ScopePick, add: boolean) => void;

type Shared = {
  kids: Map<number | null, CollectionRow[]>;
  folded: Set<number>;
  toggle: (id: number, open?: boolean) => void;
  focusKey: string;
  setFocusKey: (key: string) => void;
  active: ScopeState;
  onPick: Pick;
  collect: ReturnType<typeof useAddToCollection>;
  /** A collection row's right-click menu (Open, New collection inside…, the order). */
  onMenu: (c: CollectionRow) => (e: ReactMouseEvent) => void;
};

const ICON = { size: 14, strokeWidth: 1.75, "aria-hidden": true } as const;

/** One row: the tree item, its look and its keys. ``kids`` and ``onToggle`` only for a
 * collection with collections in it. */
function Row({
  rowKey,
  name,
  icon,
  level,
  current,
  expanded,
  parentKey,
  firstChildKey,
  onToggle,
  onPick,
  shared,
  dropProps,
  onContextMenu,
  closed,
  children,
}: {
  rowKey: string;
  name: string;
  icon: ReactNode;
  level: number;
  current: boolean;
  expanded?: boolean;
  parentKey?: string;
  firstChildKey?: string;
  onToggle?: (open?: boolean) => void;
  onPick: () => void;
  shared: Shared;
  dropProps?: object;
  onContextMenu?: (e: ReactMouseEvent) => void;
  /** A closed collection (shown with Show closed): greyed. */
  closed?: boolean;
  children?: ReactNode;
}) {
  const go = (e: KeyboardEvent<HTMLLIElement>, key: string) =>
    Array.from(e.currentTarget.closest('[role="tree"]')?.querySelectorAll<HTMLElement>("[data-key]") ?? [])
      .find((n) => n.dataset.key === key)
      ?.focus();
  const onKeyDown = (e: KeyboardEvent<HTMLLIElement>) => {
    if (e.target !== e.currentTarget || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "ArrowRight") {
      if (onToggle && !expanded) onToggle(true);
      else if (expanded && firstChildKey) go(e, firstChildKey);
    } else if (e.key === "ArrowLeft") {
      if (onToggle && expanded) onToggle(false);
      else if (parentKey) go(e, parentKey);
    } else if (e.key === "Enter" || e.key === " ") {
      onPick();
    } else return;
    e.preventDefault();
    e.stopPropagation(); // the page's own keys (the list's cursor) never see these
  };
  return (
    <li
      role="treeitem"
      aria-level={level}
      aria-label={name}
      aria-expanded={onToggle ? expanded : undefined}
      aria-current={current ? "true" : undefined}
      data-key={rowKey}
      className="tree-node"
      tabIndex={shared.focusKey === rowKey ? 0 : -1}
      onFocus={(e) => {
        if (e.target === e.currentTarget) shared.setFocusKey(rowKey);
      }}
      onKeyDown={onKeyDown}
    >
      <div
        className={["tree-row", current && "tree-current", closed && "tree-closed"].filter(Boolean).join(" ")}
        style={{ paddingLeft: 8 + (level - 1) * 16 }}
        onClick={onPick}
        onContextMenu={onContextMenu}
        {...dropProps}
      >
        <span
          className={onToggle ? (expanded ? "tree-chevron is-open" : "tree-chevron") : "tree-chevron is-none"}
          aria-hidden="true"
          onClick={(e) => {
            if (!onToggle) return;
            e.stopPropagation();
            onToggle();
          }}
        >
          <ChevronRight size={12} strokeWidth={2} />
        </span>
        {icon}
        <span className="tree-name" title={name}>
          {name}
        </span>
      </div>
      {children}
    </li>
  );
}

function CollectionNode({ c, level, parentKey, shared }: { c: CollectionRow; level: number; parentKey?: string; shared: Shared }) {
  const kids = shared.kids.get(c.id) ?? [];
  const expanded = kids.length > 0 && !shared.folded.has(c.id);
  const accept = shared.collect.accept(c);
  const add = shared.collect.add(c);
  // files, and the collection they come from (a drop within one tree moves them)
  const target = useDropTarget<{ ids: string[]; from: number | null }>({
    read: (e) => {
      const ids = readDragFiles(e);
      return ids === null ? null : { ids, from: readDragSource(e) };
    },
    accept: (d) => accept(d.ids),
    onDrop: (d) => add(d.ids, d.from),
  });
  const key = `c${c.id}`;
  return (
    <Row
      rowKey={key}
      name={visible(c.name)}
      icon={<Layers className="tree-icon" {...ICON} />}
      level={level}
      current={shared.active.collections.some((n) => n.toLowerCase() === c.name.toLowerCase())}
      expanded={expanded}
      parentKey={parentKey}
      firstChildKey={kids[0] ? `c${kids[0].id}` : undefined}
      onToggle={kids.length > 0 ? (open) => shared.toggle(c.id, open) : undefined}
      onPick={() => shared.onPick({ kind: "collection", name: c.name }, false)}
      shared={shared}
      dropProps={target.props}
      onContextMenu={shared.onMenu(c)}
      closed={c.state === "closed"}
    >
      {expanded && (
        <ul role="group" className="tree-group">
          {kids.map((k) => (
            <CollectionNode key={k.id} c={k} level={level + 1} parentKey={key} shared={shared} />
          ))}
        </ul>
      )}
    </Row>
  );
}

export function CollectionTree({
  active,
  onPick,
  head,
  onDeleted,
  startNew = false,
  onStartedNew,
  startClosed = false,
}: {
  active: ScopeState;
  onPick: Pick;
  head?: ReactNode;
  /** After a delete from the tree: the names of every collection that went (Browse leaves a search on them). */
  onDeleted?: (names: string[]) => void;
  /** Open with the New collection sheet (the sidebar's +), or with the closed ones shown. */
  startNew?: boolean;
  /** The New collection sheet opened for ``startNew``: drop the flag so the next ask opens it again. */
  onStartedNew?: () => void;
  startClosed?: boolean;
}) {
  // the open collections; with Show closed, the closed ones too (greyed)
  const [showClosed, setShowClosed] = useState(startClosed);
  const list = useCollections(showClosed ? "all" : "open");
  const collect = useAddToCollection();
  const toast = useToast();
  // New collection (at the top or inside one), then it opens: the tree's own pick
  const [creating, setCreating] = useState<{ parent: CollectionRow | null } | null>(null);
  useEffect(() => {
    if (!startNew) return;
    setCreating({ parent: null });
    onStartedNew?.();
    // only when asked; ``onStartedNew`` is a new function each render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startNew]);
  const order = useCollectionOrder(list.data ?? []);
  const [merging, setMerging] = useState<CollectionRow | null>(null);
  const [deleting, setDeleting] = useState<CollectionRow | null>(null);
  const menu = useOrderMenu(order, (c) => [
    { label: "Open", onSelect: () => onPick({ kind: "collection", name: c.name }, false) },
    { label: "New collection inside…", onSelect: () => setCreating({ parent: c }) },
    { label: "Merge into…", onSelect: () => setMerging(c) },
    { label: "Delete…", onSelect: () => setDeleting(c) },
  ]);
  const [folded, setFolded] = useState<Set<number>>(() => new Set());
  const [focused, setFocused] = useState<string | null>(null);
  const toggle = (id: number, open?: boolean) =>
    setFolded((old) => {
      const next = new Set(old);
      if (open ?? old.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const kids = childrenOf(list.data ?? []);
  const top = kids.get(null) ?? [];
  // the row that takes Tab: the one last focused while it is still shown, else Important
  const shownKeys = (level: CollectionRow[]): string[] =>
    level.flatMap((c) => [`c${c.id}`, ...(folded.has(c.id) ? [] : shownKeys(kids.get(c.id) ?? []))]);
  const focusKey = focused !== null && ["important", "starred", ...shownKeys(top)].includes(focused) ? focused : "important";
  const shared: Shared = { kids, folded, toggle, focusKey, setFocusKey: setFocused, active, onPick, collect, onMenu: menu.onContextMenu };
  const onKeyDown = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="treeitem"]'));
    const at = items.indexOf(document.activeElement as HTMLElement);
    if (at < 0) return;
    let next: HTMLElement | undefined;
    if (e.key === "ArrowDown") next = items[Math.min(items.length - 1, at + 1)];
    else if (e.key === "ArrowUp") next = items[Math.max(0, at - 1)];
    else if (e.key === "Home") next = items[0];
    else if (e.key === "End") next = items.at(-1);
    else return;
    e.preventDefault();
    e.stopPropagation();
    next?.focus();
  };
  return (
    <nav className="tree" aria-label="Collections">
      {head}
      <div className="tree-tools">
        <IconButton
          icon={<Archive />}
          label="Show closed"
          tip={showClosed ? "Hide the closed collections" : "Show the closed collections too"}
          pressed={showClosed}
          onClick={() => setShowClosed((on) => !on)}
        />
        <IconButton icon={<Plus />} label="New collection" onClick={() => setCreating({ parent: null })} />
      </div>
      <ul role="tree" aria-label="Collection tree" className="tree-list" onKeyDown={onKeyDown}>
        <Row
          rowKey="important"
          name="Important"
          icon={
            <span className="tree-icon" aria-hidden="true">
              <ImportantGlyph />
            </span>
          }
          level={1}
          current={active.important}
          onPick={() => onPick({ kind: "important" }, false)}
          shared={shared}
        />
        <Row
          rowKey="starred"
          name="Starred"
          icon={
            <span className="tree-icon" aria-hidden="true">
              <StarGlyph />
            </span>
          }
          level={1}
          current={active.starred}
          onPick={() => onPick({ kind: "starred" }, false)}
          shared={shared}
        />
        {top.map((c) => (
          <CollectionNode key={c.id} c={c} level={1} shared={shared} />
        ))}
        {list.isPending && (
          <li role="none" className="tree-note">
            Loading…
          </li>
        )}
        {list.isError && (
          <li role="none" className="tree-note">
            Could not list the collections
          </li>
        )}
        {list.isSuccess && top.length === 0 && (
          <li role="none" className="tree-note">
            No open collections
          </li>
        )}
      </ul>
      {menu.element}
      {deleting && (
        <DeleteCollectionSheet
          c={deleting}
          onCancel={() => setDeleting(null)}
          onDone={(n, names) => {
            setDeleting(null);
            toast({ kind: "info", text: n === 1 ? `Deleted ${deleting.name}` : `Deleted ${deleting.name} and the ${n - 1} inside it` });
            onDeleted?.(names);
          }}
        />
      )}
      {merging && (
        <MergeCollectionSheet
          c={merging}
          all={list.data ?? []}
          onCancel={() => setMerging(null)}
          onDone={(into) => {
            setMerging(null);
            toast({ kind: "info", text: `Merged ${merging.name} into ${into.name}` });
            onPick({ kind: "collection", name: into.name }, false);
          }}
        />
      )}
      {creating && (
        <NewCollectionSheet
          parent={creating.parent}
          onCancel={() => setCreating(null)}
          onCreated={(child) => {
            setCreating(null);
            toast({ kind: "info", text: creating.parent ? `Created ${child.name} inside ${creating.parent.name}` : `Created ${child.name}` });
            onPick({ kind: "collection", name: child.name }, false);
          }}
        />
      )}
    </nav>
  );
}
