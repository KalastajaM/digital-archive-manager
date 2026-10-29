/** The tag tree beside Browse's panes (the New look): the tags by group as on the Tags screen
 * (each group's tags by name, then those in no group), each with its number of files, and a
 * box above them that narrows the list. A click lists the tag's files in Browse (a `tag:`
 * search); Cmd-click (Ctrl-click) adds the tag to those already picked.
 *
 * Keyboard (the tree view pattern): ↑ and ↓ move, → opens a group, ← closes it (or steps
 * out to it), Home and End go to the first and last, Enter picks (with Cmd: adds). */
import { ChevronRight, Tag as TagIcon } from "lucide-react";
import { type KeyboardEvent, type MouseEvent, useState } from "react";
import { useAllTags } from "../api/client";
import type { ScopePick, ScopeState } from "../browseScope";
import { visible } from "../text";

type Pick = (pick: ScopePick, add: boolean) => void;
type TagInfo = { name: string; files: number; group_id: number | null };

const byName = (a: TagInfo, b: TagInfo) => a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true });
const ICON = { size: 14, strokeWidth: 1.75, "aria-hidden": true } as const;

/** Focus the tree item with ``data-key`` = ``key`` in the same tree. */
const go = (from: HTMLElement, key: string) =>
  Array.from(from.closest('[role="tree"]')?.querySelectorAll<HTMLElement>("[data-key]") ?? [])
    .find((n) => n.dataset.key === key)
    ?.focus();

export function TagTree({ active, onPick }: { active: ScopeState; onPick: Pick }) {
  const [typed, setTyped] = useState("");
  const list = useAllTags(typed.trim());
  const [folded, setFolded] = useState<Set<number>>(() => new Set());
  const [focused, setFocused] = useState<string | null>(null);
  const tags = list.data?.tags ?? [];
  const groups = (list.data?.groups ?? []).map((g) => ({ ...g, tags: tags.filter((t) => t.group_id === g.id).sort(byName) })).filter((g) => g.tags.length > 0);
  const loose = tags.filter((t) => t.group_id === null || !groups.some((g) => g.id === t.group_id)).sort(byName);
  const sections = [...groups.map((g) => ({ key: `g${g.id}`, id: g.id as number | null, name: g.name, tags: g.tags })), ...(loose.length > 0 ? [{ key: "g-none", id: null, name: "No group", tags: loose }] : [])];
  // with no groups at all the tags stand alone, as on the Tags screen
  const flat = groups.length === 0;
  const firstKey = flat ? (loose[0] ? `t${loose[0].name}` : "") : (sections[0]?.key ?? "");
  const focusKey = focused ?? firstKey;
  const picked = (name: string) => active.tags.some((t) => t.toLowerCase() === name.toLowerCase());
  const toggle = (id: number, open?: boolean) =>
    setFolded((old) => {
      const next = new Set(old);
      if (open ?? old.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const groupId = (key: string) => (key === "g-none" ? -1 : Number(key.slice(1)));

  const onTreeKeys = (e: KeyboardEvent<HTMLUListElement>) => {
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

  const tagItem = (t: TagInfo, level: number, groupKey?: string) => {
    const key = `t${t.name}`;
    const name = visible(t.name);
    const pick = (add: boolean) => onPick({ kind: "tag", name: t.name }, add);
    const onKeyDown = (e: KeyboardEvent<HTMLLIElement>) => {
      if (e.target !== e.currentTarget || e.altKey) return;
      if (e.key === "Enter" || e.key === " ") pick(e.metaKey || e.ctrlKey);
      else if (e.key === "ArrowLeft" && groupKey && !e.metaKey && !e.ctrlKey) go(e.currentTarget, groupKey);
      else return;
      e.preventDefault();
      e.stopPropagation();
    };
    return (
      <li
        key={key}
        role="treeitem"
        aria-level={level}
        aria-label={`${name}, ${t.files} ${t.files === 1 ? "file" : "files"}`}
        aria-current={picked(t.name) ? "true" : undefined}
        data-key={key}
        className="tree-node"
        tabIndex={focusKey === key ? 0 : -1}
        onFocus={(e) => {
          if (e.target === e.currentTarget) setFocused(key);
        }}
        onKeyDown={onKeyDown}
      >
        <div
          className={picked(t.name) ? "tree-row tree-current" : "tree-row"}
          style={{ paddingLeft: 8 + (level - 1) * 16 }}
          onClick={(e: MouseEvent) => pick(e.metaKey || e.ctrlKey)}
        >
          <span className="tree-chevron is-none" aria-hidden="true" />
          <TagIcon className="tree-icon" {...ICON} />
          <span className="tree-name" title={name}>
            {name}
          </span>
          <span className="tree-count">{t.files}</span>
        </div>
      </li>
    );
  };

  const empty = list.isSuccess && tags.length === 0;
  return (
    <nav className="tree" aria-label="Tags">
      <input
        type="search"
        className="tree-filter"
        aria-label="Filter tags"
        placeholder="Filter tags"
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
      />
      <ul role="tree" aria-label="Tag tree" className="tree-list" onKeyDown={onTreeKeys}>
        {flat
          ? loose.map((t) => tagItem(t, 1))
          : sections.map((s) => {
              const open = !folded.has(groupId(s.key));
              const onKeyDown = (e: KeyboardEvent<HTMLLIElement>) => {
                if (e.target !== e.currentTarget || e.metaKey || e.ctrlKey || e.altKey) return;
                if (e.key === "ArrowRight") {
                  if (!open) toggle(groupId(s.key), true);
                  else if (s.tags[0]) go(e.currentTarget, `t${s.tags[0].name}`);
                } else if (e.key === "ArrowLeft" || e.key === "Enter" || e.key === " ") {
                  toggle(groupId(s.key), e.key === "ArrowLeft" ? false : undefined);
                } else return;
                e.preventDefault();
                e.stopPropagation();
              };
              return (
                <li
                  key={s.key}
                  role="treeitem"
                  aria-level={1}
                  aria-label={visible(s.name)}
                  aria-expanded={open}
                  data-key={s.key}
                  className="tree-node"
                  tabIndex={focusKey === s.key ? 0 : -1}
                  onFocus={(e) => {
                    if (e.target === e.currentTarget) setFocused(s.key);
                  }}
                  onKeyDown={onKeyDown}
                >
                  <div className="tree-row tree-group-row" style={{ paddingLeft: 8 }} onClick={() => toggle(groupId(s.key))}>
                    <span className={open ? "tree-chevron is-open" : "tree-chevron"} aria-hidden="true">
                      <ChevronRight size={12} strokeWidth={2} />
                    </span>
                    <span className="tree-name" title={visible(s.name)}>
                      {visible(s.name)}
                    </span>
                  </div>
                  {open && (
                    <ul role="group" className="tree-group">
                      {s.tags.map((t) => tagItem(t, 2, s.key))}
                    </ul>
                  )}
                </li>
              );
            })}
        {list.isPending && (
          <li role="none" className="tree-note">
            Loading…
          </li>
        )}
        {list.isError && (
          <li role="none" className="tree-note">
            Could not list the tags
          </li>
        )}
        {empty && (
          <li role="none" className="tree-note">
            {typed.trim() ? "No tag matches" : "No tags yet"}
          </li>
        )}
      </ul>
    </nav>
  );
}
