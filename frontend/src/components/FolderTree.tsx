/** The folder tree beside Browse's panes (the New look): the archive's top folders, each
 * opening onto its subfolders when expanded (listed on demand, from the same listing the
 * panes use, so a folder the panes already read costs nothing). The folders the panes are
 * in are highlighted (and marked L / R with two panes) and kept in view: their parents open
 * by themselves. A click opens the folder in the active pane; every folder takes a drop of
 * files or a folder as a folder row or a breadcrumb step does (the screen judges it).
 *
 * Keyboard (the tree view pattern): ↑ and ↓ move, → opens a folder (or steps into it), ←
 * closes it (or steps out), Home and End go to the first and last, Enter opens the folder
 * in the pane. A right-click (or Shift+F10) on a folder opens the screen's menu for it. */
import { ChevronRight, Folder, HardDrive } from "lucide-react";
import { type KeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { type DirEntry, useBrowse } from "../api/client";
import { type BrowseDrag, readBrowseDrag, useDropTarget } from "../dnd";
import { visible } from "../text";

/** What a drop on a folder of the tree does: the screen's own rules (as a breadcrumb step's). */
export type TreeDrop = {
  accept: (drag: BrowseDrag, e: { altKey: boolean }) => boolean | string;
  onDrop: (drag: BrowseDrag, e: { altKey: boolean }) => void;
  onRefused: (reason: string) => void;
};

/** A folder a pane is in: ``label`` is the pane's mark (L or R; empty with one pane). */
export type TreeMark = { path: string; label: string };

type Shared = {
  marks: TreeMark[];
  open: Set<string>;
  toggle: (path: string, on?: boolean) => void;
  focusPath: string;
  setFocusPath: (path: string) => void;
  onOpen: (entry: DirEntry) => void;
  dropFor: (path: string) => TreeDrop;
  onMenu?: (entry: DirEntry, e: ReactMouseEvent) => void;
};

/** The folders above ``path``: "a/b/c" is under "a" and "a/b". */
export const ancestorsOf = (path: string): string[] => {
  const parts = path.split("/").filter(Boolean);
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
};

function TreeNode({ entry, level, parent, shared }: { entry: DirEntry; level: number; parent: string; shared: Shared }) {
  const { marks, open, toggle, focusPath, setFocusPath, onOpen, dropFor, onMenu } = shared;
  const offline = entry.connected === false;
  const expanded = open.has(entry.path) && !offline;
  const kids = useBrowse(entry.path, expanded);
  const folders = (kids.data ?? []).filter((e) => e.is_dir);
  // a folder with no subfolder has nothing to open; one not listed yet may have
  const expandable = !offline && !(kids.isSuccess && folders.length === 0);
  const here = marks.filter((m) => m.path === entry.path);
  const drop = dropFor(entry.path);
  const target = useDropTarget<BrowseDrag>({ ...drop, read: readBrowseDrag });
  const driveRoot = entry.folder != null && !entry.path.includes("/"); // an extra archive folder's own root
  const Icon = driveRoot ? HardDrive : Folder;
  const name = visible(entry.name);
  const onKeyDown = (e: KeyboardEvent<HTMLLIElement>) => {
    if (e.target !== e.currentTarget || e.metaKey || e.ctrlKey || e.altKey) return;
    const tree = e.currentTarget.closest<HTMLElement>('[role="tree"]');
    const go = (path: string) =>
      Array.from(tree?.querySelectorAll<HTMLElement>("[data-path]") ?? [])
        .find((n) => n.dataset.path === path)
        ?.focus();
    if (e.key === "ArrowRight") {
      if (expandable && !expanded) toggle(entry.path, true);
      else if (expanded && folders[0]) go(folders[0].path);
    } else if (e.key === "ArrowLeft") {
      if (expanded) toggle(entry.path, false);
      else if (parent) go(parent);
    } else if (e.key === "Enter" || e.key === " ") {
      onOpen(entry);
    } else return;
    e.preventDefault();
    e.stopPropagation(); // the page's own keys (the list's cursor) never see these
  };
  return (
    <li
      role="treeitem"
      aria-level={level}
      aria-label={name}
      aria-expanded={expandable ? expanded : undefined}
      aria-selected={here.length > 0}
      data-path={entry.path}
      className="tree-node"
      tabIndex={focusPath === entry.path ? 0 : -1}
      onFocus={(e) => {
        if (e.target === e.currentTarget) setFocusPath(entry.path);
      }}
      onKeyDown={onKeyDown}
      onContextMenu={
        onMenu &&
        ((e) => {
          e.preventDefault();
          e.stopPropagation(); // this folder's menu, not its parent's
          onMenu(entry, e);
        })
      }
    >
      <div
        className={here.length > 0 ? "tree-row tree-current" : "tree-row"}
        style={{ paddingLeft: 8 + (level - 1) * 16 }}
        title={visible(entry.path)}
        onClick={() => {
          if (!offline) toggle(entry.path, true);
          onOpen(entry);
        }}
        {...target.props}
      >
        <span
          className={expandable ? (expanded ? "tree-chevron is-open" : "tree-chevron") : "tree-chevron is-none"}
          aria-hidden="true"
          onClick={(e) => {
            if (!expandable) return;
            e.stopPropagation();
            toggle(entry.path);
          }}
        >
          <ChevronRight size={12} strokeWidth={2} />
        </span>
        <Icon className="tree-icon" size={14} strokeWidth={1.75} aria-hidden="true" />
        <span className="tree-name">{name}</span>
        {offline && <span className="tree-offline">Not connected</span>}
        {here.length > 0 && (
          <span className="tree-pane mono" aria-hidden="true">
            {here.map((m) => m.label).join("")}
          </span>
        )}
      </div>
      {expanded && (
        <ul role="group" className="tree-group">
          {kids.isPending && (
            <li role="none" className="tree-note" style={{ paddingLeft: 8 + level * 16 + 36 }}>
              Loading…
            </li>
          )}
          {kids.isError && (
            <li role="none" className="tree-note" style={{ paddingLeft: 8 + level * 16 + 36 }}>
              Could not list this folder
            </li>
          )}
          {folders.map((f) => (
            <TreeNode key={f.drive_id} entry={f} level={level + 1} parent={entry.path} shared={shared} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function FolderTree({
  marks,
  onOpen,
  dropFor,
  onMenu,
  head,
}: {
  marks: TreeMark[];
  onOpen: (entry: DirEntry) => void;
  dropFor: (path: string) => TreeDrop;
  /** A folder's right-click menu (also Shift+F10 on the focused folder): the screen's. */
  onMenu?: (entry: DirEntry, e: ReactMouseEvent) => void;
  /** Shown above the tree (Browse's Folders | Collections | Tags switch). */
  head?: ReactNode;
}) {
  const roots = useBrowse("");
  const [open, setOpen] = useState<Set<string>>(() => new Set(marks.flatMap((m) => ancestorsOf(m.path))));
  const [focused, setFocused] = useState<string | null>(null);
  const tree = useRef<HTMLUListElement>(null);
  // the folders the panes are in stay in view: their parents open (a folder you opened and
  // then closed again stays closed until a pane moves)
  const where = marks.map((m) => m.path).join("\n");
  useEffect(() => {
    const parents = marks.flatMap((m) => ancestorsOf(m.path));
    setOpen((old) => (parents.every((p) => old.has(p)) ? old : new Set([...old, ...parents])));
    // the marks are this render's; ``where`` says when a pane moved
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [where]);
  const toggle = (path: string, on?: boolean) =>
    setOpen((old) => {
      const next = new Set(old);
      if (on ?? !old.has(path)) next.add(path);
      else next.delete(path);
      return next;
    });
  const folders = (roots.data ?? []).filter((e) => e.is_dir);
  const focusPath = focused ?? marks.find((m) => m.path !== "")?.path ?? folders[0]?.path ?? "";
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
  const shared: Shared = { marks, open, toggle, focusPath, setFocusPath: setFocused, onOpen, dropFor, onMenu };
  return (
    <nav className="tree" aria-label="Folders">
      {head}
      {roots.isPending ? (
        <p className="tree-note">Loading…</p>
      ) : roots.isError ? (
        <p className="tree-note">Could not list the folders</p>
      ) : folders.length === 0 ? (
        <p className="tree-note">No folders yet</p>
      ) : (
        <ul role="tree" aria-label="Folder tree" className="tree-list" ref={tree} onKeyDown={onKeyDown}>
          {folders.map((f) => (
            <TreeNode key={f.drive_id} entry={f} level={1} parent="" shared={shared} />
          ))}
        </ul>
      )}
    </nav>
  );
}
