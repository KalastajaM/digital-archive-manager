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
  Sun,
} from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  archiveKey,
  type CollectionRow,
  errorText,
  type TrayDef,
  useBuiltin,
  useCollectionMembers,
  useCollections,
  useStatus,
  useToday,
  useTodayFollowsInbox,
  useSetCollectionParent,
  useTrays,
} from "../../api/client";
import {
  type DropTarget,
  draggedLabel,
  draggedPaths,
  readDragCollection,
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
  collectionMoveRunning,
  endCollectionMove,
  movedText,
  recreatedLinks,
  moveRefusal,
  startCollectionMove,
} from "../collectionTree";
import { anyMoveRunning, backToInbox, inboxRefusal, MOVE_BUSY, useInboxFolder, useMoveFlow } from "../MoveTo";
import { useBlockToastActions, useToast } from "../Toasts";
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
 * ``dropProps`` make the caption a drop target (the Collections caption: the top level). */
function Section({
  title,
  to,
  dropProps,
  children,
}: {
  title: string;
  to?: string;
  dropProps?: DropTarget["props"];
  children: ReactNode;
}) {
  return (
    <li className="sidebar-section">
      {to ? (
        <NavLink to={to} end className="sidebar-section-title" {...dropProps}>
          {title}
        </NavLink>
      ) : (
        <h3 className="sidebar-section-title">{title}</h3>
      )}
      <ul className="sidebar-list">{children}</ul>
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
const readFilesOrCollection = (e: Parameters<typeof readDragFiles>[0]): Dragged | null => {
  const id = readDragCollection(e);
  if (id !== null) return { kind: "collection", id };
  const ids = readDragFiles(e);
  return ids === null ? null : { kind: "files", ids };
};

const FOLD_KEY = "dam.sidebar.collections.folded.v1";

/** The folded parents (collection ids), kept in this browser's localStorage. Every
 * storage access is in try/catch: private windows and blocked site data throw. */
function readFolds(): Set<number> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(archiveKey(FOLD_KEY)) ?? "[]");
    return new Set(Array.isArray(value) ? value.filter((x): x is number => Number.isSafeInteger(x)) : []);
  } catch {
    return new Set();
  }
}

function useFolds() {
  const [folded, setFolded] = useState<Set<number>>(readFolds);
  // Saved after each change; the updates are functional, so a fold made while a move
  // runs is never undone by the move's unfold (or the other way round).
  useEffect(() => {
    try {
      localStorage.setItem(archiveKey(FOLD_KEY), JSON.stringify([...folded]));
    } catch {
      // Not saved: the fold still applies until the page reloads.
    }
  }, [folded]);
  return {
    folded,
    toggle: (id: number) =>
      setFolded((now) => {
        const next = new Set(now);
        if (!next.delete(id)) next.add(id);
        return next;
      }),
    unfold: (id: number) =>
      setFolded((now) => {
        if (!now.has(id)) return now;
        const next = new Set(now);
        next.delete(id);
        return next;
      }),
  };
}

/** Dropping a collection on another moves it inside; on the section caption, to the
 * top. No confirm (as for member and group changes): the Ongoing sync only moves
 * app-owned entries, journaled, and moving it back reverses it; the toast says what
 * Ongoing did. A cycle or a closed parent is refused before the drop. */
function useMoveCollection(list: CollectionRow[], onMoved: (target: CollectionRow | null) => void) {
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
    const open = { label: "Open", run: () => navigate(`/collections/${id}`) };
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

type TreeProps = {
  c: CollectionRow;
  kids: Map<number | null, CollectionRow[]>;
  folds: ReturnType<typeof useFolds>;
  collect: ReturnType<typeof useAddToCollection>;
  mover: ReturnType<typeof useMoveCollection>;
};

/** One collection in the sidebar tree, its children below it (unless folded). The row
 * takes dropped files (members) and dropped collections (moved inside), and drags as
 * a collection itself; "Move to…" on the collection page is the keyboard way. */
function CollectionNode({ c, kids, folds, collect, mover }: TreeProps) {
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
  const name = visible(c.name);
  return (
    <li className="sidebar-tree-item">
      <NavLink
        to={`/collections/${c.id}`}
        className={children.length > 0 ? "sidebar-row sidebar-row-parent" : "sidebar-row"}
        aria-label={name}
        draggable
        onDragStart={(e) => setDragCollection(e, c.id, c.name)}
        {...target.props}
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
            <CollectionNode key={child.id} c={child} kids={kids} folds={folds} collect={collect} mover={mover} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** The Collections section: the open collections as a tree; its caption takes a
 * dropped collection to the top level. */
function CollectionsSection({ list }: { list: CollectionRow[] }) {
  const folds = useFolds();
  const collect = useAddToCollection();
  const mover = useMoveCollection(list, (target) => target && folds.unfold(target.id));
  const kids = childrenOf(list);
  const top = useDropTarget<number>({ read: readDragCollection, accept: mover.accept(null), onDrop: mover.move(null) });
  return (
    <Section title="Collections" to="/collections" dropProps={top.props}>
      <ImportantRow />
      <StarredRow />
      {(kids.get(null) ?? []).map((c) => (
        <CollectionNode key={c.id} c={c} kids={kids} folds={folds} collect={collect} mover={mover} />
      ))}
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
      <NavLink to="/important" className="sidebar-row" aria-label={n ? `Important (${n})` : "Important"}>
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
      <NavLink to="/starred" className="sidebar-row" aria-label={n ? `Starred (${n})` : "Starred"}>
        <span className="sidebar-icon sidebar-starred" aria-hidden="true">
          <StarGlyph size={16} />
        </span>
        <span className="sidebar-label">Starred</span>
        {n > 0 && <span className="sidebar-count">{n}</span>}
      </NavLink>
    </li>
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

/** The app's sidebar: Today, Inbox, the trays, the open collections (a tree) and the
 * archive. Documents dragged onto a tray are put in it; onto a collection, added to
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
          <Section title="Trays" to="/trays">
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
          <CollectionsSection list={collections.data ?? []} />
          <Section title="Archive">
            <Row to="/browse" icon={FolderTree} label="Browse" />
            <Row to="/ask" icon={MessageCircleQuestion} label="Ask" />
            <Row to="/activity" icon={History} label="Activity" />
            <Row to="/help" icon={CircleHelp} label="Help" />
          </Section>
        </ul>
      </nav>
      {footer && <div className="sidebar-foot">{footer}</div>}
      {back.view}
    </aside>
  );
}
