import { ArrowLeftRight, ChevronDown, ChevronLeft, ChevronRight, Columns2, Eye, File, Folder, FolderPlus, HardDrive } from "lucide-react";
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
import { Link, useLocation, useSearchParams } from "react-router-dom";
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
import { WindowedList } from "../components/WindowedList";
import { notConnected } from "../components/FileLaunch";
import type { PreviewFile } from "../components/FilePreview";
import { BUILTIN_LABEL, MarkIcons } from "../components/MarkIcons";
import { MarkToggles } from "../components/MarkToggles";
import { type RestoreTo, type RestoreWhere, restoreEntries, useRestoreFlow } from "../components/Restore";
import {
  anyMoveRunning,
  backToInbox,
  deletionRefusal,
  FILES_MOVED_EVENT,
  folderMoveRequest,
  type FilesMovedDetail,
  inboxRefusal,
  MOVE_BUSY,
  type MoveRequest,
  MoveToSheet,
  sourceRefusal,
  useInboxFolder,
  useMoveFlow,
} from "../components/MoveTo";
import { isTrashKey, TRASH_BUSY, useTrash } from "../components/Trash";
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
import { type BrowseDrag, type DropTarget, dragSelection, readBrowseDrag, setDragFiles, setDragFolder, useDropTarget } from "../dnd";
import { type DropVerdict, folderSourceRefusal, judgeDrop, judgeFolderDrop, placeOf, SEARCH_DROP_REASON } from "../dropModes";
import { useDropToCollection } from "../components/useDropToCollection";
import { dialogOpen, isShortcut, isTyping, OWN_ENTER, useKeydown } from "../keyboard";
import { publishSelection } from "../selection";
import { formatSize, groupDigits, shortDate } from "../format";
import { visible } from "../text";
import { inToDelete, toDeleteReasonFor } from "../toDelete";
import { type KeyHint, KeyHints } from "../components/KeyHints";
import { type AssignKind, AssignSheet } from "../components/zones/FromFor";
import { FilePanel, FolderPanel } from "./FilePanel";
import { FileActionBar, useAskAction } from "../components/FileActionBar";
import { useFilingAI } from "../components/ai/useFilingAI";
import { usePutInTrayEntries } from "./FileActions";
import { SEARCH_DEBOUNCE_MS, useSearch } from "./useSearch";
import { filterToken, positiveTags, readQuery, sameFilter, type SearchFilter, serializeQuery, splitSearch, withFilter } from "../searchFilters";
import { FilterBar, SearchSuggestions, type TagMode } from "../components/TagSearch";
import { type Completion, useSearchCompletions } from "../components/useSearchCompletions";
import { SearchHelp } from "../components/SearchHelp";
import { parentOf } from "../paths";

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
  [[], "drag files onto a folder to move, link or copy them (hold ⌥ for a copy)"],
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
  /** The extra archive folder the entry is in (null or left out: the main folder). */
  folder?: string | null;
  connected?: boolean;
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
/** Folders sort like the folder tree: parents before their children, siblings by name. */
function byFolder(a: string, b: string): number {
  const x = a === "" ? [] : a.split("/");
  const y = b === "" ? [] : b.split("/");
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const c = byText(x[i], y[i]);
    if (c !== 0) return c;
  }
  return x.length - y.length;
}
/** Search hits under their folders; the order inside a folder is the order given. */
type HitGroup = { folder: string; files: Item[] };
function groupHits(hits: Item[]): HitGroup[] {
  const by = new Map<string, Item[]>();
  for (const h of hits) {
    const folder = parentOf(h.path);
    const list = by.get(folder);
    if (list) list.push(h);
    else by.set(folder, [h]);
  }
  return [...by].sort(([a], [b]) => byFolder(a, b)).map(([folder, files]) => ({ folder, files }));
}
// Differs from paths.ts: takes a bare name, so a "/" in the input is not stripped first.
const extOf = (name: string) => (name.includes(".") ? name.slice(name.lastIndexOf(".") + 1).toLowerCase() : null);
const previewOf = (item: Item): PreviewFile => ({
  drive_id: item.drive_id,
  path: item.path,
  ext: extOf(item.name),
  is_link: item.is_link,
  folder: item.folder,
  connected: item.connected,
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

/** One step of the breadcrumb as a drop target: files or a folder dropped on it go
 * into that folder, as on a folder row. */
function Crumb({ drop, children }: { drop: DropProps; children: (props: DropTarget["props"]) => ReactNode }) {
  const target = useDropTarget<BrowseDrag>({ ...drop, read: readBrowseDrag, onRefused: drop.onRefused });
  return <>{children(target.props)}</>;
}

/** The pane's folder as a path of links; each link goes there in this pane only, and
 * takes a drop into that folder (``drop``). */
function Breadcrumb({
  path,
  href,
  go,
  drop,
}: {
  path: string;
  href: (to: string) => string;
  go: (to: string) => void;
  drop: (to: string) => DropProps;
}) {
  const parts = path ? path.split("/") : [];
  const link = (to: string, label: string) => (
    <Crumb drop={drop(to)}>
      {(props) => (
        <Link
          to={href(to)}
          draggable={false}
          title={label}
          onClick={(e) => {
            e.preventDefault();
            go(to);
          }}
          {...props}
        >
          {label}
        </Link>
      )}
    </Crumb>
  );
  const current = (to: string, label: string) => (
    <Crumb drop={drop(to)}>
      {(props) => (
        <span aria-current="page" title={label} {...props}>
          {label}
        </span>
      )}
    </Crumb>
  );
  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      <ol>
        <li>{parts.length === 0 ? current("", "Archive") : link("", "Archive")}</li>
        {parts.map((part, i) => {
          const here = parts.slice(0, i + 1).join("/");
          return <li key={here}>{i === parts.length - 1 ? current(here, visible(part)) : link(here, visible(part))}</li>;
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
  /** True: a drop does something. A string: "not allowed" and why (shown on the target
   * while the drag is over it, and as a toast when dropped there anyway). */
  accept: (drag: BrowseDrag, e: { altKey: boolean }) => boolean | string;
  onDrop: (drag: BrowseDrag, e: { altKey: boolean }) => void;
  onRefused: (reason: string) => void;
};

type RowProps = {
  item: Item;
  current: boolean;
  checked: boolean;
  /** The Files view: the folder, date and size columns. */
  columns?: boolean;
  /** With ``columns``: leave the folder column out (the rows sit under their folder). */
  noFolder?: boolean;
  /** The ids a drag of this row carries; null: the row is not draggable (as files). */
  dragIds: (() => string[]) | null;
  /** A folder row's own drag (to a collection), instead of ``dragIds``. */
  onDragStart?: (e: DragEvent<HTMLLIElement>) => void;
  /** The archive paths of dragged ids (unknown ones leave the drag without paths). */
  dragPaths?: (ids: string[]) => string[];
  /** Rows of ##. Ongoing / ##. Important / ##. To Delete in the drag: it then carries the
   * special type, which only Browse's own folders take. */
  dragSpecial?: (ids: string[]) => boolean;
  /** Why a drag over this row is refused (a folder row), shown on the row itself. */
  refusal?: string | null;
  onToggle: () => void;
  onClick: (e: MouseEvent) => void;
  /** Drop-target props (folder rows only). */
  dropProps?: DropTarget["props"];
  /** Right-click (folder rows only). */
  onContextMenu?: (e: MouseEvent) => void;
  /** A file row: the Quick Look button at its right end, shown on hover. */
  onQuickLook?: () => void;
  /** The row's place in the pane's items: focus finds the row by it. */
  row: number;
  /** An even line of the list: shaded (the list renders only the rows near the view, so
   * ``nth-child`` cannot tell). */
  stripe: boolean;
};

/** One listed entry. Files drag (with the selection), unless their area keeps them. */
function EntryRow({
  item,
  current,
  checked,
  columns = false,
  noFolder = false,
  dragIds,
  dragPaths,
  dragSpecial,
  refusal,
  onDragStart,
  onToggle,
  onClick,
  dropProps,
  onContextMenu,
  onQuickLook,
  row,
  stripe,
}: RowProps) {
  const driveRoot = item.is_dir && item.folder != null && !item.path.includes("/"); // an extra folder's own root
  const Icon = driveRoot ? HardDrive : item.is_dir ? Folder : File;
  const cls = [checked && "checked", item.is_dir && "entry-row-dir", stripe && "stripe"].filter(Boolean).join(" ");
  const main = (
    <>
      <Icon className="entry-icon" size={16} strokeWidth={1.5} aria-hidden="true" />
      {columns ? (
        <FitText mode="name" className="entry-name" text={visible(item.name)} />
      ) : (
        <span className="entry-name">{visible(item.name)}</span>
      )}
      <MarkIcons marks={item.marks} driveId={item.is_dir ? undefined : item.drive_id} path={item.path} />
      {item.connected === false && <span className="entry-offline">Not connected</span>}
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
      data-row={row}
      aria-current={current ? "true" : undefined}
      draggable={dragIds || onDragStart ? true : undefined}
      onDragStart={
        onDragStart ??
        (dragIds
          ? (e) => {
              const ids = dragIds();
              setDragFiles(e, ids, visible(item.name), dragPaths?.(ids), dragSpecial?.(ids) ?? false);
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
            {!noFolder && (
              <FitText mode="path" className="entry-col entry-folder" text={visible(parentOf(item.path)) || "Archive"} />
            )}
            <span className="entry-col entry-date">{item.mtime != null ? shortDate(item.mtime) : ""}</span>
            <span className="entry-col entry-size">{item.size != null ? formatSize(item.size) : ""}</span>
          </>
        ) : (
          main
        )}
        {item.snippet !== undefined && item.snippet !== item.name && <Snippet text={item.snippet} />}
      </button>
      {onQuickLook && !item.is_dir && (
        <IconButton icon={<Eye />} label={`Quick Look ${visible(item.name)}`} tip="Quick Look" shortcut="Space" className="entry-ql" onClick={onQuickLook} />
      )}
      {refusal && (
        <span className="drop-refusal" role="status">
          {refusal}
        </span>
      )}
    </li>
  );
}

/** A folder row: a drop target (files or a folder dropped here move into it). It drags
 * only as a folder, never with the checked files (``collectable``: its area allows that):
 * Browse's folder targets move it, a collection in the sidebar takes it as a member. */
function FolderRow({ drop, collectable, ...row }: Omit<RowProps, "dropProps" | "dragIds"> & { drop: DropProps; collectable: boolean }) {
  const target = useDropTarget<BrowseDrag>({ ...drop, read: readBrowseDrag, onRefused: drop.onRefused });
  const { item } = row;
  return (
    <EntryRow
      {...row}
      dragIds={null}
      onDragStart={collectable ? (e) => setDragFolder(e, item.drive_id, visible(item.name)) : undefined}
      dropProps={target.props}
      refusal={target.refusal}
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

/** A pane's list area: dropping files here puts them in the pane's folder (move, link or
 * copy), or says why not. */
function DropZone({ drop, children }: { drop: DropProps; children: ReactNode }) {
  const target = useDropTarget<BrowseDrag>({ ...drop, read: readBrowseDrag });
  return (
    <div className="pane-body" data-testid="pane-drop" {...target.props}>
      {target.refusal && (
        <div className="pane-refusal" role="status">
          {target.refusal}
        </div>
      )}
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
  const [menu, setMenu] = useState<{ x: number; y: number; path: string; name: string; driveId: string } | null>(null);

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

  // The whole query is in ?q= (the words and the filters, as typed: `kela tag:medical
  // -in:"90. Other People"`), so a link or Back brings the same search. The box holds only
  // the words; a finished filter typed in it moves to the address and shows as a chip.
  // Old links with ?tag= (repeated) still work: those tags join the filters.
  const urlQ = params.get("q");
  const fromUrl = readQuery(urlQ);
  const [query, setQuery] = useState(() => fromUrl.words);
  const location = useLocation();
  const wrote = useRef<string | null>(null); // the words this screen last wrote to the address
  useEffect(() => {
    // a link to this screen with ?q= sets the words (an empty one clears them); the
    // address change this screen made itself on typing does not
    if (urlQ !== null && fromUrl.words !== wrote.current) setQuery(fromUrl.words);
    // only when the address was navigated to
  }, [location.key]);
  const filters: SearchFilter[] = params
    .getAll("tag")
    .map((value) => ({ name: "tag" as const, value, negated: false }))
    .reduce(withFilter, fromUrl.filters);
  const filtersKey = filters.map(filterToken).join("\n");
  // several tags: every one (the default) or at least one; the address keeps only "any"
  const tagMode: TagMode = positiveTags(filters).length > 1 && params.get("tag_mode") === "any" ? "any" : "all";
  const typed = splitSearch(query);
  const [scope, setScope] = useState<"folder" | "everywhere">("everywhere");
  // The search results' column order; null: best match first (the API's order).
  const [searchSort, setSearchSort] = useState<SortState | null>(null);
  const [searchPane, setSearchPane] = useState<PaneId>("left");
  const [reload, setReload] = useState(0);
  const q = typed.rest.trim();
  const searching = q !== "" || filters.length > 0;
  const sp: PaneId = split ? searchPane : "left";
  const inFolder = scope === "folder" && !!paths[sp];
  const folder = inFolder ? paths[sp] : "";
  const search = useSearch(serializeQuery(q, filters), folder, reload, tagMode);
  // Folders: the results under their folders (a folded folder hides its files); Files: flat.
  // Folding is forgotten when the search changes.
  const grouped = searching && panes[sp].view === "folders";
  const searchKey = `${q}\n${filtersKey}\n${tagMode}\n${folder}`;
  const [folded, setFolded] = useState<{ key: string; folders: Set<string> }>({ key: "", folders: new Set() });
  const foldedFolders = folded.key === searchKey ? folded.folders : NONE;
  const searchGroups = useMemo<HitGroup[]>(() => {
    if (!grouped) return [];
    const hits: Item[] = (search.hits ?? []).map((h) => ({ ...h, is_dir: false, is_link: false }));
    return groupHits(searchSort ? sortHits(hits, searchSort) : hits);
  }, [grouped, search.hits, searchSort]);

  const viewOf = (pane: PaneId) => {
    if (searching && pane === sp) return `search\n${q}\n${filtersKey}\n${tagMode}\n${folder}\n${grouped ? "grouped" : "flat"}\n${searchSort ? `${searchSort.sort} ${searchSort.dir}` : ""}`;
    const { path, collection, view } = panes[pane];
    const sort = view === "files" ? `${sorts[pane].sort} ${sorts[pane].dir}` : "";
    return `browse\n${path}\n${collection ?? ""}\n${view}\n${sort}`;
  };
  const itemsOf = (pane: PaneId): Item[] =>
    searching && pane === sp && grouped
      ? searchGroups.filter((g) => !foldedFolders.has(g.folder)).flatMap((g) => g.files)
      : searching && pane === sp
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
      searchGroups,
      foldedFolders,
      q,
      filtersKey,
      sp,
      split,
    ],
  );

  /** Every listed row of either pane, by id: what a drag over a folder can look up. */
  const rowsById = useMemo(() => {
    const map = new Map<string, Item>();
    for (const it of [...items.left, ...items.right]) map.set(it.drive_id, it);
    return map;
  }, [items]);

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
    // the search stays while you move through folders
    const whole = serializeQuery(q, filters);
    if (whole) p.set("q", whole);
    if (tagMode === "any") p.set("tag_mode", "any");
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
  /** A folder header of the grouped results: open that folder in Browse and leave the
   * search (the words and filters go; Back brings the folder you were in). */
  const openFolderFromSearch = (pane: PaneId, to: string) => {
    setHistory((h) => ({ ...h, [pane]: { back: [...h[pane].back, paths[pane]], forward: [] } }));
    const p = urlFor(withPath(pane, to), split);
    p.delete("q");
    p.delete("tag");
    p.delete("tag_mode");
    setQuery("");
    setParams(p);
  };
  const toggleFolded = (folder: string) => {
    const group = searchGroups.find((g) => g.folder === folder);
    const next = new Set(foldedFolders);
    if (next.has(folder)) next.delete(folder);
    else {
      next.add(folder);
      // files that are hidden are no longer selected
      const hidden = new Set(group?.files.map((f) => f.drive_id));
      update(sp, { ids: selOf(sp).ids.filter((id) => !hidden.has(id)) });
    }
    setFolded({ key: searchKey, folders: next });
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
  /** Two panes: the left one goes right and the right one left, each with its folder,
   * filter, view, sort, history, selection and search. */
  const swapPanes = () => {
    if (!split) return;
    const flip = <T,>(all: Record<PaneId, T>): Record<PaneId, T> => ({ left: all.right, right: all.left });
    setNaming(null);
    setHistory(flip);
    setSorts(flip);
    setSelections(flip);
    setActive((a) => (a === "left" ? "right" : "left"));
    setSearchPane((p) => (p === "left" ? "right" : "left"));
    setParams(urlFor(flip(panes), true));
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
      // the row is in view (a long folder): after this render has marked it
      setTimeout(() => listRef.current.left?.querySelector('[aria-current="true"]')?.scrollIntoView?.({ block: "nearest" }), 0);
    } else {
      toast({ kind: "info", text: "That file is no longer in this folder. Showing the folder it was last in." });
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
  const [moveTo, setMoveTo] = useState<{ ids: string[]; names: string[]; initial: string; title?: string; folder?: true } | null>(
    null,
  );
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
    newFolderRefusal(panes[pane], searching && pane === sp, specialFolders);
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
   * the user is on (once they chose one). A folder moves on its own, never with files:
   * dragged, or with Move to… in its panel (``folderToMove``). */
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
  // Files under ##. To Delete are read-only: every action on them is off until they are
  // restored. Restore takes the same rows as Mark for deletion (checked folders too).
  const readOnlyWhy = toDeleteReasonFor([...moveTargets, ...markTargets].map((it) => it.path));
  const restoring = useRestoreFlow();
  const restoreWhy =
    markTargets.length > 0 && !markTargets.every((it) => inToDelete(it.path))
      ? "Restore works on items in To Delete only: deselect the others"
      : null;
  const startRestore = (ids: string[], to: RestoreTo | RestoreWhere) => {
    if (restoring.running()) toast({ kind: "info", text: "Already restoring…" });
    else if (running()) toast({ kind: "info", text: MOVE_BUSY });
    else restoring.start(ids, to);
  };
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
  // The header's file actions: Put in tray (a pull-down of the trays) and Ask AI work on
  // the selected files / the one file the preview shows.
  const trayEntries = usePutInTrayEntries(
    moveTargets.map((it) => it.drive_id),
    moveTargets.length === 1 ? moveTargets[0].name : null,
  );
  const filingAI = useFilingAI();
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
  /** Why this folder cannot move at all (null: it can), as far as this screen knows. */
  const folderMoveWhy = (it: Item): string | null =>
    folderSourceRefusal(it, specialFolders) ?? (it.connected === false && it.folder ? notConnected(it.folder) : null);
  /** Why the folder ``id`` cannot go into ``target`` (null: it can). A folder no pane lists
   * any more is left to the server's preview. */
  const folderDropWhy = (id: string, target: string): string | null => {
    const it = rowsById.get(id);
    if (!it) return null;
    return folderMoveWhy(it) ?? judgeFolderDrop({ folder: it, target, areas: specialFolders });
  };
  /** Move the folder ``id`` (with everything in it) into ``dest``: Move only, through the
   * same preview, confirm and Undo as files. */
  const moveFolder = (id: string, dest: string) => {
    const why = folderDropWhy(id, dest);
    if (why) toast({ kind: "info", text: why });
    else startRequest(folderMoveRequest(id, dest));
  };
  /** Move to… for one folder (one pane: the other pane is no choice to start with). */
  const openFolderMoveTo = (it: Item) => {
    if (running() || folderMoveWhy(it)) return;
    setMoveTo({ ids: [it.drive_id], names: [it.name], title: `Move ${visible(it.name)} to…`, folder: true, initial: "" });
  };
  const inbox = useInboxFolder();
  const openMoveTo = () => {
    if (folderToMove) {
      openFolderMoveTo(folderToMove);
      return;
    }
    if (running() || moveTargets.length === 0 || moveBlocked) return;
    const other: PaneId = act === "left" ? "right" : "left";
    setMoveTo({
      ids: moveTargets.map((it) => it.drive_id),
      names: moveTargets.map((it) => it.name),
      initial: split && paths[other] !== paths[act] ? paths[other] : "", // where they are is no choice
    });
  };

  // -- dropping files on a folder or a pane: Move / Link / Copy, a restore out of To Delete,
  // or adding to a collection (dropModes.ts has the rules)
  const addToCollection = useDropToCollection();
  const status = useStatus().data;
  const collectionRows = collections.data?.filter((c) => c.state === "open" && !c.kind);
  const judge = (drag: Extract<BrowseDrag, { kind: "files" }>, target: string, alt: boolean): DropVerdict => {
    const dragged = drag.ids.flatMap((id) => {
      const it = rowsById.get(id);
      return it && !it.is_dir ? [{ id, path: it.path, locked: isBlocked(id, it.marks, it.path) }] : [];
    });
    return judgeDrop({
      dragged,
      count: drag.ids.length,
      target,
      areas: specialFolders,
      collections: collectionRows,
      canLink: status?.can_link !== false,
      alt,
    });
  };
  const dropOn = (drag: BrowseDrag, target: string, alt: boolean) => {
    if (drag.kind === "folder") {
      moveFolder(drag.id, target); // Option does nothing: a folder is only moved
      return;
    }
    const verdict = judge(drag, target, alt);
    if (verdict.kind === "refused") {
      toast({ kind: "info", text: verdict.reason });
    } else if (verdict.kind === "collection") {
      const row = collectionRows?.find((c) => c.id === verdict.collection.id);
      if (row) addToCollection(row, drag.ids);
    } else if (verdict.kind === "restore") {
      startRestore(drag.ids, { to: "folder", folder: verdict.folder });
    } else {
      startRequest({
        ids: drag.ids,
        folder: target,
        mode: verdict.initial,
        modes: verdict.modes,
        fromRows: verdict.place === "ongoing" || verdict.place === "important" ? verdict.place : undefined,
      });
    }
  };
  const dropTo = (target: string): DropProps => ({
    accept: (drag, e) => {
      if (drag.kind === "folder") return folderDropWhy(drag.id, target) ?? (running() ? MOVE_BUSY : true);
      const verdict = judge(drag, target, e.altKey);
      if (verdict.kind === "refused") return verdict.reason;
      return running() ? MOVE_BUSY : true;
    },
    onDrop: (drag, e) => dropOn(drag, target, e.altKey),
    onRefused: (reason) => toast({ kind: "info", text: reason }),
  });
  const folderDrop = (item: Item): DropProps => dropTo(item.path);
  const paneDrop = (pane: PaneId): DropProps =>
    searching && pane === sp
      ? {
          // search results are no folder
          accept: () => SEARCH_DROP_REASON,
          onDrop: () => {},
          onRefused: (reason) => toast({ kind: "info", text: reason }),
        }
      : dropTo(paths[pane]);

  useEffect(() => {
    if (!focusRow.current) return;
    focusRow.current = false;
    // by the row's place, not the DOM's: a long list renders only the rows near the view
    // (and always the current one)
    listRef.current[act]?.querySelector<HTMLButtonElement>(`li[data-row="${index}"] button.entry`)?.focus();
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
  // Move to… (the header's, ⇧⌘M and the panel's) takes the folder shown when no file is picked
  const folderToMove: Item | null = moveTargets.length === 0 ? folderShown : null;
  const folderMoveBlocked = folderToMove ? folderMoveWhy(folderToMove) : null;
  // Back to inbox for the selected files: why not (the inbox is unknown, they are there already, locked)
  const inboxWhy =
    moveTargets.length === 0
      ? null
      : (inboxRefusal(moveTargets.map((it) => it.path), inbox) ??
        (lockedIn(moveTargets) ? LOCKED_REASON : null) ??
        (locked ? MOVE_BUSY : null));
  // Ask AI works on one file, the one the preview shows (two panes have no details to
  // show its answer in)
  const askBar = useAskAction(
    filingAI,
    previewed && moveTargets.length === 1 && moveTargets[0].drive_id === previewed.drive_id ? previewed : null,
    split ? "Ask AI works on one file: use one pane" : "Select one file to ask AI",
    locked,
  );
  // A root of a folder whose disk is away is not opened: the row says why.
  const [offlineNote, setOfflineNote] = useState<string | null>(null);
  // it is about the folder the pane showed: any way to another one clears it
  useEffect(() => setOfflineNote(null), [paths.left, paths.right]);
  const open = (pane: PaneId, item: Item | undefined) => {
    if (!item?.is_dir) return;
    if (item.connected === false && item.folder != null && !item.path.includes("/")) {
      setOfflineNote(notConnected(item.folder));
      return;
    }
    setOfflineNote(null);
    go(pane, item.path);
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

  // A row's Quick Look button: that row becomes the pane's current one, and Quick Look
  // opens once the render has its pane's files.
  const [lookAt, setLookAt] = useState<string | null>(null);
  const quickLookRow = (pane: PaneId, i: number) => {
    const id = items[pane][i].drive_id;
    setActive(pane);
    setGone(NONE);
    update(pane, { index: i, anchor: id, touched: true });
    setLookAt(id);
  };
  useEffect(() => {
    if (lookAt === null) return;
    setLookAt(null);
    if (qlCurrent.current === lookAt) quickLook.open();
  }, [lookAt]);

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
    if (searching && pane === sp) {
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
    const isSearch = searching && pane === sp;
    const flat = flatOf(pane) && !isSearch;
    // the Files view and search results have the folder, date and size columns
    const columns = flat || isSearch;
    const byFolders = isSearch && grouped;
    const sortColumns = byFolders ? SORT_COLUMNS.filter((c) => c.sort !== "folder") : SORT_COLUMNS;
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
    const checkedIds = new Set(s.ids); // a big folder: no list scan per row
    const checkedFiles = fileRows.filter((it) => checkedIds.has(it.drive_id)).length;
    // What the list shows: the rows, with a header row before each folder's files when
    // grouped. ``i`` is the row's place in ``rows`` (the headers are not rows).
    let next = 0;
    const listed: ({ header: HitGroup; item: null } | { header: null; item: Item; i: number })[] = byFolders
      ? searchGroups.flatMap((g) => [
          { header: g, item: null },
          ...(foldedFolders.has(g.folder) ? [] : g.files).map((f) => ({ header: null, item: f, i: next++ })),
        ])
      : rows.map((item, i) => ({ header: null, item, i }));
    const pin = s.touched ? listed.findIndex((entry) => entry.item !== null && entry.i === s.index) : -1;
    // the new folder's row is the list's first line
    const stripeOf = (pos: number) => (pos + (nameRow ? 1 : 0)) % 2 === 1;
    const selectAllBox = (
      <SelectAll
        checked={checkedFiles}
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
        className={
          (split && act === pane ? "browse-pane browse-pane-active" : "browse-pane") +
          (byFolders ? " browse-pane-grouped" : "")
        }
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
            drop={dropTo}
          />
          <div className="pane-tools">
            {marked && <MarkToggles key={marked.drive_id} driveId={marked.drive_id} name={marked.name} marks={marked.marks} path={marked.path} />}
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
        {isSearch && filters.length > 0 && (
          <FilterBar
            filters={filters}
            mode={tagMode}
            onMode={setTagMode}
            onRemove={(f) => setFilters(filters.filter((x) => !sameFilter(x, f)))}
            onAdd={(name) => addTags([name])}
          />
        )}
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
                {sortColumns.map((c) => {
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
          {offlineNote && act === pane && (
            <p className="hint" role="status">
              {visible(offlineNote)}
            </p>
          )}
          {body ?? (
            <WindowedList
              entries={listed}
              keyOf={(entry) => (entry.header ? `group:${entry.header.folder}` : entry.item.drive_id)}
              pin={pin >= 0 ? pin : null}
              listRef={(el) => {
                listRef.current[pane] = el;
              }}
              className={
                "entries browse-entries" +
                (columns ? " entries-flat" : "") +
                (byFolders ? " entries-grouped" : "") +
                // a checked row may be out of view: every row shows its checkbox then
                (checkedFiles > 0 ? " entries-checking" : "")
              }
              aria-label={isSearch ? "Search results" : flat ? "Files" : "Folder contents"}
              head={
                nameRow && <NewFolderRow onCreate={(name) => makeFolder(nameRow, name)} onCancel={() => setNaming(null)} />
              }
              render={(entry, pos) => {
                if (entry.header) {
                  const g = entry.header;
                  const label = g.folder === "" ? "Archive" : visible(g.folder);
                  const open = !foldedFolders.has(g.folder);
                  return (
                    <li key={`group:${g.folder}`} className={stripeOf(pos) ? "group-head stripe" : "group-head"}>
                      <button
                        type="button"
                        className="group-fold"
                        aria-expanded={open}
                        aria-label={`${open ? "Fold" : "Unfold"} ${label}`}
                        onClick={() => toggleFolded(g.folder)}
                      >
                        {open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
                      </button>
                      <button
                        type="button"
                        className="group-name"
                        data-tip={`Open ${label}`}
                        aria-label={`Open folder ${label}`}
                        onClick={() => openFolderFromSearch(pane, g.folder)}
                      >
                        <Folder size={14} strokeWidth={1.5} aria-hidden="true" /> {label}
                      </button>
                      <span className="group-count">
                        {g.files.length} {g.files.length === 1 ? "match" : "matches"}
                      </span>
                    </li>
                  );
                }
                const { item, i } = entry;
                const row = {
                  item,
                  current: i === s.index && s.touched,
                  checked: checkedIds.has(item.drive_id),
                  columns,
                  noFolder: byFolders,
                  onToggle: () => toggle(pane, item.drive_id),
                  onClick: (e: MouseEvent) => clickRow(pane, e, i),
                  row: i,
                  stripe: stripeOf(pos),
                };
                if (item.is_dir) {
                  const onContextMenu = (e: MouseEvent) => {
                    e.preventDefault();
                    setMenu({ x: e.clientX, y: e.clientY, path: item.path, name: item.name, driveId: item.drive_id });
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
                const dragIds = () => {
                  const own = s.ids.includes(item.drive_id) ? selectedFiles() : [];
                  return dragSelection(own, item.drive_id);
                };
                // rows of the app's own folders drag as "special": only Browse's folders take them
                const dragSpecial = (ids: string[]) =>
                  ids.some((id) => {
                    const it = rowsById.get(id);
                    return !!specialFolders && !!it && placeOf(it.path, specialFolders) !== "plain";
                  });
                const dragPaths = (ids: string[]) => {
                  const pathOf = new Map(items[pane].map((it) => [it.drive_id, it.path]));
                  return ids.map((d) => pathOf.get(d)).filter((p): p is string => p !== undefined);
                };
                return (
                  <EntryRow
                    key={item.drive_id}
                    {...row}
                    dragIds={dragIds}
                    dragPaths={dragPaths}
                    dragSpecial={dragSpecial}
                    onQuickLook={split ? () => quickLookRow(pane, i) : undefined}
                  />
                );
              }}
            />
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

  // Filters live in the address, in ?q= beside the words; a finished `tag:name` typed in
  // the box moves there and shows as a chip.
  const setFilters = (next: SearchFilter[], words = q) => {
    const p = new URLSearchParams(params);
    p.delete("tag");
    const whole = serializeQuery(words, next);
    if (whole) p.set("q", whole);
    else p.delete("q");
    if (positiveTags(next).length < 2) p.delete("tag_mode");
    wrote.current = readQuery(whole).words;
    setParams(p);
  };
  const setTagMode = (mode: TagMode) => {
    const p = new URLSearchParams(params);
    if (mode === "any") p.set("tag_mode", "any");
    else p.delete("tag_mode");
    setParams(p);
  };
  const addFilters = (add: SearchFilter[], words = q) => {
    const next = add.reduce(withFilter, filters);
    if (next.length !== filters.length) setFilters(next, words);
  };
  const addTags = (names: string[]) => addFilters(names.map((value) => ({ name: "tag" as const, value, negated: false })));
  // The words follow into the address as they are typed (replacing the entry, so Back is
  // not filled with letters), and a ?tag= from an old link is moved into ?q=.
  useEffect(() => {
    const want = serializeQuery(q, filters);
    if (want === (urlQ ?? "") && !params.has("tag")) return;
    const timer = setTimeout(() => {
      const p = new URLSearchParams(params);
      p.delete("tag");
      if (want) p.set("q", want);
      else p.delete("q");
      wrote.current = readQuery(want).words;
      setParams(p, { replace: true });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // the address and the box are compared as they stand
  }, [q, filtersKey, urlQ]);
  const inputRef = useRef<HTMLInputElement>(null);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [onSuggestion, setOnSuggestion] = useState(-1); // the arrow keys' place in the list
  const offered = useSearchCompletions(typed, filters, suggestOpen);
  /** A filter typed in the box moves out of it: finished ones at once, the rest with Enter. */
  const typeInBox = (value: string) => {
    const t = splitSearch(value);
    if (t.filters.length > 0) addFilters(t.filters, t.rest.trim());
    setQuery(t.kept);
  };
  const pick = (c: Completion) => {
    if (c.kind === "name") {
      // the word becomes the filter's name; its values are offered next
      setQuery(typed.rest.replace(/\S+$/, "") + c.insert);
      setOnSuggestion(-1);
    } else {
      const base = typed.partial !== null ? typed.rest : typed.rest.replace(/\S+$/, "");
      addFilters([c.filter], base.trim());
      setQuery(base);
      setSuggestOpen(false);
    }
    inputRef.current?.focus();
  };
  /** Enter on a filter being typed finishes it: the suggestion it names, else the first, else as typed. */
  const finishTyped = () => {
    const partial = typed.partial;
    if (!partial) return false;
    const values = offered.filter((c) => c.kind === "value");
    const exact = values.find((c) => c.filter.value.toLowerCase() === partial.value.trim().toLowerCase());
    const chosen = (exact ?? values[0])?.filter ?? (partial.value.trim() ? { name: partial.name, negated: partial.negated, value: partial.value.trim() } : null);
    if (!chosen) return false;
    addFilters([chosen], typed.rest.trim());
    setQuery(typed.rest);
    setSuggestOpen(false);
    return true;
  };
  /** A click on an example in the ? popup: it goes into the box, ready to be edited. */
  const putExample = (example: string) => {
    if (!searching) setSearchPane(act);
    setQuery((query.trim() ? `${query.trimEnd()} ` : "") + example);
    setSuggestOpen(true);
    setOnSuggestion(-1);
    inputRef.current?.focus();
  };

  const searchBox = (
    <div
      className="search"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setSuggestOpen(false);
      }}
    >
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
      <div className="search-field">
        <input
          id={`${ids}-q`}
          ref={inputRef}
          type="search"
          placeholder={inFolder ? `Search ${visible(paths[sp].split("/").at(-1) ?? "")}` : "Search the archive"}
          title={inFolder ? `Searches ${visible(paths[sp])} and its subfolders` : undefined}
          value={query}
          spellCheck={false}
          onChange={(e) => {
            if (!searching && e.target.value.trim()) setSearchPane(act);
            typeInBox(e.target.value);
            setSuggestOpen(true);
            setOnSuggestion(-1);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") setSuggestOpen(false);
            else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && offered.length > 0) {
              e.preventDefault();
              const by = e.key === "ArrowDown" ? 1 : -1;
              setOnSuggestion((n) => Math.max(-1, Math.min(offered.length - 1, n + by)));
            } else if (e.key === "Enter" && onSuggestion >= 0 && offered[onSuggestion]) {
              e.preventDefault();
              pick(offered[onSuggestion]);
            } else if (e.key === "Enter" && finishTyped()) {
              e.preventDefault();
            } else if (e.key === "Enter" && typed.filters.length > 0) {
              // finished filters left in the box (an example from the ? popup)
              e.preventDefault();
              addFilters(typed.filters, typed.rest.trim());
              setQuery(typed.rest);
            }
          }}
        />
        <SearchSuggestions offered={offered} active={onSuggestion} onPick={pick} />
      </div>
      <SearchHelp onUse={putExample} />
    </div>
  );

  return (
    <div className={split ? "browse browse-split" : "browse"}>
      <Toolbar
        title="Browse"
        className="browse-toolbar"
        style={split ? undefined : listSplit.hostStyle}
        subtitle={checked.length > 0 ? `${checked.length} selected` : undefined}
        actions={
          <>
            <IconButton
              icon={<Columns2 />}
              label="Two panes"
              pressed={split}
              onClick={toggleSplit}
            />
            {split && <IconButton icon={<ArrowLeftRight />} label="Swap panes" onClick={swapPanes} />}
            <IconButton
              icon={<FolderPlus />}
              label="New folder"
              shortcut="⇧⌘N"
              disabled={newFolderWhy(act) !== null || naming !== null || locked}
              disabledReason={newFolderWhy(act) ?? undefined}
              onClick={startNewFolder}
            />
          </>
        }
        search={searchBox}
        trailing={
          <FileActionBar
            tray={{
              label: "Put in tray",
              entries: trayEntries,
              disabled: moveTargets.length === 0 || locked,
              reason: readOnlyWhy,
            }}
            backToInbox={{
              run: () => {
                if (inbox && !inboxRefusal(moveTargets.map((it) => it.path), inbox)) {
                  startRequest(
                    backToInbox(
                      moveTargets.map((it) => it.drive_id),
                      inbox,
                      moveTargets.map((it) => it.path),
                    ),
                  );
                }
              },
              disabled: moveTargets.length === 0 || locked,
              reason: inboxWhy,
            }}
            moveTo={{
              run: openMoveTo,
              shortcut: "⇧⌘M",
              disabled: (moveTargets.length === 0 && !folderToMove) || locked,
              reason: moveBlocked ?? folderMoveBlocked,
            }}
            sender={{
              run: () => setAssigning({ kind: "sender", ids: moveTargets.map((it) => it.drive_id) }),
              disabled: moveTargets.length === 0 || locked,
              reason: readOnlyWhy,
            }}
            person={{
              run: () => setAssigning({ kind: "person", ids: moveTargets.map((it) => it.drive_id) }),
              disabled: moveTargets.length === 0 || locked,
              reason: readOnlyWhy,
            }}
            ask={askBar}
            star={{
              on: starAll,
              run: () => void batchMark("star"),
              disabled: moveTargets.length === 0 || marks.busy,
              reason: readOnlyWhy,
            }}
            important={{
              on: importantAll,
              run: () => void batchMark("important"),
              disabled: moveTargets.length === 0 || marks.busy,
              reason: readOnlyWhy,
            }}
            restore={
              markTargets.some((it) => inToDelete(it.path))
                ? { entries: restoreEntries((to) => startRestore(markIds, to), restoreWhy) }
                : undefined
            }
            trash={{
              count: markIds.length,
              run: trashSelection,
              disabled: markIds.length === 0 || marking.busy,
              reason: markBlocked,
            }}
          />
        }
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
                  restore={(to) => startRestore([previewed.drive_id], to)}
                  boxTool
                  headerActions={{ ai: filingAI }}
                />
              ) : folderShown ? (
                <FolderPanel
                  folder={folderShown}
                  refusal={folderCollectRefusal(folderShown.path, specialFolders)}
                  restore={(to) => startRestore([folderShown.drive_id], to)}
                  moveTo={{ run: () => openFolderMoveTo(folderShown), refusal: folderMoveWhy(folderShown) ?? (locked ? MOVE_BUSY : null) }}
                />
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
      {filingAI.sheet}
      {moveTo && (
        <MoveToSheet
          names={moveTo.names}
          title={moveTo.title}
          initial={moveTo.initial}
          onCancel={() => setMoveTo(null)}
          onChoose={(dest) => {
            const chosen = moveTo;
            setMoveTo(null);
            if (chosen.folder) moveFolder(chosen.ids[0], dest);
            else startMove(chosen.ids, dest);
          }}
        />
      )}
      {assigning && <AssignSheet kind={assigning.kind} driveIds={assigning.ids} onClose={() => setAssigning(null)} />}
      {marking.view}
      {restoring.view}
      {newFolder.view}
      {setupFolders.view}
      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          label={`${visible(menu.name)} actions`}
          entries={[
            { label: `New folder inside ${visible(menu.name)}…`, onSelect: () => newFolder.open(menu.path) },
            ...(inToDelete(menu.path)
              ? restoreEntries((to) => startRestore([menu.driveId], to), null)
              : []),
          ]}
          onClose={() => setMenu(null)}
        />
      )}
    </div>
  );
}

