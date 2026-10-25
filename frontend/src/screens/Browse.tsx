import { Building2, ChevronLeft, ChevronRight, Columns2, File, Folder, FolderInput, FolderPlus, User } from "lucide-react";
import {
  type DragEvent,
  Fragment,
  type MouseEvent,
  type ReactNode,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  archiveKey,
  ApiError,
  type DirEntry,
  errorText,
  type FlatSort,
  useBrowse,
  type Mark,
  useBrowseFiles,
  useIsBlocked,
  LOCKED_REASON,
  useCollectionsWithMarked,
  useCreateFolder,
  useStatus,
} from "../api/client";
import { childrenOf } from "../components/collectionTree";
import { FitText } from "../components/FitText";
import type { PreviewFile } from "../components/FilePreview";
import { BUILTIN_LABEL, ImportantGlyph, MarkIcons, StarGlyph } from "../components/MarkIcons";
import { MarkToggles } from "../components/MarkToggles";
import {
  anyMoveRunning,
  backToInbox,
  deletionRefusal,
  FILES_MOVED_EVENT,
  type FilesMovedDetail,
  inboxRefusal,
  MOVE_BUSY,
  type MoveRequest,
  moveRefusal,
  MoveToSheet,
  sourceRefusal,
  useInboxFolder,
  useMoveFlow,
} from "../components/MoveTo";
import { isTrashKey, TRASH_BUSY, TrashButton, useTrash } from "../components/Trash";
import { undoAction, useBlockToastActions, useToast } from "../components/Toasts";
import { allMarked, useBatchMark } from "../components/useBatchMark";
import { useNewFolder } from "../components/NewFolder";
import { useSetupFolders } from "../components/SetupFolders";
import { ContextMenu } from "../components/ui/ContextMenu";
import { EmptyState } from "../components/ui/EmptyState";
import { IconButton } from "../components/ui/IconButton";
import { Menu, type MenuEntry } from "../components/ui/Menu";
import { Segmented } from "../components/ui/Segmented";
import { Splitter, useSplitWidth } from "../components/ui/SplitPane";
import { Toolbar } from "../components/ui/Toolbar";
import { useUndoConfirm } from "../components/UndoConfirm";
import { type QLFile, useQuickLook } from "../components/useQuickLook";
import { type DropTarget, dragSelection, setDragFiles, setDragFolder, useDropTarget } from "../dnd";
import { dialogOpen, isShortcut, isTyping, OWN_ENTER, useKeydown } from "../keyboard";
import { publishSelection } from "../selection";
import { formatSize, groupDigits, shortDate } from "../format";
import { visible } from "../text";
import { type KeyHint, KeyHints } from "../components/KeyHints";
import { type AssignKind, AssignSheet } from "../components/zones/FromFor";
import { FilePanel, FolderPanel } from "./FilePanel";
import { useSearch } from "./useSearch";

/** One row of the folder listing or of the search results. */
const KEYS: KeyHint[] = [
  [["↑", "↓"], "move"],
  [["↩"], "open"],
  [["⌫"], "up"],
  [["Space"], "Quick Look"],
  [["⌘", "⇧"], "click to select"],
  [["⌘A"], "select all"],
  [["⇧⌘M"], "move to…"],
  [["⇧⌘N"], "new folder"],
  [["⌘⌫"], "move to To Delete"],
  [[], "drag files onto a folder to move them"],
];

type Item = {
  drive_id: string;
  path: string;
  name: string;
  is_dir: boolean;
  is_link: boolean;
  snippet?: string;
  marks?: Mark[];
  size?: number | null;
  mtime?: number | null;
};

type PaneId = "left" | "right";
const PANES: PaneId[] = ["left", "right"];
const PANE_NAME: Record<PaneId, string> = { left: "Left pane", right: "Right pane" };

/** Folders: the folder tree as it is; Files: every file below the folder, flat. */
export type PaneView = "folders" | "files";
/** What one pane shows: its folder, its collection filter (an id) and its view. */
type PaneState = { path: string; collection: number | null; view: PaneView };
/** The URL parameters of a pane's filter and view: one pane uses ?collection=&view=,
 * two use ?lcol=&lview=&rcol=&rview= (beside ?left=&right=). */
const PARAM = {
  one: { collection: "collection", view: "view" },
  left: { collection: "lcol", view: "lview" },
  right: { collection: "rcol", view: "rview" },
} as const;
const idParam = (raw: string | null): number | null => {
  const n = raw === null ? Number.NaN : Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
};
const viewParam = (raw: string | null): PaneView => (raw === "files" ? "files" : "folders");

type SortState = { sort: FlatSort; dir: "asc" | "desc" };
const SORT_COLUMNS: { sort: FlatSort; label: string }[] = [
  { sort: "name", label: "Name" },
  { sort: "folder", label: "Folder" },
  { sort: "date", label: "Date" },
  { sort: "size", label: "Size" },
];
/** A newly chosen column starts newest/largest first for dates and sizes, A–Z otherwise. */
const firstDir = (sort: FlatSort): "asc" | "desc" => (sort === "date" || sort === "size" ? "desc" : "asc");

/** Where the two-pane choice is remembered (this browser only). */
export const SPLIT_KEY = "dam.browse.split";
function readSplit(): boolean {
  try {
    return localStorage.getItem(archiveKey(SPLIT_KEY)) === "1";
  } catch {
    return false; // storage blocked: one pane
  }
}
function writeSplit(split: boolean) {
  try {
    localStorage.setItem(archiveKey(SPLIT_KEY), split ? "1" : "0");
  } catch {
    // storage blocked: the choice lasts for this page only
  }
}

/** The list's share of the width with one pane, in percent (this browser only). */
export const LIST_WIDTH_KEY = "dam.browse.listwidth";
const LIST_SPLIT = { min: 25, max: 75, initial: 45 };

const NONE: Set<string> = new Set();
const parentOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");

const byText = (a: string, b: string) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true });
/** Search hits in a column's order (ties by name, then path); files with no date or size last. */
function sortHits(items: Item[], { sort, dir }: SortState): Item[] {
  const key = (it: Item): string | number | null =>
    sort === "name" ? it.name : sort === "folder" ? parentOf(it.path) : sort === "date" ? (it.mtime ?? null) : (it.size ?? null);
  const sign = dir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
    if (ka === null || kb === null) {
      if (ka !== kb) return ka === null ? 1 : -1;
    } else {
      const c = typeof ka === "number" ? ka - (kb as number) : byText(ka, kb as string);
      if (c !== 0) return sign * c;
    }
    return byText(a.name, b.name) || byText(a.path, b.path);
  });
}
const extOf = (name: string) => (name.includes(".") ? name.slice(name.lastIndexOf(".") + 1).toLowerCase() : null);
const previewOf = (item: Item): PreviewFile => ({
  drive_id: item.drive_id,
  path: item.path,
  ext: extOf(item.name),
  is_link: item.is_link,
});

/** A search snippet: ``[...]`` marks a match. Built from text nodes and <mark>, never HTML. */
export function Snippet({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  const match = /\[([^[\]]*)\]/g;
  let last = 0;
  for (let m = match.exec(text); m !== null; m = match.exec(text)) {
    if (m.index > last) parts.push(<Fragment key={last}>{visible(text.slice(last, m.index))}</Fragment>);
    parts.push(<mark key={`m${m.index}`}>{visible(m[1])}</mark>);
    last = match.lastIndex;
  }
  if (last < text.length) parts.push(<Fragment key={last}>{visible(text.slice(last))}</Fragment>);
  return <span className="snippet">{parts}</span>;
}

/** The header checkbox of a list: checks every file of the pane, or clears them when all
 * are checked; mixed while only some are. */
function SelectAll({ checked, total, onChange }: { checked: number; total: number; onChange: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const all = total > 0 && checked === total;
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = checked > 0 && !all;
  }, [checked, all]);
  return (
    <input
      ref={ref}
      type="checkbox"
      className="select-all"
      aria-label="Select all files"
      checked={all}
      disabled={total === 0}
      onChange={onChange}
    />
  );
}

/** The pane's folder as a path of links; each link goes there in this pane only. */
function Breadcrumb({
  path,
  href,
  go,
}: {
  path: string;
  href: (to: string) => string;
  go: (to: string) => void;
}) {
  const parts = path ? path.split("/") : [];
  const link = (to: string, label: string) => (
    <Link
      to={href(to)}
      draggable={false}
      title={label}
      onClick={(e) => {
        e.preventDefault();
        go(to);
      }}
    >
      {label}
    </Link>
  );
  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      <ol>
        <li>{parts.length === 0 ? <span aria-current="page">Archive</span> : link("", "Archive")}</li>
        {parts.map((part, i) => {
          const here = parts.slice(0, i + 1).join("/");
          return (
            <li key={here}>
              {i === parts.length - 1 ? (
                <span aria-current="page" title={visible(part)}>
                  {visible(part)}
                </span>
              ) : link(here, visible(part))}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Per pane: the row the keyboard is on, the checked rows and the ⇧-click anchor. They
 * belong to what is listed (``view``): a new folder or query starts afresh. */
type PaneSelection = { view: string; index: number; ids: string[]; anchor: string | null; touched: boolean };
const fresh = (view: string): PaneSelection => ({ view, index: 0, ids: [], anchor: null, touched: false });

type History = { back: string[]; forward: string[] };

type DropProps = {
  /** Already there, or not a folder: no highlight. A string: "not allowed" and why. */
  accept: (ids: string[]) => boolean | string;
  onDrop: (ids: string[]) => void;
};

type RowProps = {
  item: Item;
  current: boolean;
  checked: boolean;
  /** The Files view: the folder, date and size columns. */
  columns?: boolean;
  /** The ids a drag of this row carries; null: the row is not draggable (as files). */
  dragIds: (() => string[]) | null;
  /** A folder row's own drag (to a collection), instead of ``dragIds``. */
  onDragStart?: (e: DragEvent<HTMLLIElement>) => void;
  /** The archive paths of dragged ids (unknown ones leave the drag without paths). */
  dragPaths?: (ids: string[]) => string[];
  onToggle: () => void;
  onClick: (e: MouseEvent) => void;
  /** Drop-target props (folder rows only). */
  dropProps?: DropTarget["props"];
  /** Right-click (folder rows only). */
  onContextMenu?: (e: MouseEvent) => void;
};

/** One listed entry. Files drag (with the selection), unless their area keeps them. */
function EntryRow({
  item,
  current,
  checked,
  columns = false,
  dragIds,
  dragPaths,
  onDragStart,
  onToggle,
  onClick,
  dropProps,
  onContextMenu,
}: RowProps) {
  const Icon = item.is_dir ? Folder : File;
  const cls = [checked && "checked", item.is_dir && "entry-row-dir"].filter(Boolean).join(" ");
  const main = (
    <>
      <Icon className="entry-icon" size={16} strokeWidth={1.5} aria-hidden="true" />
      {columns ? (
        <FitText mode="name" className="entry-name" text={visible(item.name)} />
      ) : (
        <span className="entry-name">{visible(item.name)}</span>
      )}
      <MarkIcons marks={item.marks} driveId={item.is_dir ? undefined : item.drive_id} path={item.path} />
      {item.is_link && (
        <span className="link-icon" role="img" aria-label="Symbolic link" title="Symbolic link">
          ↪
        </span>
      )}
    </>
  );
  return (
    <li
      className={cls || undefined}
      aria-current={current ? "true" : undefined}
      draggable={dragIds || onDragStart ? true : undefined}
      onDragStart={
        onDragStart ??
        (dragIds
          ? (e) => {
              const ids = dragIds();
              setDragFiles(e, ids, visible(item.name), dragPaths?.(ids));
            }
          : undefined)
      }
      onContextMenu={onContextMenu}
      {...dropProps}
    >
      {item.is_dir ? (
        // folders are opened, not selected: a spacer keeps the names aligned
        <span className="entry-check-spacer" aria-hidden="true" />
      ) : (
        <input type="checkbox" aria-label={`Select ${visible(item.name)}`} checked={checked} onChange={onToggle} />
      )}
      <button
        type="button"
        className={item.is_dir ? "entry entry-dir" : "entry"}
        data-quicklook={item.is_dir ? undefined : true}
        onClick={onClick}
      >
        {columns ? (
          <>
            <span className="entry-main">{main}</span>
            <FitText mode="path" className="entry-col entry-folder" text={visible(parentOf(item.path)) || "Archive"} />
            <span className="entry-col entry-date">{item.mtime != null ? shortDate(item.mtime) : ""}</span>
            <span className="entry-col entry-size">{item.size != null ? formatSize(item.size) : ""}</span>
          </>
        ) : (
          main
        )}
        {item.snippet !== undefined && item.snippet !== item.name && <Snippet text={item.snippet} />}
      </button>
    </li>
  );
}

/** A folder row: a drop target (files dropped here move into it). It drags only as a
 * folder, which only a collection in the sidebar takes (``collectable``: its area allows
 * that); it is never moved by a drag. */
function FolderRow({ drop, collectable, ...row }: Omit<RowProps, "dropProps" | "dragIds"> & { drop: DropProps; collectable: boolean }) {
  const target = useDropTarget(drop);
  const { item } = row;
  return (
    <EntryRow
      {...row}
      dragIds={null}
      onDragStart={collectable ? (e) => setDragFolder(e, item.drive_id, visible(item.name)) : undefined}
      dropProps={target.props}
    />
  );
}

/** Why a folder cannot be added to a collection (null: it can): the app's own areas. */
export function folderCollectRefusal(
  path: string,
  special: { quarantine: string; ongoing: string; important: string } | undefined,
): string | null {
  if (!special) return "The special folders are not known yet";
  for (const area of [special.quarantine, special.ongoing, special.important]) {
    if (isUnder(path, area)) return `Folders in ${visible(area)} can't be added to a collection`;
  }
  return null;
}

const fold = (s: string) => s.normalize("NFC").toLowerCase();
const isUnder = (path: string, area: string) => fold(path) === fold(area) || fold(path).startsWith(`${fold(area)}/`);

/** Why "New folder" is off for a pane (null: a folder can be made in what it shows). The
 * server refuses the same places; this only says so first. */
function newFolderRefusal(
  pane: { path: string; collection: number | null; view: PaneView },
  searching: boolean,
  special: { quarantine: string; ongoing: string; important: string } | undefined,
): string | null {
  if (searching) return "Search results are not a folder: open a folder first";
  if (pane.view === "files") return "Switch to Folders to make a folder here";
  if (pane.collection !== null) return "Show all files to make a folder here (a filter hides it)";
  if (!special) return "The special folders are not known yet";
  for (const area of [special.quarantine, special.ongoing, special.important]) {
    if (isUnder(pane.path, area)) return `Folders can't be made in ${visible(area)}`;
  }
  return null;
}

/** The new folder's row at the top of the list: "untitled folder" selected; Enter makes
 * the folder, Esc (or leaving the field) cancels. A refusal stays under the field. */
function NewFolderRow({
  onCreate,
  onCancel,
}: {
  /** The reason it was refused, or null once the folder is made. */
  onCreate: (name: string) => Promise<string | null>;
  onCancel: () => void;
}) {
  const [text, setText] = useState("untitled folder");
  const [problem, setProblem] = useState<string | null>(null);
  const ref = useRef<HTMLInputElement>(null);
  const busy = useRef(false); // the request is on its way: a blur or a second Enter does nothing
  const done = useRef(false);
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);
  return (
    <li className="entry-new-row">
      <span className="entry-check-spacer" aria-hidden="true" />
      <Folder className="entry-icon" size={16} strokeWidth={1.5} aria-hidden="true" />
      <div className="entry-new-field">
        <input
          ref={ref}
          aria-label="New folder name"
          aria-invalid={problem ? true : undefined}
          autoComplete="off"
          spellCheck={false}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setProblem(null);
          }}
          onBlur={() => {
            if (busy.current || done.current) return;
            done.current = true;
            onCancel();
          }}
          onKeyDown={(e) => {
            e.stopPropagation(); // the page's keys are not for this field
            if (e.key === "Enter") {
              e.preventDefault();
              if (busy.current) return;
              const name = text.trim();
              if (!name) {
                setProblem("Enter a name.");
                return;
              }
              busy.current = true;
              void onCreate(name).then((refused) => {
                busy.current = false;
                if (refused === null) done.current = true;
                else setProblem(refused);
              });
            } else if (e.key === "Escape") {
              e.preventDefault();
              done.current = true;
              onCancel();
            }
          }}
        />
        {problem && (
          <p className="error" role="alert">
            {problem}
          </p>
        )}
      </div>
    </li>
  );
}

/** A pane's list area: dropping files here moves them into the pane's folder. */
function DropZone({ drop, children }: { drop: DropProps | null; children: ReactNode }) {
  const target = useDropTarget(drop ?? { accept: () => false, onDrop: () => {} });
  return (
    <div className="pane-body" data-testid="pane-drop" {...(drop ? target.props : {})}>
      {children}
    </div>
  );
}

/** The archive by folder, in one pane or two side by side (like two Finder windows),
 * full-text search, Quick Look, Move to… and Mark for deletion. Files are dragged onto
 * a folder (or the other pane) to move them, always through the plan and its confirm.
 * With one pane, the previewed file shows its trays, collections and note beside it. */
export default function Browse() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const ids = useId();
  const newFolder = useNewFolder();
  const setupFolders = useSetupFolders();
  const [menu, setMenu] = useState<{ x: number; y: number; path: string; name: string } | null>(null);

  // Paths: one pane uses ?path= (as before), two use ?left=&right=; each pane's
  // collection filter and view sit beside them (PARAM).
  const leftState: PaneState = {
    path: params.get("left") ?? params.get("path") ?? "",
    collection: idParam(params.get(PARAM.left.collection) ?? params.get(PARAM.one.collection)),
    view: viewParam(params.get(PARAM.left.view) ?? params.get(PARAM.one.view)),
  };
  const panes: Record<PaneId, PaneState> = {
    left: leftState,
    right: params.has("right")
      ? {
          path: params.get("right") ?? "",
          collection: idParam(params.get(PARAM.right.collection)),
          view: viewParam(params.get(PARAM.right.view)),
        }
      : leftState,
  };
  const paths: Record<PaneId, string> = { left: panes.left.path, right: panes.right.path };
  const [split, setSplit] = useState(() => params.has("right") || readSplit());
  const [active, setActive] = useState<PaneId>("left");
  // Files that just left (moved, marked): their row may linger until the folder reloads,
  // but the detail no longer shows them. The next click or step clears it.
  const [gone, setGone] = useState<Set<string>>(NONE);
  // One pane: the list's share of the width, dragged on the splitter (remembered here).
  const listSplit = useSplitWidth(archiveKey(LIST_WIDTH_KEY), LIST_SPLIT);
  const act: PaneId = split ? active : "left";
  const shown: PaneId[] = split ? PANES : ["left"];
  const flatOf = (pane: PaneId) => panes[pane].view === "files";

  const [sorts, setSorts] = useState<Record<PaneId, SortState>>({
    left: { sort: "name", dir: "asc" },
    right: { sort: "name", dir: "asc" },
  });
  const listings: Record<PaneId, ReturnType<typeof useBrowse>> = {
    left: useBrowse(paths.left, !flatOf("left"), panes.left.collection),
    right: useBrowse(paths.right, split && !flatOf("right"), panes.right.collection),
  };
  const flats: Record<PaneId, ReturnType<typeof useBrowseFiles>> = {
    left: useBrowseFiles(paths.left, panes.left.collection, sorts.left.sort, sorts.left.dir, flatOf("left")),
    right: useBrowseFiles(
      paths.right,
      panes.right.collection,
      sorts.right.sort,
      sorts.right.dir,
      split && flatOf("right"),
    ),
  };
  /** The pane's current listing: the folder's entries, or the Files view's rows. */
  const listedOf = (pane: PaneId): DirEntry[] | undefined =>
    flatOf(pane) ? flats[pane].data?.rows : listings[pane].data;
  // Every collection, open and closed, so a closed collection's link still names it.
  const collections = useCollectionsWithMarked(); // the built-ins too, under "Marked"
  // The collection filter's menu button: "Collection", or the chosen one's name.
  const filterName = (id: number) => {
    const c = collections.data?.find((x) => x.id === id);
    if (c?.kind) return BUILTIN_LABEL[c.kind];
    return c ? c.name : collections.isPending ? "…" : `Collection ${id}`;
  };
  /** "All files", the built-ins, then the open collections as a tree (a closed one only
   * while it is the chosen filter, e.g. from a link). */
  const filterEntries = (pane: PaneId): MenuEntry[] => {
    const chosen = panes[pane].collection;
    const all = collections.data ?? [];
    const pick = (id: number | null) => () => setPane(pane, { collection: id });
    const out: MenuEntry[] = [{ label: "All files", checked: chosen === null, onSelect: pick(null) }];
    const builtins = all
      .filter((c) => c.kind != null)
      .sort((a, b) => (a.kind === "starred" ? 0 : 1) - (b.kind === "starred" ? 0 : 1));
    if (builtins.length > 0) {
      out.push("separator");
      for (const c of builtins) out.push({ label: filterName(c.id), checked: chosen === c.id, onSelect: pick(c.id) });
    }
    const ordinary = all.filter((c) => c.kind == null && (c.state === "open" || c.id === chosen));
    const kids = childrenOf(ordinary);
    const walk = (parent: number | null, level: number) => {
      for (const c of kids.get(parent) ?? []) {
        out.push({ label: visible(c.name), checked: chosen === c.id, indent: level, onSelect: pick(c.id) });
        walk(c.id, level + 1);
      }
    };
    if ((kids.get(null) ?? []).length > 0) out.push("separator");
    walk(null, 0);
    return out;
  };

  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"folder" | "everywhere">("everywhere");
  // The search results' column order; null: best match first (the API's order).
  const [searchSort, setSearchSort] = useState<SortState | null>(null);
  const [searchPane, setSearchPane] = useState<PaneId>("left");
  const [reload, setReload] = useState(0);
  const q = query.trim();
  const sp: PaneId = split ? searchPane : "left";
  const inFolder = scope === "folder" && !!paths[sp];
  const folder = inFolder ? paths[sp] : "";
  const search = useSearch(q, folder, reload);

  const viewOf = (pane: PaneId) => {
    if (q && pane === sp) return `search\n${q}\n${folder}\n${searchSort ? `${searchSort.sort} ${searchSort.dir}` : ""}`;
    const { path, collection, view } = panes[pane];
    const sort = view === "files" ? `${sorts[pane].sort} ${sorts[pane].dir}` : "";
    return `browse\n${path}\n${collection ?? ""}\n${view}\n${sort}`;
  };
  const itemsOf = (pane: PaneId): Item[] =>
    q && pane === sp
      ? (() => {
          // SearchHit has no is_dir/is_link (the API does not say); hits are indexed files.
          const hits: Item[] = (search.hits ?? []).map((h) => ({ ...h, is_dir: false, is_link: false }));
          return searchSort ? sortHits(hits, searchSort) : hits;
        })()
      : flatOf(pane)
        ? (flats[pane].data?.rows ?? []).map((e: DirEntry) => ({ ...e })) // in the API's order
        : [...(listings[pane].data ?? [])]
            .sort((a, b) => Number(b.is_dir) - Number(a.is_dir))
            .map((e: DirEntry) => ({ ...e }));

  const items: Record<PaneId, Item[]> = useMemo(
    () => ({ left: itemsOf("left"), right: split ? itemsOf("right") : [] }),
    // itemsOf reads exactly these
    [
      listings.left.data,
      listings.right.data,
      flats.left.data,
      flats.right.data,
      panes.left.view,
      panes.right.view,
      search.hits,
      searchSort,
      q,
      sp,
      split,
    ],
  );

  // Where each listed file lives, for "already there" before a drop.
  const known = useMemo(() => {
    const map = new Map<string, string>();
    for (const it of [...items.left, ...items.right]) map.set(it.drive_id, parentOf(it.path));
    return map;
  }, [items]);
  const allIn = (dragged: string[], dest: string) =>
    dragged.every((id) => known.has(id) && known.get(id) === dest);

  const [selections, setSelections] = useState<Record<PaneId, PaneSelection>>(() => ({
    left: fresh(viewOf("left")),
    right: fresh(viewOf("right")),
  }));
  const selOf = (pane: PaneId): PaneSelection => {
    const s = selections[pane];
    const view = viewOf(pane);
    if (s.view !== view) return fresh(view);
    return { ...s, index: Math.min(s.index, Math.max(0, items[pane].length - 1)) };
  };
  const update = (pane: PaneId, change: Partial<PaneSelection>) =>
    setSelections((all) => {
      const view = viewOf(pane);
      const base = all[pane].view === view ? all[pane] : fresh(view);
      return { ...all, [pane]: { ...base, ...change, view } };
    });

  const sel = selOf(act);
  const list = items[act];
  const index = sel.index;
  const checked = sel.ids;
  const currentItem: Item | undefined = list[index];

  // Back and forward, per pane (the browser's own history keeps working too).
  const [history, setHistory] = useState<Record<PaneId, History>>({
    left: { back: [], forward: [] },
    right: { back: [], forward: [] },
  });
  const urlFor = (next: Record<PaneId, PaneState>, twoPanes: boolean) => {
    const p = new URLSearchParams();
    const extra = (state: PaneState, keys: { collection: string; view: string }) => {
      if (state.collection !== null) p.set(keys.collection, String(state.collection));
      if (state.view === "files") p.set(keys.view, "files");
    };
    if (twoPanes) {
      p.set("left", next.left.path);
      p.set("right", next.right.path);
      extra(next.left, PARAM.left);
      extra(next.right, PARAM.right);
    } else {
      if (next.left.path) p.set("path", next.left.path);
      extra(next.left, PARAM.one);
    }
    return p;
  };
  const withPath = (pane: PaneId, to: string) => ({ ...panes, [pane]: { ...panes[pane], path: to } });
  const hrefFor = (pane: PaneId, to: string) => {
    const s = urlFor(withPath(pane, to), split).toString();
    return s ? `/browse?${s}` : "/browse";
  };
  const go = (pane: PaneId, to: string) => {
    if (to === paths[pane]) return;
    setHistory((h) => ({ ...h, [pane]: { back: [...h[pane].back, paths[pane]], forward: [] } }));
    setParams(urlFor(withPath(pane, to), split));
  };
  const goBack = (pane: PaneId) => {
    const h = history[pane];
    const to = h.back.at(-1);
    if (to === undefined) return;
    setHistory((all) => ({ ...all, [pane]: { back: h.back.slice(0, -1), forward: [paths[pane], ...h.forward] } }));
    setParams(urlFor(withPath(pane, to), split));
  };
  const goForward = (pane: PaneId) => {
    const h = history[pane];
    const to = h.forward[0];
    if (to === undefined) return;
    setHistory((all) => ({ ...all, [pane]: { back: [...h.back, paths[pane]], forward: h.forward.slice(1) } }));
    setParams(urlFor(withPath(pane, to), split));
  };
  /** Change the pane's filter or view (its folder stays). */
  const setPane = (pane: PaneId, change: Partial<Omit<PaneState, "path">>) =>
    setParams(urlFor({ ...panes, [pane]: { ...panes[pane], ...change } }, split));
  const toggleSplit = () => {
    const next = !split;
    setSplit(next);
    writeSplit(next);
    if (!next) setActive("left");
    setNaming(null);
    // the new right pane starts as a copy of the left one
    setParams(urlFor({ left: panes.left, right: next ? panes.left : panes.right }, next));
  };
  const sortBy = (pane: PaneId, sort: FlatSort) =>
    setSorts((all) => ({
      ...all,
      [pane]: {
        sort,
        dir: all[pane].sort === sort ? (all[pane].dir === "asc" ? "desc" : "asc") : firstDir(sort),
      },
    }));
  /** A search column: first click sorts, the second turns it round, the third goes back to best match. */
  const sortSearchBy = (sort: FlatSort) =>
    setSearchSort((cur) =>
      cur?.sort !== sort
        ? { sort, dir: firstDir(sort) }
        : cur.dir === firstDir(sort)
          ? { sort, dir: cur.dir === "asc" ? "desc" : "asc" }
          : null,
    );

  // ?select=<drive id> ("Go to target" on a link): once the folder is listed, that file
  // is the current row and the preview; then the parameter goes (Back keeps the folder).
  const selectId = params.get("select");
  const leftListed = listedOf("left");
  useEffect(() => {
    if (!selectId || leftListed === undefined) return;
    const i = items.left.findIndex((it) => it.drive_id === selectId);
    if (i >= 0) {
      update("left", { ids: [], index: i, anchor: selectId, touched: true });
    }
    const next = new URLSearchParams(params);
    next.delete("select");
    setParams(next, { replace: true });
    // runs for a new target or a new listing only
  }, [selectId, leftListed]);
  const listRef = useRef<Record<PaneId, HTMLUListElement | null>>({ left: null, right: null });
  const focusRow = useRef(false);

  // What Trash takes now: a dry run that answers for other ids is dropped against it.
  const selection = useRef<string[]>([]);

  /** Take files that left (moved or marked) out of every selection and the preview. */
  const forget = (leaving: Set<string>) => {
    setSelections((all) => ({
      left: { ...all.left, ids: all.left.ids.filter((id) => !leaving.has(id)) },
      right: { ...all.right, ids: all.right.ids.filter((id) => !leaving.has(id)) },
    }));
    setGone((old) => new Set([...old, ...leaving]));
    setReload((r) => r + 1);
  };

  const undo = useUndoConfirm(() => setReload((r) => r + 1));
  const marking = useTrash({
    inlineMessage: true,
    onTrashed: (ids) => forget(new Set(ids)),
    onUndone: () => setReload((r) => r + 1),
  });
  // Any move flow's apply (this screen's, or a drop on the sidebar Inbox) and its Undo
  // arrive as one window event: the moved files leave the selections and the preview,
  // and the folder reloads.
  const forgetRef = useRef(forget);
  forgetRef.current = forget;
  useEffect(() => {
    const onMoved = (e: Event) => {
      const { ids } = (e as CustomEvent<FilesMovedDetail>).detail ?? { ids: [] };
      if (ids.length > 0) forgetRef.current(new Set(ids));
      else setReload((r) => r + 1);
    };
    window.addEventListener(FILES_MOVED_EVENT, onMoved);
    return () => window.removeEventListener(FILES_MOVED_EVENT, onMoved);
  }, []);
  const move = useMoveFlow();
  const [moveTo, setMoveTo] = useState<{ ids: string[]; names: string[]; initial: string } | null>(null);
  // From… / For… on the same rows as Move to…
  const [assigning, setAssigning] = useState<{ kind: AssignKind; ids: string[] } | null>(null);
  const locked = marking.busy || move.busy;
  /** At event time, before React re-rendered: a call has started. */
  const running = () => marking.running() || move.inFlight.current || anyMoveRunning();
  useBlockToastActions(
    locked || marking.confirm !== null || move.confirming || moveTo !== null || undo.target !== null || undo.pending,
  );

  // New folder: the name row at the top of a pane's list, for the folder it shows.
  const specialFolders = useStatus().data?.special_folders;
  const createFolder = useCreateFolder();
  const [naming, setNaming] = useState<{ pane: PaneId; parent: string } | null>(null);
  // The folder just made: selected once the listing has it.
  const [madeFolder, setMadeFolder] = useState<{ pane: PaneId; path: string } | null>(null);
  const newFolderWhy = (pane: PaneId) =>
    newFolderRefusal(panes[pane], !!q && pane === sp, specialFolders);
  const startNewFolder = () => {
    if (naming) return;
    const why = newFolderWhy(act);
    if (why) toast({ kind: "info", text: why });
    else if (running()) toast({ kind: "info", text: MOVE_BUSY });
    else setNaming({ pane: act, parent: paths[act] });
  };
  /** Make the folder; the reason it was refused, or null once it is made. */
  const makeFolder = async (target: { pane: PaneId; parent: string }, name: string): Promise<string | null> => {
    try {
      const result = await createFolder.mutateAsync({ parent: target.parent, name });
      if (result.error || result.failed) return visible(result.error ?? "an operation failed");
      const folder = result.done[0]?.dst ?? (target.parent ? `${target.parent}/${name}` : name);
      const made = folder.slice(folder.lastIndexOf("/") + 1);
      setNaming(null);
      setMadeFolder({ pane: target.pane, path: folder });
      toast({
        kind: "info",
        text: `Created folder ${visible(made)}`,
        action: undoAction(() => {
          if (undo.undoing.current || dialogOpen()) return;
          undo.open({ batchId: result.batch_id });
        }),
      });
      return null;
    } catch (e) {
      return visible(e instanceof ApiError && e.detail ? e.detail : errorText(e));
    }
  };
  useEffect(() => {
    if (!madeFolder) return;
    if (parentOf(madeFolder.path) !== paths[madeFolder.pane]) {
      setMadeFolder(null); // the pane went elsewhere before the listing came
      return;
    }
    const i = items[madeFolder.pane].findIndex((it) => it.path === madeFolder.path);
    if (i < 0) return;
    update(madeFolder.pane, { ids: [], index: i, anchor: items[madeFolder.pane][i].drive_id, touched: true });
    setMadeFolder(null);
  });

  /** The files a drag or Move to… takes: the checked files of the pane, else the row
   * the user is on (once they chose one). Folders never move. */
  const filesOf = (pane: PaneId): Item[] => {
    const s = selOf(pane);
    const byId = new Map(items[pane].map((it) => [it.drive_id, it]));
    const picked = s.ids.map((id) => byId.get(id)).filter((it): it is Item => !!it && !it.is_dir);
    if (picked.length > 0) return picked;
    const at = items[pane][s.index];
    return s.touched && at && !at.is_dir ? [at] : [];
  };
  const moveTargets = filesOf(act);
  // A locked file (until it is unlocked) neither moves nor goes to To Delete
  const isBlocked = useIsBlocked();
  const lockedIn = (rows: Item[]) => rows.some((it) => !it.is_dir && isBlocked(it.drive_id, it.marks, it.path));
  const lockedIds = (ids: string[]) =>
    lockedIn(ids.flatMap((id) => [...items.left, ...items.right].filter((it) => it.drive_id === id)));
  // Files in ##. To Delete or ##. Ongoing never move from here.
  const moveBlocked =
    moveTargets.map((it) => sourceRefusal(it.path)).find((r) => r !== null) ??
    (lockedIn(moveTargets) ? LOCKED_REASON : null);
  // Mark for deletion takes the same rows as Move to…, plus checked folders.
  const markTargets: Item[] =
    checked.length > 0 ? list.filter((it) => checked.includes(it.drive_id)) : moveTargets;
  const markIds = markTargets.map((it) => it.drive_id);
  const markBlocked =
    markTargets.map((it) => deletionRefusal(it.path, it.marks)).find((r) => r !== null) ??
    (lockedIn(markTargets) ? LOCKED_REASON : null);
  selection.current = markIds; // stale dry runs are dropped against this
  // The bin is disabled for these; ⌘⌫ says why instead of doing nothing.
  const trashSelection = () => {
    if (markIds.length === 0) return;
    if (markBlocked) toast({ kind: "info", text: markBlocked });
    else if (marking.running()) toast({ kind: "info", text: TRASH_BUSY });
    else if (running()) toast({ kind: "info", text: MOVE_BUSY });
    else marking.start(markIds, { current: () => selection.current, links: markTargets.some((it) => it.is_link) });
  };

  // ★ and ! for the same rows as Move to…: all marked already → unmark; else mark all.
  // (Files that cannot be moved can still be marked.)
  const marks = useBatchMark();
  const starAll = allMarked(moveTargets, "star");
  const importantAll = allMarked(moveTargets, "important");
  const batchMark = (kind: "star" | "important") => marks.run(kind, moveTargets);
  const startRequest = (request: MoveRequest) => {
    if (running()) {
      toast({ kind: "info", text: MOVE_BUSY }); // accept refuses this already; never silent
      return;
    }
    move.start(request);
  };
  const startMove = (dragged: string[], dest: string) => {
    if (lockedIds(dragged)) {
      toast({ kind: "info", text: LOCKED_REASON });
      return;
    }
    startRequest({ ids: dragged, folder: dest });
  };
  const inbox = useInboxFolder();
  const openMoveTo = () => {
    if (running() || moveTargets.length === 0 || moveBlocked) return;
    const other: PaneId = act === "left" ? "right" : "left";
    setMoveTo({
      ids: moveTargets.map((it) => it.drive_id),
      names: moveTargets.map((it) => it.name),
      initial: split && paths[other] !== paths[act] ? paths[other] : "", // where they are is no choice
    });
  };

  const folderDrop = (item: Item): DropProps => ({
    accept: (dragged) =>
      moveRefusal(item.path) ??
      (lockedIds(dragged) ? LOCKED_REASON : null) ??
      (allIn(dragged, item.path) ? `Already in ${visible(item.name)}` : running() ? MOVE_BUSY : true),
    onDrop: (dragged) => startMove(dragged, item.path),
  });
  const paneDrop = (pane: PaneId): DropProps | null =>
    q && pane === sp
      ? null // search results are no folder
      : {
          accept: (dragged) =>
            allIn(dragged, paths[pane])
              ? false
              : (moveRefusal(paths[pane]) ?? (lockedIds(dragged) ? LOCKED_REASON : running() ? MOVE_BUSY : true)),
          onDrop: (dragged) => startMove(dragged, paths[pane]),
        };

  useEffect(() => {
    if (!focusRow.current) return;
    focusRow.current = false;
    listRef.current[act]?.querySelectorAll<HTMLButtonElement>("button.entry")[index]?.focus();
  }, [index, act, sel.view]);

  // The viewer window (if it follows the selection) shows the file the user is on.
  const currentFile = currentItem && !currentItem.is_dir && sel.touched ? currentItem.drive_id : null;
  useEffect(() => {
    if (currentFile) publishSelection(currentFile);
  }, [currentFile]);

  // One pane: the row the cursor is on is the selected file, and the detail shows it
  // (a click, j/k and a move all end up here). Two panes have no detail.
  // (A row nobody has picked yet is not highlighted, and shows no detail.)
  const previewed: Item | null =
    !split && sel.touched && currentItem && !currentItem.is_dir && !gone.has(currentItem.drive_id) ? currentItem : null;
  // a folder on the cursor shows its own panel: its collections and Add to collection
  const folderShown: Item | null =
    !split && sel.touched && currentItem?.is_dir && !gone.has(currentItem.drive_id) ? currentItem : null;
  const open = (pane: PaneId, item: Item | undefined) => {
    if (item?.is_dir) go(pane, item.path);
  };
  const step = (delta: number) => {
    if (list.length === 0) return;
    focusRow.current = listRef.current[act]?.contains(document.activeElement) ?? false;
    setGone(NONE);
    // nothing picked yet: the first step lands on the first (or last) row
    const from = sel.touched ? index : delta > 0 ? -1 : list.length;
    update(act, { index: Math.max(0, Math.min(list.length - 1, from + delta)), touched: true });
  };
  const toggle = (pane: PaneId, id: string) => {
    const s = selOf(pane);
    update(pane, { ids: s.ids.includes(id) ? s.ids.filter((c) => c !== id) : [...s.ids, id] });
  };

  /** Check every file of the pane, or clear the checks when they are all checked.
   * (Folders are opened, not checked.) */
  const selectAll = (pane: PaneId) => {
    const fileIds = items[pane].filter((it) => !it.is_dir).map((it) => it.drive_id);
    if (fileIds.length === 0) return;
    const s = selOf(pane);
    const all = fileIds.every((id) => s.ids.includes(id));
    update(pane, { ids: all ? [] : fileIds });
  };

  /** A click on a row: plain opens it (a folder) or previews it (a file) and selects it
   * alone; ⌘ adds it to the selection or takes it out; ⇧ selects the range from the
   * anchor (the last plainly or ⌘-clicked row). */
  const clickRow = (pane: PaneId, e: MouseEvent, i: number) => {
    setActive(pane);
    setGone(NONE);
    const rows = items[pane];
    const s = selOf(pane);
    const id = rows[i].drive_id;
    if (e.shiftKey) {
      const anchor = rows.findIndex((x) => x.drive_id === s.anchor);
      const from = anchor >= 0 ? anchor : s.index;
      const [lo, hi] = from <= i ? [from, i] : [i, from];
      update(pane, { ids: rows.slice(lo, hi + 1).map((x) => x.drive_id), index: i, touched: true });
      return;
    }
    if (e.metaKey || e.ctrlKey) {
      const base = s.ids.length > 0 ? s.ids : s.touched && rows[s.index] ? [rows[s.index].drive_id] : [];
      const ids = base.includes(id) ? base.filter((x) => x !== id) : [...base, id];
      update(pane, { ids, index: i, anchor: id, touched: true });
      return;
    }
    update(pane, { ids: [], index: i, anchor: id, touched: true });
    open(pane, rows[i]);
  };

  // Quick Look on the active pane's files; it moves the pane's row along.
  const files = useMemo(() => list.filter((it) => !it.is_dir), [list]);
  const qlFiles = useMemo<QLFile[]>(
    () =>
      files.map((it) => ({
        drive_id: it.drive_id,
        name: it.name,
        path: it.path,
        ext: extOf(it.name),
        is_link: it.is_link,
        marks: it.marks,
      })),
    [files],
  );
  const qlIndex = currentItem ? files.findIndex((f) => f.drive_id === currentItem.drive_id) : -1;
  const qlCurrent = useRef<string | null>(null);
  qlCurrent.current = qlIndex >= 0 ? files[qlIndex].drive_id : null;
  const quickLook = useQuickLook(
    qlFiles,
    Math.max(0, qlIndex),
    (i) => {
      const target = files[i];
      if (!target) return;
      update(act, { index: list.indexOf(target), touched: true });
    },
    {
      canOpen: () => qlIndex >= 0 && !running(),
      // the file Quick Look shows (it moves the pane's row along)
      trashRefusal: (file) =>
        deletionRefusal(file.path, file.marks) ?? (isBlocked(file.drive_id, file.marks as readonly Mark[] | undefined, file.path) ? LOCKED_REASON : null),
      trashBusy: marking.busy,
      onTrash: (file, ui) => {
        if (running()) {
          ui.report(marking.running() ? TRASH_BUSY : MOVE_BUSY);
          return;
        }
        marking.start([file.drive_id], {
          current: () => (qlCurrent.current ? [qlCurrent.current] : null),
          links: !!file.is_link,
          onConfirming: ui.close,
          onRefused: ui.report,
          onCancelled: ui.reopen,
        });
      },
    },
  );

  useKeydown((e) => {
    if (e.key === "Escape" && isTyping(e.target)) {
      (e.target as HTMLElement).blur();
      return;
    }
    if ((e.metaKey || e.ctrlKey) && !e.altKey && !isTyping(e.target) && !dialogOpen()) {
      if (isTrashKey(e)) {
        // the focused list (or nothing focused): the pane's selection, as the button
        const target = e.target instanceof Element ? e.target : null;
        if (target && target !== document.body && !target.closest(".browse-pane, .browse-preview")) return;
        trashSelection();
      } else if (!e.shiftKey && e.key.toLowerCase() === "a") {
        const target = e.target instanceof Element ? e.target : null;
        if (target && target !== document.body && !target.closest(".browse-pane, .browse-preview")) return;
        selectAll(act);
      } else if (e.shiftKey && e.key.toLowerCase() === "m") openMoveTo();
      else if (e.shiftKey && e.key.toLowerCase() === "n") startNewFolder();
      else if (!e.shiftKey && e.key === "[") goBack(act);
      else if (!e.shiftKey && e.key === "]") goForward(act);
      else return;
      e.preventDefault();
      return;
    }
    if (!isShortcut(e)) return;
    if (e.key === "j" || e.key === "ArrowDown") step(1);
    else if (e.key === "k" || e.key === "ArrowUp") step(-1);
    else if (e.key === "Enter") {
      const target = e.target as HTMLElement;
      if (target instanceof HTMLInputElement && target.type === "checkbox") target.click(); // toggle only
      else if (target.closest(OWN_ENTER)) return; // a focused button clicks itself
      else {
        update(act, { touched: true });
        open(act, currentItem);
      }
    } else if (e.key === "Backspace") {
      if (e.target instanceof HTMLInputElement && e.target.type === "checkbox") return;
      if (paths[act]) go(act, parentOf(paths[act]));
    } else return;
    e.preventDefault();
  });

  const bodyOf = (pane: PaneId): ReactNode => {
    const rows = items[pane];
    if (q && pane === sp) {
      if (search.error) return <p className="error" role="alert">Search failed. {visible(search.error)}</p>;
      if (search.hits === null) return <p className="placeholder">Searching…</p>;
      if (rows.length === 0) return <p className="placeholder">No matches.</p>;
      return null;
    }
    const listing = flatOf(pane) ? flats[pane] : listings[pane];
    if (listing.isPending) return <p className="placeholder">Loading…</p>;
    if (naming?.pane === pane && !flatOf(pane) && listing.isSuccess) return null; // the name row is the list
    if (listing.isError) {
      return (
        <p className="error" role="alert">
          Could not list this folder. {visible(errorText(listing.error))}
        </p>
      );
    }
    if (rows.length === 0) {
      const filtered = panes[pane].collection !== null;
      if (flatOf(pane)) {
        return (
          <p className="placeholder">{filtered ? "No files of this collection here." : "No files here."}</p>
        );
      }
      if (!filtered && panes[pane].path === "") {
        // a new archive: no folders at all yet
        return (
          <EmptyState
            icon={<Folder size={40} strokeWidth={1.25} />}
            title="This archive has no folders yet."
            hint="Start from a layout (Household, Minimal), or make folders one at a time."
            action={
              <span className="inbox-empty-actions">
                <button type="button" className="primary" onClick={setupFolders.open}>
                  Set up folders…
                </button>
                <button type="button" onClick={() => newFolder.open("")}>
                  <FolderPlus size={14} aria-hidden="true" /> New folder…
                </button>
              </span>
            }
          />
        );
      }
      return (
        <p className="placeholder">{filtered ? "Nothing of this collection here." : "This folder is empty."}</p>
      );
    }
    return null;
  };

  const renderPane = (pane: PaneId) => {
    const rows = items[pane];
    const s = selOf(pane);
    const isSearch = !!q && pane === sp;
    const flat = flatOf(pane) && !isSearch;
    // the Files view and search results have the folder, date and size columns
    const columns = flat || isSearch;
    const body = bodyOf(pane);
    const state = panes[pane];
    const nameRow = naming?.pane === pane && naming.parent === paths[pane] && !flat && !isSearch ? naming : null;
    const total = flat ? (flats[pane].data?.total ?? 0) : 0;
    const sortState = isSearch ? searchSort : sorts[pane];
    // Two panes have no preview panel: the active pane's toolbar has the ★ / ! toggles of
    // the file it is on (one file: a toggle marks one file)
    const onFiles = split && act === pane ? filesOf(pane) : [];
    const marked = onFiles.length === 1 ? onFiles[0] : null;
    const fileRows = rows.filter((it) => !it.is_dir);
    const selectAllBox = (
      <SelectAll
        checked={fileRows.filter((it) => s.ids.includes(it.drive_id)).length}
        total={fileRows.length}
        onChange={() => selectAll(pane)}
      />
    );
    const selectedFiles = () =>
      filesOf(pane)
        .filter((it) => sourceRefusal(it.path) === null)
        .map((it) => it.drive_id);
    return (
      <section
        key={pane}
        className={split && act === pane ? "browse-pane browse-pane-active" : "browse-pane"}
        aria-label={split ? PANE_NAME[pane] : "Browse"}
        onMouseDownCapture={() => setActive(pane)}
        onFocusCapture={() => setActive(pane)}
      >
        <div className="pane-bar">
          <IconButton
            icon={<ChevronLeft />}
            label="Back"
            shortcut={act === pane ? "⌘[" : undefined}
            disabled={history[pane].back.length === 0}
            onClick={() => goBack(pane)}
          />
          <IconButton
            icon={<ChevronRight />}
            label="Forward"
            shortcut={act === pane ? "⌘]" : undefined}
            disabled={history[pane].forward.length === 0}
            onClick={() => goForward(pane)}
          />
          <Breadcrumb
            path={paths[pane]}
            href={(to) => hrefFor(pane, to)}
            go={(to) => go(pane, to)}
          />
          <div className="pane-tools">
            {marked && <MarkToggles key={marked.drive_id} driveId={marked.drive_id} name={marked.name} marks={marked.marks} />}
            <Menu
              label={state.collection === null ? "Collection" : `Collection: ${filterName(state.collection)}`}
              text={state.collection === null ? "Collection" : filterName(state.collection)}
              icon={null}
              align="end"
              className={state.collection === null ? undefined : "menu-active"}
              entries={filterEntries(pane)}
            />
            <Segmented<PaneView>
              ariaLabel="View"
              value={state.view}
              onChange={(view) => setPane(pane, { view })}
              options={[
                { value: "folders", label: "Folders", title: "The folders as they are" },
                { value: "files", label: "Files", title: "Every file below this folder, without the folders" },
              ]}
            />
          </div>
        </div>
        <DropZone drop={paneDrop(pane)}>
          {body === null && !columns && (
            <div className="list-head">
              {selectAllBox}
              <span>Select all</span>
            </div>
          )}
          {columns && body === null && (
            <div className="flat-head" role="group" aria-label="Sort by">
              {selectAllBox}
              <div className="flat-head-cols">
                {SORT_COLUMNS.map((c) => {
                  const on = sortState?.sort === c.sort;
                  const dir = sortState?.dir === "asc" ? "ascending" : "descending";
                  // a search column sorted both ways goes back to best match on the next click
                  const back = isSearch && on && sortState?.dir !== firstDir(c.sort);
                  return (
                    <button
                      key={c.sort}
                      type="button"
                      className={`flat-sort flat-sort-${c.sort}`}
                      aria-pressed={on}
                      aria-label={`Sort by ${c.label.toLowerCase()}${on ? `, ${dir}` : ""}`}
                      data-tip={back ? "Click for best match first" : undefined}
                      onClick={() => (isSearch ? sortSearchBy(c.sort) : sortBy(pane, c.sort))}
                    >
                      {c.label}
                      {on && <span aria-hidden="true">{sortState?.dir === "asc" ? " ↑" : " ↓"}</span>}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          {body ?? (
            <ul
              ref={(el) => {
                listRef.current[pane] = el;
              }}
              className={columns ? "entries entries-flat" : "entries"}
              aria-label={isSearch ? "Search results" : flat ? "Files" : "Folder contents"}
            >
              {nameRow && (
                <NewFolderRow onCreate={(name) => makeFolder(nameRow, name)} onCancel={() => setNaming(null)} />
              )}
              {rows.map((item, i) => {
                const row = {
                  item,
                  current: i === s.index && s.touched,
                  checked: s.ids.includes(item.drive_id),
                  columns,
                  onToggle: () => toggle(pane, item.drive_id),
                  onClick: (e: MouseEvent) => clickRow(pane, e, i),
                };
                if (item.is_dir) {
                  const onContextMenu = (e: MouseEvent) => {
                    e.preventDefault();
                    setMenu({ x: e.clientX, y: e.clientY, path: item.path, name: item.name });
                  };
                  return (
                    <FolderRow
                      key={item.drive_id}
                      {...row}
                      drop={folderDrop(item)}
                      collectable={folderCollectRefusal(item.path, specialFolders) === null}
                      onContextMenu={onContextMenu}
                    />
                  );
                }
                const movable = sourceRefusal(item.path) === null;
                const dragIds = () => {
                  const own = s.ids.includes(item.drive_id) ? selectedFiles() : [];
                  return dragSelection(own, item.drive_id);
                };
                const dragPaths = (ids: string[]) => {
                  const pathOf = new Map(items[pane].map((it) => [it.drive_id, it.path]));
                  return ids.map((d) => pathOf.get(d)).filter((p): p is string => p !== undefined);
                };
                return (
                  <EntryRow key={item.drive_id} {...row} dragIds={movable ? dragIds : null} dragPaths={dragPaths} />
                );
              })}
            </ul>
          )}
          {flat && body === null && total > rows.length && (
            <p className="hint flat-more" role="status">
              {groupDigits(total - rows.length)} more — narrow the folder or search
            </p>
          )}
        </DropZone>
      </section>
    );
  };

  const searchBox = (
    <div className="search">
      {paths[sp] && (
        <Segmented<"folder" | "everywhere">
          ariaLabel="Search scope"
          className="search-scope"
          value={scope}
          onChange={setScope}
          options={[
            { value: "folder", label: "Folder", title: `Search ${visible(paths[sp])} and its subfolders` },
            { value: "everywhere", label: "Archive", title: "Search the whole archive" },
          ]}
        />
      )}
      <label htmlFor={`${ids}-q`} className="visually-hidden">
        Search
      </label>
      <input
        id={`${ids}-q`}
        type="search"
        placeholder={inFolder ? `Search ${visible(paths[sp].split("/").at(-1) ?? "")}` : "Search the archive"}
        title={inFolder ? `Searches ${visible(paths[sp])} and its subfolders` : undefined}
        value={query}
        spellCheck={false}
        onChange={(e) => {
          if (!q && e.target.value.trim()) setSearchPane(act);
          setQuery(e.target.value);
        }}
      />
    </div>
  );

  return (
    <div className={split ? "browse browse-split" : "browse"}>
      <Toolbar
        title="Browse"
        subtitle={checked.length > 0 ? `${checked.length} selected` : undefined}
        actions={
          <>
            <IconButton
              icon={<Columns2 />}
              label="Two panes"
              pressed={split}
              onClick={toggleSplit}
            />
            <IconButton
              icon={<FolderPlus />}
              label="New folder"
              shortcut="⇧⌘N"
              disabled={newFolderWhy(act) !== null || naming !== null || locked}
              disabledReason={newFolderWhy(act) ?? undefined}
              onClick={startNewFolder}
            />
            <IconButton
              icon={<FolderInput />}
              label="Move to…"
              shortcut="⇧⌘M"
              disabled={moveTargets.length === 0 || moveBlocked !== null || locked}
              disabledReason={moveBlocked ?? undefined}
              onClick={openMoveTo}
            />
            <IconButton
              icon={<Building2 />}
              label="From…"
              tip="Say who sent these documents"
              disabled={moveTargets.length === 0 || locked}
              onClick={() => setAssigning({ kind: "sender", ids: moveTargets.map((it) => it.drive_id) })}
            />
            <IconButton
              icon={<User />}
              label="For…"
              tip="Say who these documents are for"
              disabled={moveTargets.length === 0 || locked}
              onClick={() => setAssigning({ kind: "person", ids: moveTargets.map((it) => it.drive_id) })}
            />
            <IconButton
              icon={<StarGlyph size={16} filled={starAll} />}
              label={starAll ? "Remove the star" : "Star"}
              pressed={starAll}
              disabled={moveTargets.length === 0 || marks.busy}
              onClick={() => void batchMark("star")}
            />
            <IconButton
              icon={<ImportantGlyph large />}
              label={importantAll ? "Unmark Important" : "Mark Important"}
              pressed={importantAll}
              disabled={moveTargets.length === 0 || marks.busy}
              onClick={() => void batchMark("important")}
            />
            <TrashButton
              count={markIds.length}
              disabled={markIds.length === 0 || marking.busy}
              disabledReason={markBlocked}
              onClick={trashSelection}
            />
          </>
        }
        search={searchBox}
      />
      {marking.message && (
      <div className="browse-filters">
        {marking.message &&
          (marking.message.kind === "error" ? (
            <p className="error" role="alert">
              {visible(marking.message.text)}
            </p>
          ) : (
            <p className="notice" role="status">
              {marking.message.text}
            </p>
          ))}
      </div>
      )}
      <div
        className="browse-main"
        ref={listSplit.hostRef}
        style={split ? undefined : listSplit.hostStyle}
      >
        {shown.map(renderPane)}
        {!split && (
          <>
            <Splitter split={listSplit} label="Resize the list" />
            <section className="browse-preview" aria-label="Preview">
              {previewed ? (
                <FilePanel
                  file={{
                    ...previewed,
                    marks: [...items.left, ...items.right].find((i) => i.drive_id === previewed.drive_id)?.marks ?? previewed.marks,
                  }}
                  preview={previewOf(previewed)}
                  disabled={locked}
                  boxTool
                  backToInbox={{
                    refusal:
                      inboxRefusal([previewed.path], inbox) ??
                      (isBlocked(previewed.drive_id, previewed.marks, previewed.path) ? LOCKED_REASON : null) ??
                      (locked ? MOVE_BUSY : null),
                    run: () => {
                      if (inbox && !inboxRefusal([previewed.path], inbox)) {
                        startRequest(backToInbox([previewed.drive_id], inbox));
                      }
                    },
                  }}
                />
              ) : folderShown ? (
                <FolderPanel folder={folderShown} refusal={folderCollectRefusal(folderShown.path, specialFolders)} />
              ) : (
                <EmptyState
                  icon={<File size={40} strokeWidth={1.25} />}
                  title="No file selected"
                  hint="Select a file to see its preview and details."
                />
              )}
            </section>
          </>
        )}
      </div>
      <KeyHints hints={KEYS} className="browse-keys" />
      {quickLook.view}
      {move.view}
      {moveTo && (
        <MoveToSheet
          names={moveTo.names}
          initial={moveTo.initial}
          onCancel={() => setMoveTo(null)}
          onChoose={(dest) => {
            const chosen = moveTo;
            setMoveTo(null);
            startMove(chosen.ids, dest);
          }}
        />
      )}
      {assigning && <AssignSheet kind={assigning.kind} driveIds={assigning.ids} onClose={() => setAssigning(null)} />}
      {marking.view}
      {newFolder.view}
      {setupFolders.view}
      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          label={`${visible(menu.name)} actions`}
          entries={[{ label: `New folder inside ${visible(menu.name)}…`, onSelect: () => newFolder.open(menu.path) }]}
          onClose={() => setMenu(null)}
        />
      )}
    </div>
  );
}

