import {
  BookOpen,
  CircleHelp,
  File as FileIcon,
  Folder,
  FolderTree,
  History,
  Inbox,
  Layers,
  type LucideIcon,
  MessageCircleQuestion,
  Search,
  Settings,
  Sun,
  Tag as TagIcon,
  Wrench,
} from "lucide-react";
import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAllTags, useCollections, useFolders, useTrays } from "../api/client";
import { useStyle } from "../appearance";
import { useKeydown } from "../keyboard";
import { baseName, parentOf } from "../paths";
import { isSearchKey } from "../searchKey";
import { useSearch } from "../screens/useSearch";
import { tagFilter } from "../searchFilters";
import { visible } from "../text";
import { trayIcon } from "./ui/Sidebar";

/** The palette's open state, and the shortcut that toggles it. It works in both looks and
 * also while typing in a field; it stays out of the way of another open dialog. */
export function useSearchPalette() {
  const [open, setOpen] = useState(false);
  useKeydown((e) => {
    if (!isSearchKey(e)) return;
    if (document.querySelector("dialog[open]:not(.palette)")) return;
    e.preventDefault();
    setOpen((o) => !o);
  });
  return { open, show: () => setOpen(true), hide: () => setOpen(false) };
}

type Item = { key: string; group: string; label: string; hint?: string; icon: LucideIcon; to: string };

const SCREENS: { label: string; to: string; icon: LucideIcon; words?: string }[] = [
  { label: "Today", to: "/", icon: Sun },
  { label: "Inbox", to: "/inbox", icon: Inbox },
  { label: "Browse", to: "/browse", icon: FolderTree },
  { label: "Trays", to: "/trays", icon: BookOpen },
  { label: "Collections", to: "/collections", icon: Layers },
  { label: "Tags", to: "/tags", icon: TagIcon },
  { label: "Ask", to: "/ask", icon: MessageCircleQuestion },
  { label: "Activity", to: "/activity", icon: History },
  { label: "Maintenance", to: "/maintenance", icon: Wrench },
  { label: "Settings", to: "/settings", icon: Settings },
  { label: "Help", to: "/help", icon: CircleHelp },
];

/** How well ``text`` matches the words typed: lower is better, null is no match. Every
 * word must occur; a match at the start of the text or of a word beats one inside. */
function rank(text: string, words: string[]): number | null {
  const t = text.toLowerCase();
  let score = 0;
  for (const w of words) {
    const at = t.indexOf(w);
    if (at < 0) return null;
    score += at === 0 ? 0 : /[\s/_.-]/.test(t[at - 1]) ? 1 : 2;
  }
  return score;
}

/** The best ``limit`` of ``items`` for the words, best first (stable for equal scores). */
function best<T>(items: T[], words: string[], text: (item: T) => string, limit: number): T[] {
  if (words.length === 0) return items.slice(0, limit);
  const scored: [number, number, T][] = [];
  items.forEach((item, i) => {
    const s = rank(text(item), words);
    if (s !== null) scored.push([s, i, item]);
  });
  return scored
    .sort((a, b) => a[0] - b[0] || a[1] - b[1])
    .slice(0, limit)
    .map((x) => x[2]);
}

const MAX = { screens: 12, trays: 6, collections: 8, tags: 8, folders: 8, files: 8 };

/** The palette's results for what is typed. The lists (trays, collections, tags, folders)
 * come from the app's own cached requests; files from the search, once two characters
 * are typed. Empty, it offers the screens, trays and collections to jump to. */
function useResults(query: string) {
  const text = query.trim();
  const words = text.toLowerCase().split(/\s+/).filter(Boolean);
  const trays = useTrays();
  const collections = useCollections("open");
  const tags = useAllTags("");
  const folders = useFolders();
  const files = useSearch(text.length >= 2 ? text : "");
  const items = useMemo(() => {
    const out: Item[] = [];
    for (const s of best(SCREENS, words, (s) => s.label, MAX.screens)) {
      out.push({ key: `screen:${s.to}`, group: "Screens", label: s.label, icon: s.icon, to: s.to });
    }
    for (const t of best(trays.data?.trays ?? [], words, (t) => t.name, MAX.trays)) {
      out.push({ key: `tray:${t.id}`, group: "Trays", label: visible(t.name), icon: trayIcon(t), to: `/trays/${encodeURIComponent(t.id)}` });
    }
    for (const c of best(collections.data ?? [], words, (c) => c.name, MAX.collections)) {
      const where = c.path.slice(0, -1).map(visible).join(" / ");
      out.push({ key: `collection:${c.id}`, group: "Collections", label: visible(c.name), hint: where || undefined, icon: Layers, to: `/collections/${c.id}` });
    }
    if (words.length > 0) {
      for (const t of best(tags.data?.tags ?? [], words, (t) => t.name, MAX.tags)) {
        out.push({
          key: `tag:${t.name}`,
          group: "Tags",
          label: visible(t.name),
          hint: `${t.files} ${t.files === 1 ? "file" : "files"}`,
          icon: TagIcon,
          to: `/browse?${new URLSearchParams({ q: tagFilter(t.name) })}`,
        });
      }
      for (const f of best(folders.data ?? [], words, (f) => f, MAX.folders)) {
        out.push({
          key: `folder:${f}`,
          group: "Folders",
          label: visible(baseName(f)),
          hint: visible(parentOf(f)) || undefined,
          icon: Folder,
          to: `/browse?${new URLSearchParams({ path: f })}`,
        });
      }
      for (const h of (files.hits ?? []).slice(0, MAX.files)) {
        out.push({
          key: `file:${h.drive_id}`,
          group: "Files",
          label: visible(h.name),
          hint: visible(parentOf(h.path)) || undefined,
          icon: FileIcon,
          to: `/browse?${new URLSearchParams({ path: parentOf(h.path), select: h.drive_id })}`,
        });
      }
    }
    return out;
    // the words are the text, split: they change exactly when it does
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, trays.data, collections.data, tags.data, folders.data, files.hits]);
  return { items, searching: text.length >= 2 && files.hits === null && !files.error, fileError: files.error };
}

/** Search and jump: one box for files, folders, collections, trays, tags and the screens
 * themselves, driven by the keyboard (↑ ↓ move, Enter opens, Esc closes). Mounted only
 * while open, so closed it asks the server for nothing. */
export function SearchPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return <PaletteDialog onClose={onClose} />;
}

function PaletteDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const [look] = useStyle();
  const id = useId();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const { items, searching, fileError } = useResults(query);
  const at = Math.min(active, Math.max(items.length - 1, 0));
  const optionId = (i: number) => `${id}-option-${i}`;

  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    if (!d.open) d.showModal();
    input.current?.focus();
    return () => {
      if (d.open) d.close();
    };
  }, []);
  useEffect(() => {
    if (items.length > 0) document.getElementById(optionId(at))?.scrollIntoView({ block: "nearest" });
    // scroll when the active row changes, not when its id string does
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [at, items.length]);

  const go = (item: Item | undefined) => {
    if (!item) return;
    onClose();
    navigate(item.to);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDialogElement>) => {
    e.stopPropagation(); // the page's shortcuts stay off while the palette has the keys
    if (isSearchKey(e)) {
      e.preventDefault(); // the shortcut that opened it closes it
      onClose();
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (items.length > 0) setActive((at + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length);
    } else if (e.key === "Enter" && !e.nativeEvent.isComposing) {
      e.preventDefault();
      go(items[at]);
    }
  };

  const groups: { name: string; first: number; list: Item[] }[] = [];
  items.forEach((item, i) => {
    const last = groups.at(-1);
    if (last?.name === item.group) last.list.push(item);
    else groups.push({ name: item.group, first: i, list: [item] });
  });
  const typed = query.trim().length > 0;
  const status = items.length > 0 ? `${items.length} ${items.length === 1 ? "result" : "results"}` : searching ? "Searching" : typed ? "No matches" : "";

  return (
    <dialog
      ref={dialog}
      className="palette"
      aria-label="Search and jump"
      data-look={look}
      tabIndex={-1}
      onCancel={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }}
      onKeyDown={onKeyDown}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose(); // the backdrop
      }}
    >
      <div className="palette-field">
        <Search size={16} strokeWidth={1.75} aria-hidden="true" />
        <input
          ref={input}
          type="text"
          role="combobox"
          aria-label="Search files, folders, collections, trays, tags and screens"
          aria-expanded={items.length > 0}
          aria-controls={`${id}-list`}
          aria-activedescendant={items.length > 0 ? optionId(at) : undefined}
          aria-autocomplete="list"
          autoComplete="off"
          spellCheck={false}
          placeholder="Search files, folders, collections, tags, screens"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
        />
        <kbd aria-hidden="true">esc</kbd>
      </div>
      <div className="palette-results">
        <div id={`${id}-list`} role="listbox" aria-label="Results">
          {groups.map((g) => (
            <div key={g.name} role="group" aria-labelledby={`${id}-group-${g.name}`} className="palette-group">
              <div id={`${id}-group-${g.name}`} className="palette-group-title">
                {g.name}
              </div>
              {g.list.map((item, j) => {
                const i = g.first + j;
                const Icon = item.icon;
                return (
                  <div
                    key={item.key}
                    id={optionId(i)}
                    role="option"
                    aria-selected={i === at}
                    className="palette-option"
                    title={item.hint ? `${item.label} (${item.hint})` : item.label}
                    onMouseMove={() => i !== at && setActive(i)}
                    onMouseDown={(e) => e.preventDefault()} // the box keeps the focus
                    onClick={() => go(item)}
                  >
                    <Icon size={16} strokeWidth={1.75} aria-hidden="true" className="palette-icon" />
                    <span className="palette-label">{item.label}</span>
                    {item.hint && <span className="palette-hint">{item.hint}</span>}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        {items.length === 0 && typed && !searching && <p className="palette-empty">Nothing matches “{query.trim()}”.</p>}
        {searching && <p className="palette-empty">Searching files…</p>}
        {fileError && <p className="palette-empty">Files could not be searched.</p>}
      </div>
      <p className="visually-hidden" role="status">
        {status}
      </p>
      <p className="palette-foot" aria-hidden="true">
        <span>
          <kbd>↑</kbd>
          <kbd>↓</kbd> move
        </span>
        <span>
          <kbd>↵</kbd> open
        </span>
        <span>
          <kbd>esc</kbd> close
        </span>
      </p>
    </dialog>
  );
}
