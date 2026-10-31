import {
  BookOpen,
  ChevronRight,
  CircleCheck,
  CircleHelp,
  Euro,
  Hourglass,
  FolderTree,
  History,
  Wrench,
  Inbox,
  Layers,
  MessageCircleQuestion,
  ListTodo,
  type LucideIcon,
  Pin,
  Plus,
  Search,
  Settings,
  Sun,
  Tag as TagIcon,
} from "lucide-react";
import { type ComponentProps, type ReactNode, useEffect, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  archiveKey,
  type CollectionRow,
  type SidebarTag,
  type TagInfo,
  type TrayDef,
  useBuiltin,
  useAllTags,
  useCollections,
  useSidebarTags,
  useStatus,
  useToday,
  useTodayFollowsInbox,
  useTrays,
} from "../../api/client";
import {
  type DropTarget,
  draggedLabel,
  draggedPaths,
  type Dragged,
  readDragCollection,
  readFilesOrCollection,
  setDragCollection,
  useDropTarget,
} from "../../dnd";
import { useStyle } from "../../appearance";
import { visible } from "../../text";
import { ArchiveSwitcher } from "../ArchiveSwitcher";
import { ImportantGlyph, StarGlyph } from "../MarkIcons";
import {
  childrenOf,
} from "../collectionTree";
import { anyMoveRunning, backToInbox, inboxRefusal, MOVE_BUSY, useInboxFolder, useMoveFlow } from "../MoveTo";
import { useBlockToastActions } from "../Toasts";
import {
  type CollectionOrder,
  orderKeys,
  useCollectionOrder,
  useMoveCollection,
  useReorderRow,
} from "../useCollectionOrder";
import { useCollectionMenu } from "../useCollectionMenu";
import { useTagManager } from "../useTagManager";
import { ContextMenu } from "./ContextMenu";
import type { MenuEntry } from "./Menu";
import { useUndoConfirm } from "../UndoConfirm";
import { useAddToCollection } from "../useAddToCollection";
import { useQuickPut } from "../useQuickPut";
import { collectionHref } from "../../collectionHref";
import { scopedCollection } from "../../collectionScope";
import { searchKeyLabel } from "../../searchKey";
import { positiveTags, readQuery, serializeQuery, tagFilter } from "../../searchFilters";

const ICON = { size: 16, strokeWidth: 1.75, "aria-hidden": true } as const;

/** The tooltip of a row: in the New look a narrow window shows the sidebar as an icon rail
 * (no labels), so every row names itself on hover. Classic has no row tooltips. */
function useRowTitle(): (text: string) => string | undefined {
  const [look] = useStyle();
  return (text) => (look === "new" ? text : undefined);
}

/** New look: the grip on a row that can be dragged to a new place (shown on hover). The
 * whole row drags, as in Classic; the grip only says so. Classic draws none. */
function Grip() {
  const [look] = useStyle();
  if (look !== "new") return null;
  return (
    <span className="sidebar-grip" aria-hidden="true">
      <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor">
        <circle cx="2.5" cy="3" r="1.2" />
        <circle cx="7.5" cy="3" r="1.2" />
        <circle cx="2.5" cy="7" r="1.2" />
        <circle cx="7.5" cy="7" r="1.2" />
        <circle cx="2.5" cy="11" r="1.2" />
        <circle cx="7.5" cy="11" r="1.2" />
      </svg>
    </span>
  );
}

/** New look: the search field under the archive's name. It looks like a field but opens the
 * search and jump palette (also on the shortcut); in the icon rail it is an icon. */
function SidebarSearch({ onOpen }: { onOpen: () => void }) {
  const key = searchKeyLabel();
  return (
    <button type="button" className="sidebar-search" aria-haspopup="dialog" aria-label={`Search (${key})`} title={`Search (${key})`} onClick={onOpen}>
      <Search size={14} strokeWidth={2} aria-hidden="true" />
      <span className="sidebar-search-text">Search</span>
      <kbd className="sidebar-search-key" aria-hidden="true">
        {key}
      </kbd>
    </button>
  );
}

type RowProps = {
  to: string;
  end?: boolean;
  icon: LucideIcon;
  label: string;
  /** A muted count after the label (hidden when 0). */
  count?: number;
  /** A red badge instead of the count (hidden when 0). */
  badge?: number;
  /** Drop-target props: dragging documents onto a tray or collection. */
  dropProps?: DropTarget["props"];
};

/** A link into Browse with a query (``/browse?tree=tags``) is current only on that exact
 * address: a NavLink compares the path alone and would mark it on every Browse address. */
function SidebarLink({ to, end, className, ...rest }: ComponentProps<typeof Link> & { to: string; end?: boolean; className: string }) {
  const { pathname, search } = useLocation();
  if (!to.includes("?")) return <NavLink to={to} end={end} className={className} {...rest} />;
  const current = pathname + search === to;
  return <Link to={to} className={current ? `${className} active` : className} aria-current={current ? "page" : undefined} {...rest} />;
}

/** One sidebar row: a NavLink named "Label (n)" so the count is read along with it. */
function Row({ to, end, icon: Icon, label, count, badge, dropProps }: RowProps) {
  const n = badge || count || 0;
  const title = useRowTitle();
  return (
    <li>
      <SidebarLink
        to={to}
        end={end}
        className="sidebar-row"
        aria-label={n ? `${label} (${n})` : label}
        title={title(n ? `${label} (${n})` : label)}
        {...dropProps}
      >
        <Icon className="sidebar-icon" {...ICON} />
        <span className="sidebar-label">{label}</span>
        {badge ? (
          <span className="sidebar-badge">{badge}</span>
        ) : count ? (
          <span className="sidebar-count">{count}</span>
        ) : null}
      </SidebarLink>
    </li>
  );
}

/** A section caption; when ``to`` is given it links to the section's index screen.
 * ``dropProps`` make the caption a drop target (the Collections caption: the top level).
 * The chevron beside the caption folds the section (shown on hover, and always while
 * folded); a folded section shows ``foldedCount`` after its caption, if given. */
function Section({
  title,
  to,
  dropProps,
  folded,
  onFold,
  foldedCount,
  add,
  onMenu,
  children,
}: {
  title: string;
  to?: string;
  dropProps?: DropTarget["props"];
  folded: boolean;
  onFold: () => void;
  foldedCount?: number;
  /** New look: a "+" after the caption that goes to where something is made. */
  add?: { to: string; label: string };
  /** The caption's right-click menu (New collection, New tag). */
  onMenu?: (e: React.MouseEvent) => void;
  children: ReactNode;
}) {
  const [look] = useStyle();
  return (
    <li className="sidebar-section">
      <div className="sidebar-section-head">
        {to ? (
          <SidebarLink to={to} end className="sidebar-section-title" onContextMenu={onMenu} {...dropProps}>
            {title}
          </SidebarLink>
        ) : (
          <h3 className="sidebar-section-title" onContextMenu={onMenu}>
            {title}
          </h3>
        )}
        {folded && foldedCount ? <span className="sidebar-count sidebar-section-count">{foldedCount}</span> : null}
        <button
          type="button"
          className="sidebar-disclosure sidebar-section-fold"
          aria-expanded={!folded}
          aria-label={`${title} section`}
          title={folded ? `Show ${title}` : `Hide ${title}`}
          onClick={onFold}
        >
          <ChevronRight size={12} strokeWidth={2} aria-hidden="true" className="sidebar-chevron" data-open={!folded || undefined} />
        </button>
        {look === "new" && add && (
          <Link to={add.to} className="sidebar-section-add" aria-label={add.label} title={add.label}>
            <Plus size={13} strokeWidth={2} aria-hidden="true" />
          </Link>
        )}
      </div>
      {!folded && <ul className="sidebar-list">{children}</ul>}
    </li>
  );
}

type DropProps = Omit<RowProps, "dropProps"> & {
  accept: (ids: string[]) => boolean | string;
  onDrop: (ids: string[]) => void;
};

/** A row that documents can be dropped on (a tray or a collection). */
function DropRow({ accept, onDrop, ...row }: DropProps) {
  const target = useDropTarget({ accept, onDrop });
  return <Row {...row} dropProps={target.props} />;
}

/** What a drop names in its toast: the file for one (when the drag says), else a count. */
/** Dropping documents on the Inbox moves them back into the inbox folder: the move
 * flow previews, always confirms and offers Undo. Files already there (or in an area
 * that keeps its files) are refused before the drop when the drag says where they are. */
function useDropBackToInbox() {
  const inbox = useInboxFolder();
  const move = useMoveFlow();
  const undo = useUndoConfirm();
  useBlockToastActions(move.busy || move.confirming || undo.target !== null || undo.pending);
  const accept = () => {
    const refusal = inboxRefusal(draggedPaths(), inbox);
    if (refusal) return refusal;
    return anyMoveRunning() ? MOVE_BUSY : true; // any flow's move, not only this one's
  };
  const drop = (ids: string[]) => {
    if (!inbox || anyMoveRunning()) return;
    // a mixed drag: the files already in the inbox stay out of the request
    move.start(backToInbox(ids, inbox, draggedPaths()));
  };
  return { accept, drop, view: move.view };
}

/** What a collection row takes: files (added as members) or another collection (moved
 * inside it). A drag is one or the other, never both (see ``dnd``). */
const FOLD_KEY = "dam.sidebar.collections.folded.v1";
/** The folded sections (Trays, Collections, Archive): the same in every archive. */
const SECTION_FOLD_KEY = "dam.sidebar.sections.folded.v1";

const isId = (x: unknown): x is number => Number.isSafeInteger(x);
const isName = (x: unknown): x is string => typeof x === "string";

/** What is folded, kept in this browser's localStorage under ``key``. Every storage
 * access is in try/catch: private windows and blocked site data throw. */
function readFolds<T>(key: string, valid: (x: unknown) => x is T): Set<T> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) ?? "[]");
    return new Set(Array.isArray(value) ? value.filter(valid) : []);
  } catch {
    return new Set();
  }
}

/** The folded parents (collection ids, per archive) or sections (by name). */
function useFolds<T extends number | string>(key: string, valid: (x: unknown) => x is T) {
  const [folded, setFolded] = useState<Set<T>>(() => readFolds(key, valid));
  // Saved after each change; the updates are functional, so a fold made while a move
  // runs is never undone by the move's unfold (or the other way round).
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify([...folded]));
    } catch {
      // Not saved: the fold still applies until the page reloads.
    }
  }, [key, folded]);
  return {
    folded,
    toggle: (id: T) =>
      setFolded((now) => {
        const next = new Set(now);
        if (!next.delete(id)) next.add(id);
        return next;
      }),
    unfold: (id: T) =>
      setFolded((now) => {
        if (!now.has(id)) return now;
        const next = new Set(now);
        next.delete(id);
        return next;
      }),
  };
}

type TreeProps = {
  c: CollectionRow;
  /** The collection Browse shows now (its search), if any: that row is current. */
  current: number | null;
  kids: Map<number | null, CollectionRow[]>;
  folds: ReturnType<typeof useFolds<number>>;
  collect: ReturnType<typeof useAddToCollection>;
  mover: ReturnType<typeof useMoveCollection>;
  order: CollectionOrder;
  onMenu: (c: CollectionRow) => (e: React.MouseEvent) => void;
};

/** One collection in the sidebar tree, its children below it (unless folded). The row
 * takes dropped files (members) and dropped collections (moved inside), and drags as
 * a collection itself; "Move to…" on the collection page is the keyboard way. */
function CollectionNode({ c, current, kids, folds, collect, mover, order, onMenu }: TreeProps) {
  const children = kids.get(c.id) ?? [];
  const open = !folds.folded.has(c.id);
  const addFiles = collect.accept(c);
  const add = collect.add(c);
  const takeCollection = mover.accept(c);
  const moveHere = mover.move(c);
  const target = useDropTarget<Dragged>({
    read: readFilesOrCollection,
    accept: (d) => (d.kind === "files" ? addFiles(d.ids) : takeCollection(d.id)),
    onDrop: (d) => (d.kind === "files" ? add(d.ids, d.from) : moveHere(d.id)),
  });
  // near a sibling's top or bottom edge a dragged collection is put before or after it
  // (a drop line); in the middle it goes inside, as before
  const reorder = useReorderRow(order, c, target.props);
  const name = visible(c.name);
  const title = useRowTitle();
  const [look] = useStyle();
  // New: a count of the files in it, named with the row like the trays' counts
  const files = look === "new" ? c.files : 0;
  const label = files ? `${name} (${files})` : name;
  return (
    <li className="sidebar-tree-item">
      {/* a plain Link: every collection opens in /browse, so a NavLink would mark them all
          current there; the row is current while Browse shows this collection */}
      <Link
        to={collectionHref(c)}
        className={[children.length > 0 ? "sidebar-row sidebar-row-parent" : "sidebar-row", current === c.id && "active"].filter(Boolean).join(" ")}
        aria-current={current === c.id ? "page" : undefined}
        aria-label={label}
        title={title(label)}
        data-collection-id={c.id}
        draggable
        onDragStart={(e) => setDragCollection(e, c.id, c.name)}
        onKeyDown={orderKeys(order, c)}
        onContextMenu={onMenu(c)}
        {...reorder.props}
      >
        <Grip />
        <Layers className="sidebar-icon" {...ICON} />
        <span className="sidebar-label">{name}</span>
        {files > 0 && <span className="sidebar-count">{files}</span>}
      </Link>
      {children.length > 0 && (
        <button
          type="button"
          className="sidebar-disclosure"
          aria-expanded={open}
          aria-label={`Collections in ${name}`}
          title={open ? `Hide the collections in ${name}` : `Show the collections in ${name}`}
          onClick={() => folds.toggle(c.id)}
        >
          <ChevronRight size={12} strokeWidth={2} aria-hidden="true" className="sidebar-chevron" data-open={open || undefined} />
        </button>
      )}
      {children.length > 0 && open && (
        <ul className="sidebar-list sidebar-children">
          {children.map((child) => (
            <CollectionNode key={child.id} c={child} current={current} kids={kids} folds={folds} collect={collect} mover={mover} order={order} onMenu={onMenu} />
          ))}
        </ul>
      )}
    </li>
  );
}

type SectionFolds = ReturnType<typeof useFolds<string>>;

/** A right-click menu at the pointer: ``open(label, entries)`` makes the handler. */
function useMenuAt() {
  const [menu, setMenu] = useState<{ x: number; y: number; label: string; entries: MenuEntry[] } | null>(null);
  return {
    open: (label: string, entries: () => MenuEntry[]) => (e: React.MouseEvent) => {
      e.preventDefault();
      setMenu({ x: e.clientX, y: e.clientY, label, entries: entries() });
    },
    element: menu && <ContextMenu x={menu.x} y={menu.y} label={menu.label} entries={menu.entries} onClose={() => setMenu(null)} />,
  };
}

/** The Collections section: the open collections as a tree; its caption takes a
 * dropped collection to the top level. */
function CollectionsSection({ list, sections }: { list: CollectionRow[]; sections: SectionFolds }) {
  const [look] = useStyle();
  const folds = useFolds(archiveKey(FOLD_KEY), isId);
  const collect = useAddToCollection();
  const mover = useMoveCollection(list, (target) => target && folds.unfold(target.id));
  const kids = childrenOf(list);
  const location = useLocation();
  // the collection Browse shows now (a search of just that collection)
  const shown = location.pathname === "/browse" ? scopedCollection(readQuery(new URLSearchParams(location.search).get("q")).filters, list) : null;
  const current = shown && "c" in shown ? shown.c.id : null;
  const order = useCollectionOrder(list);
  const navigate = useNavigate();
  // as in Browse's collection tree: Open, New collection inside…, Merge into…, Delete…, the order
  const menu = useCollectionMenu(list, order, {
    open: (c) => navigate(collectionHref(c)),
    onDeleted: (names) => {
      // Browse leaves a search on any collection that went, the inner ones too
      if (location.pathname !== "/browse") return;
      const params = new URLSearchParams(location.search);
      const { words, filters } = readQuery(params.get("q"));
      const gone = new Set(names.map((n) => n.toLowerCase()));
      const kept = filters.filter((f) => !(f.name === "collection" && gone.has(f.value.toLowerCase())));
      if (kept.length === filters.length) return;
      const q = serializeQuery(words, kept);
      if (q) params.set("q", q);
      else params.delete("q");
      navigate(`/browse?${params}`, { replace: true });
    },
  });
  const caption = useMenuAt();
  const top = useDropTarget<number>({ read: readDragCollection, accept: mover.accept(null), onDrop: mover.move(null) });
  return (
    <>
    <Section
      title="Collections"
      to="/browse?tree=collections"
      dropProps={top.props}
      folded={sections.folded.has("collections")}
      onFold={() => sections.toggle("collections")}
      foldedCount={look === "new" ? (kids.get(null) ?? []).length + 2 : undefined}
      add={{ to: "/browse?tree=collections&new=1", label: "New collection" }}
      onMenu={caption.open("Collections", () => [{ label: "New collection", onSelect: () => menu.startNew(null) }])}
    >
      <ImportantRow />
      <StarredRow />
      {(kids.get(null) ?? []).map((c) => (
        <CollectionNode key={c.id} c={c} current={current} kids={kids} folds={folds} collect={collect} mover={mover} order={order} onMenu={menu.onContextMenu} />
      ))}
    </Section>
    {menu.view}
    {caption.element}
    </>
  );
}

/** The ! Important row, first in the Collections section: its collection page (groups,
 * no rename, close or parent actions) and, from there, Convert ##. Important. */
function ImportantRow() {
  const important = useBuiltin("important");
  const n = important.data?.members.length ?? 0;
  const title = useRowTitle();
  return (
    <li>
      <NavLink to="/important" className="sidebar-row" draggable={false} aria-label={n ? `Important (${n})` : "Important"} title={title(n ? `Important (${n})` : "Important")}>
        <span className="sidebar-icon sidebar-important" aria-hidden="true">
          <ImportantGlyph large />
        </span>
        <span className="sidebar-label">Important</span>
        {n > 0 && <span className="sidebar-count">{n}</span>}
      </NavLink>
    </li>
  );
}

/** The ★ Starred row, under Important: the ★ Ongoing built-in's collection page. */
function StarredRow() {
  const starred = useBuiltin("starred");
  const n = starred.data?.members.length ?? 0;
  const title = useRowTitle();
  const location = useLocation();
  // it opens in Browse (a search of the starred files); current while Browse shows that
  const shown = location.pathname === "/browse" ? readQuery(new URLSearchParams(location.search).get("q")).filters : [];
  const current = shown.length === 1 && shown[0].name === "is" && shown[0].value === "starred" && !shown[0].negated;
  return (
    <li>
      <Link
        to={collectionHref({ id: starred.data?.id ?? 0, name: "Starred", kind: "starred" })}
        className={current ? "sidebar-row active" : "sidebar-row"}
        aria-current={current ? "page" : undefined}
        draggable={false}
        aria-label={n ? `Starred (${n})` : "Starred"}
        title={title(n ? `Starred (${n})` : "Starred")}
      >
        <span className="sidebar-icon sidebar-starred" aria-hidden="true">
          <StarGlyph size={16} />
        </span>
        <span className="sidebar-label">Starred</span>
        {n > 0 && <span className="sidebar-count">{n}</span>}
      </Link>
    </li>
  );
}

/** The Tags section: its caption opens the Tags screen; below it the pinned tags, then the
 * most recently used ones (eight in all), each opening its files in Browse. New look: the
 * Tags screen is a row in the Archive section, and the tags are two sections, "Pinned
 * tags" and "Recent tags" (none shown while there are none). */
function TagsSection({ sections }: { sections: SectionFolds }) {
  const tags = useSidebarTags();
  const location = useLocation();
  const [look] = useStyle();
  const shown = tags.data ?? [];
  // rename, merge, pin and delete, as in Browse's tag tree (right-click a tag); New tag on the caption
  const all = useAllTags();
  const manager = useTagManager(all.data?.tags ?? []);
  const menu = useMenuAt();
  const info = (t: SidebarTag): TagInfo => all.data?.tags.find((x) => x.name === t.name) ?? { ...t, group_id: null };
  const onCaption = menu.open("Tags", () => [{ label: "New tag", onSelect: () => manager.open({ kind: "create" }) }]);
  const extras = (
    <>
      {menu.element}
      {manager.view}
    </>
  );
  // the tags Browse filters by now: `tag:` filters in the search, or an older `?tag=` link
  const current = location.pathname === "/browse" ? browseTags(location.search) : [];
  const rows = (list: typeof shown) =>
    list.map((t) => {
      const name = visible(t.name);
      const Icon = t.pinned ? Pin : TagIcon;
      const isCurrent = current.length === 1 && current[0] === t.name;
      return (
        <li key={t.name}>
          {/* a plain Link: a NavLink would mark every tag current on /browse, since they
              all share that path and differ only in the query */}
          <Link
            to={`/browse?${new URLSearchParams({ q: tagFilter(t.name) })}`}
            className={isCurrent ? "sidebar-row active" : "sidebar-row"}
            aria-label={`${name} (${t.files})`}
            aria-current={isCurrent ? "page" : undefined}
            title={t.pinned ? `${name} (pinned)` : name}
            onContextMenu={menu.open(`Actions for ${name}`, () => manager.shortMenu(info(t)))}
          >
            <Icon className="sidebar-icon" {...ICON} />
            <span className="sidebar-label">{name}</span>
            {t.files > 0 && <span className="sidebar-count">{t.files}</span>}
          </Link>
        </li>
      );
    });
  if (look === "new") {
    const pinned = shown.filter((t) => t.pinned);
    const recent = shown.filter((t) => !t.pinned);
    return (
      <>
        {pinned.length > 0 && (
          <Section title="Pinned tags" folded={sections.folded.has("pinned-tags")} onFold={() => sections.toggle("pinned-tags")} foldedCount={pinned.length} onMenu={onCaption}>
            {rows(pinned)}
          </Section>
        )}
        {recent.length > 0 && (
          <Section title="Recent tags" folded={sections.folded.has("recent-tags")} onFold={() => sections.toggle("recent-tags")} foldedCount={recent.length} onMenu={onCaption}>
            {rows(recent)}
          </Section>
        )}
        {extras}
      </>
    );
  }
  return (
    <>
      <Section title="Tags" to="/browse?tree=tags" folded={sections.folded.has("tags")} onFold={() => sections.toggle("tags")} onMenu={onCaption}>
        {rows(shown)}
      </Section>
      {extras}
    </>
  );
}

/** New look: the Tags screen's row in the Archive section, counting every tag. */
function TagsRow() {
  const all = useAllTags();
  return <Row to="/browse?tree=tags" icon={TagIcon} label="Tags" count={all.data?.tags.length} />;
}

/** The tags a Browse address filters by, when it filters by tags alone (no words or
 * other filters), so a sidebar tag shows as current only for its own plain tag search. */
function browseTags(search: string): string[] {
  const params = new URLSearchParams(search);
  const { words, filters } = readQuery(params.get("q"));
  const tags = positiveTags(filters);
  if (words.trim() || tags.length !== filters.length) return [];
  return [...params.getAll("tag"), ...tags.map((f) => f.value)];
}

export function trayIcon(tray: TrayDef): LucideIcon {
  const key = `${tray.id} ${tray.name}`.toLowerCase();
  if (/follow|waiting|odota|seuranta/.test(key)) return Hourglass;
  if (/pay|bill|invoice|lasku|maksu/.test(key)) return Euro;
  if (/read|lue|luettava/.test(key)) return BookOpen;
  if (/action|task|todo|tee|hoida/.test(key)) return CircleCheck;
  return ListTodo;
}

type Props = {
  /** The sidebar's foot: the status line. */
  footer?: ReactNode;
  /** Opens search and jump; New look: the search field under the archive's name. */
  onSearch?: () => void;
};

/** The app's sidebar: Today, Inbox, Browse, the trays, the open collections (a tree)
 * and the rest of the archive (Trays, Collections and Archive fold). Documents dragged onto a tray are put in it; onto a collection, added to
 * it. A collection dragged onto another goes inside it; onto the caption, to the top. */
export function Sidebar({ footer, onSearch }: Props) {
  const [look] = useStyle();
  const status = useStatus();
  const today = useToday();
  useTodayFollowsInbox(status.data);
  const trays = useTrays();
  const collections = useCollections("open");
  const due = today.data?.attention.filter((a) => a.level === "overdue" || a.level === "today").length ?? 0;
  const openIn = (trayId: string) => today.data?.overview.trays.find((t) => t.tray_id === trayId)?.open ?? 0;
  const quick = useQuickPut();
  const back = useDropBackToInbox();
  const sections = useFolds(SECTION_FOLD_KEY, isName);
  const trayTotal = trays.data?.trays.reduce((n, t) => n + openIn(t.id), 0) ?? 0;
  return (
    <aside className="sidebar">
      <ArchiveSwitcher />
      {look === "new" && onSearch && <SidebarSearch onOpen={onSearch} />}
      <nav aria-label="Main" className="sidebar-nav">
        <ul className="sidebar-list">
          <Row to="/" end icon={Sun} label="Today" badge={due} />
          <DropRow
            to="/inbox"
            icon={Inbox}
            label="Inbox"
            count={status.data?.inbox_count}
            accept={back.accept}
            onDrop={back.drop}
          />
          <Row to="/browse" icon={FolderTree} label="Browse" />
          <Section
            title="Trays"
            to="/trays"
            folded={sections.folded.has("trays")}
            onFold={() => sections.toggle("trays")}
            foldedCount={trayTotal}
          >
            {trays.data?.trays.map((t) => (
              <DropRow
                key={t.id}
                to={`/trays/${encodeURIComponent(t.id)}`}
                icon={trayIcon(t)}
                label={visible(t.name)}
                count={openIn(t.id)}
                accept={() => true}
                onDrop={(ids) => {
                  const name = ids.length === 1 ? draggedLabel() : null;
                  void quick.put({ tray: t.id, trayName: t.name, ids, name });
                }}
              />
            ))}
          </Section>
          <CollectionsSection list={collections.data ?? []} sections={sections} />
          <TagsSection sections={sections} />
          <Section title="Archive" folded={sections.folded.has("archive")} onFold={() => sections.toggle("archive")}>
            {look === "new" ? (
              <>
                <TagsRow />
                <Row to="/activity" icon={History} label="Activity" />
                <Row to="/maintenance" icon={Wrench} label="Maintenance" />
                <Row to="/ask" icon={MessageCircleQuestion} label="Ask" />
              </>
            ) : (
              <>
                <Row to="/ask" icon={MessageCircleQuestion} label="Ask" />
                <Row to="/activity" icon={History} label="Activity" />
                <Row to="/maintenance" icon={Wrench} label="Maintenance" />
              </>
            )}
            <Row to="/settings" icon={Settings} label="Settings" />
            <Row to="/help" icon={CircleHelp} label="Help" />
          </Section>
        </ul>
      </nav>
      {footer && <div className="sidebar-foot">{footer}</div>}
      {back.view}
    </aside>
  );
}
