import { ChevronRight } from "lucide-react";
import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { errorText, useCollections } from "../api/client";
import { visible } from "../text";
import { childrenOf, pathLabel } from "./collectionTree";
import { Sheet } from "./ui/Sheet";

const fold = (s: string) => s.normalize("NFC").toLocaleLowerCase();

type Row = { id: number; name: string; level: number; hasChildren: boolean; expanded: boolean };

type Props = {
  onChoose: (name: string) => void;
  onCancel: () => void;
};

/** "Browse collections…": the open collections as a tree (a collection nests in
 * another), to walk instead of typing a name. Same keys as the folder browser: ↑/↓
 * move, → opens (then goes in), ← closes (then goes up), Enter or a double-click
 * chooses, Esc cancels. The filter matches a name or its path ("Houses › Sauna") and
 * shows the matches under their parents. Choosing only hands the name back. */
export function CollectionBrowser({ onChoose, onCancel }: Props) {
  const ids = useId();
  const query = useCollections("open");
  const treeRef = useRef<HTMLUListElement>(null);
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set());
  const [active, setActive] = useState<number | null>(null);

  // Built-ins (★ Ongoing, ! Important) are not collections to add to by name.
  const list = useMemo(() => (query.data ?? []).filter((c) => c.kind == null && c.state === "open"), [query.data]);
  const kids = useMemo(() => childrenOf(list), [list]);
  const byId = useMemo(() => new Map(list.map((c) => [c.id, c])), [list]);
  const parentOf = (id: number) => {
    const p = byId.get(id)?.parent_id;
    return p != null && byId.has(p) ? p : null;
  };

  const needle = fold(filter.trim());
  const rows = useMemo((): Row[] => {
    const keep = needle ? new Set<number>() : null;
    if (keep) {
      for (const c of list) {
        if (!fold(pathLabel(c)).includes(needle)) continue;
        for (let at: number | null = c.id; at !== null && !keep.has(at); at = parentOf(at)) keep.add(at);
      }
    }
    const out: Row[] = [];
    const visit = (id: number, level: number) => {
      if (keep && !keep.has(id)) return;
      const c = byId.get(id)!;
      const sub = (kids.get(id) ?? []).filter((k) => !keep || keep.has(k.id));
      const open = keep ? true : expanded.has(id);
      out.push({ id, name: c.name, level, hasChildren: sub.length > 0, expanded: open && sub.length > 0 });
      if (open) sub.forEach((k) => visit(k.id, level + 1));
    };
    (kids.get(null) ?? []).forEach((c) => visit(c.id, 1));
    return out;
  }, [list, kids, byId, expanded, needle]);

  const current = rows.find((r) => r.id === active) ?? rows[0] ?? null;
  const index = current ? rows.indexOf(current) : -1;
  const rowId = (i: number) => `${ids}-row-${i}`;

  useEffect(() => {
    if (index >= 0) document.getElementById(rowId(index))?.scrollIntoView?.({ block: "nearest" });
  }, [index]);
  useEffect(() => {
    treeRef.current?.focus();
  }, []);
  // A new filter selects its first match (not a parent shown for it).
  useEffect(() => {
    if (!needle) return;
    const hit = rows.find((r) => fold(pathLabel(byId.get(r.id)!)).includes(needle));
    if (hit) setActive(hit.id);
    // Deliberately keyed on the filter only: walking the results keeps the user's row.
  }, [needle]);

  const setOpen = (id: number, open: boolean) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (open) next.add(id);
      else next.delete(id);
      return next;
    });
  const choose = (row: Row | null) => {
    if (row) onChoose(row.name);
  };

  /** ↑ ↓ and Enter work in the filter too; → and ← only on the tree (they move the caret). */
  const onKeys = (e: KeyboardEvent, inTree: boolean) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const move = (to: number) => {
      const row = rows[Math.max(0, Math.min(rows.length - 1, to))];
      if (row) setActive(row.id);
    };
    if (e.key === "ArrowDown") move(index + 1);
    else if (e.key === "ArrowUp") move(index - 1);
    else if (e.key === "Enter") choose(current);
    else if (inTree && e.key === "Home") move(0);
    else if (inTree && e.key === "End") move(rows.length - 1);
    else if (inTree && e.key === "ArrowRight" && current?.hasChildren) {
      if (!current.expanded) {
        if (!needle) setOpen(current.id, true);
      } else move(index + 1);
    } else if (inTree && e.key === "ArrowLeft" && current) {
      if (current.expanded && !needle) setOpen(current.id, false);
      else {
        const up = parentOf(current.id);
        if (up !== null) setActive(up);
      }
    } else return;
    e.preventDefault(); // Enter never submits a form underneath; arrows never scroll
  };

  return (
    <Sheet
      open
      className="folder-browser"
      title="Choose a collection"
      onClose={onCancel}
      // Keys pressed here are the browser's: the sheet or page underneath never sees them.
      onKeyDown={(e) => e.stopPropagation()}
      footer={
        <>
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={!current} onClick={() => choose(current)}>
            Choose
          </button>
        </>
      }
    >
      <input
        type="search"
        className="folder-browser-filter"
        aria-label="Filter collections"
        placeholder="Filter collections"
        aria-controls={`${ids}-tree`}
        autoComplete="off"
        spellCheck={false}
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        onKeyDown={(e) => onKeys(e, false)}
      />
      {query.isPending && <p className="busy">Loading collections…</p>}
      {query.isError && (
        <p className="error" role="alert">
          The collections could not be loaded: {visible(errorText(query.error))}
        </p>
      )}
      <ul
        ref={treeRef}
        id={`${ids}-tree`}
        role="tree"
        aria-label="Collections"
        className="folder-tree"
        tabIndex={0}
        aria-activedescendant={index >= 0 ? rowId(index) : undefined}
        onKeyDown={(e) => onKeys(e, true)}
      >
        {rows.map((row, i) => {
          const name = visible(row.name);
          return (
            <li
              key={row.id}
              id={rowId(i)}
              role="treeitem"
              aria-label={name}
              aria-level={row.level}
              aria-selected={i === index}
              aria-expanded={row.hasChildren ? row.expanded : undefined}
              className="folder-tree-row"
              style={{ paddingLeft: `calc(6px + ${row.level - 1} * var(--tree-indent))` }}
              onClick={() => setActive(row.id)}
              onDoubleClick={() => choose(row)}
            >
              {row.hasChildren ? (
                <button
                  type="button"
                  tabIndex={-1}
                  className="folder-tree-chevron"
                  aria-label={`${row.expanded ? "Close" : "Open"} ${name}`}
                  disabled={!!needle}
                  onClick={(e) => {
                    e.stopPropagation();
                    setActive(row.id);
                    setOpen(row.id, !row.expanded);
                    treeRef.current?.focus();
                  }}
                >
                  <ChevronRight size={12} data-open={row.expanded || undefined} aria-hidden="true" />
                </button>
              ) : (
                <span className="folder-tree-chevron" aria-hidden="true" />
              )}
              <span className="folder-tree-name">{name}</span>
            </li>
          );
        })}
      </ul>
      {needle && rows.length === 0 && query.data && <p className="hint">No collection matches “{visible(filter.trim())}”.</p>}
      {!needle && rows.length === 0 && query.data && <p className="hint">There are no open collections yet.</p>}
      <p className="hint folder-browser-status" role="status">
        {current ? visible(pathLabel(byId.get(current.id)!)) : ""}
      </p>
    </Sheet>
  );
}
