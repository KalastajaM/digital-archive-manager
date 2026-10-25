import {
  BookOpen,
  ChevronRight,
  CircleCheck,
  CircleHelp,
  Euro,
  Hourglass,
  FolderTree,
  History,
  Inbox,
  Layers,
  MessageCircleQuestion,
  ListTodo,
  type LucideIcon,
  Pin,
  Settings,
  Sun,
  Tag as TagIcon,
} from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  archiveKey,
  type CollectionRow,
  errorText,
  type TrayDef,
  useBuiltin,
  useCollectionMembers,
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
  readDragCollection,
  readDragFolder,
  readDragFiles,
  setDragCollection,
  useDropTarget,
} from "../../dnd";
import { plural } from "../../format";
import { visible } from "../../text";
import { changeToast } from "../collectionText";
import { ArchiveSwitcher } from "../ArchiveSwitcher";
import { ImportantGlyph, StarGlyph } from "../MarkIcons";
import {
  childrenOf,
} from "../collectionTree";
import { anyMoveRunning, backToInbox, inboxRefusal, MOVE_BUSY, useInboxFolder, useMoveFlow } from "../MoveTo";
import { useBlockToastActions, useToast } from "../Toasts";
import {
  type CollectionOrder,
  orderKeys,
  useCollectionOrder,
  useMoveCollection,
  useOrderMenu,
  useReorderRow,
} from "../useCollectionOrder";
import { useUndoConfirm } from "../UndoConfirm";
import { useQuickPut } from "../useQuickPut";

const ICON = { size: 16, strokeWidth: 1.75, "aria-hidden": true } as const;

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

/** One sidebar row: a NavLink named "Label (n)" so the count is read along with it. */
function Row({ to, end, icon: Icon, label, count, badge, dropProps }: RowProps) {
  const n = badge || count || 0;
  return (
    <li>
      <NavLink
        to={to}
        end={end}
        className="sidebar-row"
        aria-label={n ? `${label} (${n})` : label}
        {...dropProps}
      >
        <Icon className="sidebar-icon" {...ICON} />
        <span className="sidebar-label">{label}</span>
        {badge ? (
          <span className="sidebar-badge">{badge}</span>
        ) : count ? (
          <span className="sidebar-count">{count}</span>
        ) : null}
      </NavLink>
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
  children,
}: {
  title: string;
  to?: string;
  dropProps?: DropTarget["props"];
  folded: boolean;
  onFold: () => void;
  foldedCount?: number;
  children: ReactNode;
}) {
  return (
    <li className="sidebar-section">
      <div className="sidebar-section-head">
        {to ? (
          <NavLink to={to} end className="sidebar-section-title" {...dropProps}>
            {title}
          </NavLink>
        ) : (
          <h3 className="sidebar-section-title">{title}</h3>
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
const dropped = (ids: string[]) => {
  const label = ids.length === 1 ? draggedLabel() : null;
  return label !== null ? visible(label) : plural(ids.length, "file");
};

/** Dropping documents on a collection adds them as members, ungrouped. No confirm: a
 * member change moves no file (the Phase 2 ruling); the toast says what Ongoing did. */
function useAddToCollection() {
  const members = useCollectionMembers();
  const toast = useToast();
  const adding = useRef(new Set<number>()); // synchronous: a second drop sees it at once
  const accept = (c: CollectionRow) => (ids: string[]) => {
    const name = visible(c.name);
    if (c.state === "closed") return `${name} is closed: reopen it to add files`;
    const have = new Set(c.members.map((m) => m.drive_id));
    if (ids.every((id) => have.has(id))) return `Already in ${name}`;
    return true;
  };
  const add = (c: CollectionRow) => (ids: string[]) => {
    if (adding.current.has(c.id)) return;
    adding.current.add(c.id);
    const what = dropped(ids);
    const name = visible(c.name);
    members
      .mutateAsync({ id: c.id, add: ids })
      .then((result) => toast(changeToast(`Added ${what} to ${name}`, result)))
      .catch((err) => toast({ kind: "error", text: `Could not add ${what} to ${name}: ${visible(errorText(err))}` }))
      .finally(() => adding.current.delete(c.id));
  };
  return { accept, add };
}

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
type Dragged = { kind: "files"; ids: string[] } | { kind: "collection"; id: number };
/** What a collection row takes: files, or a folder from Browse (as one member, so
 * everything in it belongs), or another collection. */
const readFilesOrCollection = (e: Parameters<typeof readDragFiles>[0]): Dragged | null => {
  const id = readDragCollection(e);
  if (id !== null) return { kind: "collection", id };
  const folder = readDragFolder(e);
  if (folder !== null) return { kind: "files", ids: [folder] };
  const ids = readDragFiles(e);
  return ids === null ? null : { kind: "files", ids };
};

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
function CollectionNode({ c, kids, folds, collect, mover, order, onMenu }: TreeProps) {
  const children = kids.get(c.id) ?? [];
  const open = !folds.folded.has(c.id);
  const addFiles = collect.accept(c);
  const add = collect.add(c);
  const takeCollection = mover.accept(c);
  const moveHere = mover.move(c);
  const target = useDropTarget<Dragged>({
    read: readFilesOrCollection,
    accept: (d) => (d.kind === "files" ? addFiles(d.ids) : takeCollection(d.id)),
    onDrop: (d) => (d.kind === "files" ? add(d.ids) : moveHere(d.id)),
  });
  // near a sibling's top or bottom edge a dragged collection is put before or after it
  // (a drop line); in the middle it goes inside, as before
  const reorder = useReorderRow(order, c, target.props);
  const name = visible(c.name);
  return (
    <li className="sidebar-tree-item">
      <NavLink
        to={`/collections/${c.id}`}
        className={children.length > 0 ? "sidebar-row sidebar-row-parent" : "sidebar-row"}
        aria-label={name}
        data-collection-id={c.id}
        draggable
        onDragStart={(e) => setDragCollection(e, c.id, c.name)}
        onKeyDown={orderKeys(order, c)}
        onContextMenu={onMenu(c)}
        {...reorder.props}
      >
        <Layers className="sidebar-icon" {...ICON} />
        <span className="sidebar-label">{name}</span>
      </NavLink>
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
            <CollectionNode key={child.id} c={child} kids={kids} folds={folds} collect={collect} mover={mover} order={order} onMenu={onMenu} />
          ))}
        </ul>
      )}
    </li>
  );
}

type SectionFolds = ReturnType<typeof useFolds<string>>;

/** The Collections section: the open collections as a tree; its caption takes a
 * dropped collection to the top level. */
function CollectionsSection({ list, sections }: { list: CollectionRow[]; sections: SectionFolds }) {
  const folds = useFolds(archiveKey(FOLD_KEY), isId);
  const collect = useAddToCollection();
  const mover = useMoveCollection(list, (target) => target && folds.unfold(target.id));
  const kids = childrenOf(list);
  const order = useCollectionOrder(list);
  const menu = useOrderMenu(order);
  const top = useDropTarget<number>({ read: readDragCollection, accept: mover.accept(null), onDrop: mover.move(null) });
  return (
    <Section
      title="Collections"
      to="/collections"
      dropProps={top.props}
      folded={sections.folded.has("collections")}
      onFold={() => sections.toggle("collections")}
    >
      <ImportantRow />
      <StarredRow />
      {(kids.get(null) ?? []).map((c) => (
        <CollectionNode key={c.id} c={c} kids={kids} folds={folds} collect={collect} mover={mover} order={order} onMenu={menu.onContextMenu} />
      ))}
      {menu.element}
    </Section>
  );
}

/** The ! Important row, first in the Collections section: its collection page (groups,
 * no rename, close or parent actions) and, from there, Convert ##. Important. */
function ImportantRow() {
  const important = useBuiltin("important");
  const n = important.data?.members.length ?? 0;
  return (
    <li>
      <NavLink to="/important" className="sidebar-row" draggable={false} aria-label={n ? `Important (${n})` : "Important"}>
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
  return (
    <li>
      <NavLink to="/starred" className="sidebar-row" draggable={false} aria-label={n ? `Starred (${n})` : "Starred"}>
        <span className="sidebar-icon sidebar-starred" aria-hidden="true">
          <StarGlyph size={16} />
        </span>
        <span className="sidebar-label">Starred</span>
        {n > 0 && <span className="sidebar-count">{n}</span>}
      </NavLink>
    </li>
  );
}

/** The Tags section: its caption opens the Tags screen; below it the pinned tags, then the
 * most recently used ones (eight in all), each opening its files in Browse. */
function TagsSection({ sections }: { sections: SectionFolds }) {
  const tags = useSidebarTags();
  const location = useLocation();
  const shown = tags.data ?? [];
  // the tag whose filter Browse shows now (the only one)
  const current =
    location.pathname === "/browse" ? new URLSearchParams(location.search).getAll("tag") : [];
  return (
    <Section
      title="Tags"
      to="/tags"
      folded={sections.folded.has("tags")}
      onFold={() => sections.toggle("tags")}
    >
      {shown.map((t) => {
        const name = visible(t.name);
        const Icon = t.pinned ? Pin : TagIcon;
        return (
          <li key={t.name}>
            <NavLink
              to={`/browse?${new URLSearchParams({ tag: t.name, q: "" })}`}
              className="sidebar-row"
              aria-label={`${name} (${t.files})`}
              aria-current={current.length === 1 && current[0] === t.name ? "page" : undefined}
              title={t.pinned ? `${name} (pinned)` : name}
            >
              <Icon className="sidebar-icon" {...ICON} />
              <span className="sidebar-label">{name}</span>
              {t.files > 0 && <span className="sidebar-count">{t.files}</span>}
            </NavLink>
          </li>
        );
      })}
    </Section>
  );
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
};

/** The app's sidebar: Today, Inbox, Browse, the trays, the open collections (a tree)
 * and the rest of the archive (Trays, Collections and Archive fold). Documents dragged onto a tray are put in it; onto a collection, added to
 * it. A collection dragged onto another goes inside it; onto the caption, to the top. */
export function Sidebar({ footer }: Props) {
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
            <Row to="/ask" icon={MessageCircleQuestion} label="Ask" />
            <Row to="/activity" icon={History} label="Activity" />
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
