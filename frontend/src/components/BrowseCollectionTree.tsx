/** The collection tree beside Browse's panes (the New look): Important and Starred first, then
 * the open collections as they nest, in their own order. A click lists the collection's files
 * in Browse (a `collection:` search, or `is:starred` / `is:important`); files dropped on a
 * collection are added to it, as on the sidebar's rows.
 *
 * Keyboard (the tree view pattern, as the folder tree): ↑ and ↓ move, → opens a collection
 * (or steps into it), ← closes it (or steps out), Home and End go to the first and last, Enter
 * picks. */
import { ChevronRight, Layers } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useState } from "react";
import { type CollectionRow, useCollections } from "../api/client";
import type { ScopePick, ScopeState } from "../browseScope";
import { useDropTarget } from "../dnd";
import { visible } from "../text";
import { childrenOf } from "./collectionTree";
import { ImportantGlyph, StarGlyph } from "./MarkIcons";
import { useAddToCollection } from "./useAddToCollection";

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
      <div className={current ? "tree-row tree-current" : "tree-row"} style={{ paddingLeft: 8 + (level - 1) * 16 }} onClick={onPick} {...dropProps}>
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
  const target = useDropTarget({ accept: shared.collect.accept(c), onDrop: shared.collect.add(c) });
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

export function CollectionTree({ active, onPick, head }: { active: ScopeState; onPick: Pick; head?: ReactNode }) {
  const list = useCollections("open");
  const collect = useAddToCollection();
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
  const shared: Shared = { kids, folded, toggle, focusKey: focused ?? "important", setFocusKey: setFocused, active, onPick, collect };
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
    </nav>
  );
}
