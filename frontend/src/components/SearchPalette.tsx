import { File as FileIcon, Folder, Layers, ListFilter, type LucideIcon, Search, Tag as TagIcon } from "lucide-react";
import { type KeyboardEvent, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAllTags, useCollections, useFolders, useTrays } from "../api/client";
import { useKeydown } from "../keyboard";
import { baseName, parentOf } from "../paths";
import { isSearchKey } from "../searchKey";
import { useSearch } from "../screens/useSearch";
import { filterToken, readQuery, serializeQuery, splitSearch, tagFilter } from "../searchFilters";
import { visible } from "../text";
import { browseSearchUrl } from "./today/SearchCard";
import { trayIcon } from "./ui/Sidebar";
import { type Completion, useSearchCompletions } from "./useSearchCompletions";
import { collectionHref } from "../collectionHref";

/** The palette's open state, and the shortcut that toggles it. It works also while
 * typing in a field; it stays out of the way of another open dialog. */
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

type Item = {
  key: string;
  group: string;
  label: string;
  hint?: string;
  icon: LucideIcon;
  /** Where it goes; a suggestion has none (it edits the box instead). */
  to?: string;
  completion?: Completion;
};

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

const MAX = { trays: 6, collections: 8, tags: 8, folders: 8, files: 8 };

/** The text before the caret, split into words and filters, and where the token being
 * typed starts in it. A quoted value may hold spaces, so a partial one starts before its
 * last opening quote. */
function tokenAtCaret(before: string) {
  const typed = splitSearch(before);
  const quote = typed.partial?.quoted ? before.lastIndexOf('"') : before.length;
  return { typed, start: before.slice(0, quote).search(/\S*$/) };
}

/** The palette's results for what is typed. The lists (trays, collections, tags, folders)
 * come from the app's own cached requests; files from the search, once two characters
 * are typed; filter names and values from the same completions as Browse's search box.
 * Empty, it offers the trays and collections to jump to. A last row always searches the
 * archive for the whole text. */
function useResults(query: string, typed: ReturnType<typeof splitSearch>, suggestOpen: boolean) {
  const text = query.trim();
  const words = typed.rest.toLowerCase().split(/\s+/).filter(Boolean);
  const nothing = text === "";
  const trays = useTrays();
  const collections = useCollections("open");
  const tags = useAllTags("");
  const folders = useFolders();
  const whole = splitSearch(query);
  const files = useSearch(text.length >= 2 && !typed.partial ? text : "");
  const completions = useSearchCompletions(typed, whole.filters, suggestOpen && !nothing);
  // Words only get filter names; their tag matches are the Tags rows below.
  const offered = useMemo(() => completions.filter((c) => typed.partial !== null || c.kind === "name"), [completions, typed.partial]);
  const items = useMemo(() => {
    const out: Item[] = [];
    for (const c of offered) {
      out.push({
        key: `suggest:${c.key}`,
        group: "Filters",
        label: c.kind === "name" ? c.label : filterToken(c.filter),
        hint: c.hint,
        icon: ListFilter,
        completion: c,
      });
    }
    if (nothing || words.length > 0) {
      for (const t of best(trays.data?.trays ?? [], words, (t) => t.name, MAX.trays)) {
        out.push({ key: `tray:${t.id}`, group: "Trays", label: visible(t.name), icon: trayIcon(t), to: `/trays/${encodeURIComponent(t.id)}` });
      }
      for (const c of best(collections.data ?? [], words, (c) => c.name, MAX.collections)) {
        const where = c.path.slice(0, -1).map(visible).join(" / ");
        out.push({ key: `collection:${c.id}`, group: "Collections", label: visible(c.name), hint: where || undefined, icon: Layers, to: collectionHref(c) });
      }
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
    }
    for (const h of (nothing ? [] : (files.hits ?? [])).slice(0, MAX.files)) {
      out.push({
        key: `file:${h.drive_id}`,
        group: "Files",
        label: visible(h.name),
        hint: visible(parentOf(h.path)) || undefined,
        icon: FileIcon,
        to: `/browse?${new URLSearchParams({ path: parentOf(h.path), select: h.drive_id })}`,
      });
    }
    if (!nothing) {
      // the same address as submitting Browse's own search box with this text
      const { words: w, filters } = readQuery(text);
      out.push({
        key: "search-all",
        group: "Search",
        label: `Search the archive for \u201c${serializeQuery(w, filters) || text}\u201d`,
        icon: Search,
        to: browseSearchUrl(text),
      });
    }
    return out;
    // the words are the text, split: they change exactly when it does
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, offered, trays.data, collections.data, tags.data, folders.data, files.hits]);
  return { items, suggesting: offered.length > 0, searching: text.length >= 2 && !typed.partial && files.hits === null && !files.error, fileError: files.error };
}

/** Search and jump: one box for files, folders, collections, trays and tags, driven by the
 * keyboard (↑ ↓ move, Enter opens, Esc closes). Typing a filter (``tag:``) lists its values
 * to take with Enter or Tab (Esc hides that list first); the last row searches the archive
 * for the text as typed. Mounted only while open, so closed it asks the server for nothing. */
export function SearchPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return <PaletteDialog onClose={onClose} />;
}

function PaletteDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const id = useId();
  const [query, setQuery] = useState("");
  const [caret, setCaret] = useState(0);
  const [suggestOpen, setSuggestOpen] = useState(true);
  const [active, setActive] = useState(0);
  const moveCaret = useRef<number | null>(null);
  const { typed, start } = tokenAtCaret(query.slice(0, caret));
  const { items, suggesting, searching, fileError } = useResults(query, typed, suggestOpen);
  const at = Math.min(active, Math.max(items.length - 1, 0));
  const optionId = (i: number) => `${id}-option-${i}`;
  const showing = useRef(false);
  showing.current = suggesting;

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
  useLayoutEffect(() => {
    if (moveCaret.current === null) return;
    input.current?.setSelectionRange(moveCaret.current, moveCaret.current);
    moveCaret.current = null;
  });

  /** A suggestion edits the box: a filter name replaces the word, a value replaces the
   * token being typed and ends with a space, so the next filter or word can follow. */
  const insert = (c: Completion) => {
    const after = query.slice(caret);
    const put = c.kind === "name" ? c.insert : `${filterToken(c.filter)} `;
    // the rest of the token goes (and, for a value, the space after it: put brings its own)
    const next = query.slice(0, start) + put + after.replace(c.kind === "name" ? /^\S*/ : /^\S*\s?/, "");
    const to = start + put.length;
    setQuery(next);
    setCaret(to);
    moveCaret.current = to;
    setSuggestOpen(true);
    setActive(0);
  };
  const go = (item: Item | undefined) => {
    if (!item) return;
    if (item.completion) {
      insert(item.completion);
      return;
    }
    if (!item.to) return;
    onClose();
    navigate(item.to);
  };
  const close = (e: { preventDefault(): void; stopPropagation(): void }) => {
    e.preventDefault();
    e.stopPropagation();
    if (showing.current) {
      setSuggestOpen(false); // Esc closes the suggestions first, the palette next
      setActive(0);
    } else onClose();
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDialogElement>) => {
    e.stopPropagation(); // the page's shortcuts stay off while the palette has the keys
    if (isSearchKey(e)) {
      e.preventDefault(); // the shortcut that opened it closes it
      onClose();
      return;
    }
    if (e.key === "Escape") {
      close(e);
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (items.length > 0) setActive((at + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length);
    } else if (e.key === "Tab" && !e.shiftKey && items[at]?.completion) {
      e.preventDefault();
      go(items[at]);
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
  const typedAny = query.trim().length > 0;
  const found = items.filter((i) => i.group !== "Search" && i.group !== "Filters").length;
  const status = found > 0 ? `${found} ${found === 1 ? "result" : "results"}` : searching ? "Searching" : typedAny ? "No matches" : "";
  const sync = (e: { currentTarget: HTMLInputElement }) => setCaret(e.currentTarget.selectionStart ?? e.currentTarget.value.length);

  return (
    <dialog
      ref={dialog}
      className="palette"
      aria-label="Search and jump"
      tabIndex={-1}
      onCancel={close}
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
          aria-label="Search files, folders, collections, trays and tags"
          aria-expanded={items.length > 0}
          aria-controls={`${id}-list`}
          aria-activedescendant={items.length > 0 ? optionId(at) : undefined}
          aria-autocomplete="list"
          autoComplete="off"
          spellCheck={false}
          placeholder="Search files, folders, collections, tags, or tag:name"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            sync(e);
            setSuggestOpen(true);
            setActive(0);
          }}
          onSelect={sync}
          onKeyUp={sync}
          onClick={sync}
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
          <kbd>tab</kbd> take a filter
        </span>
        <span>
          <kbd>esc</kbd> close
        </span>
      </p>
    </dialog>
  );
}
