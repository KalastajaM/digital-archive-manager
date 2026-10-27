import { ChevronRight, FolderPlus } from "lucide-react";
import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { ApiError, errorText, type Status, useCreateFolder, useFolders, useStatus } from "../api/client";
import { visible } from "../text";
import { Sheet } from "./ui/Sheet";

/** At most this many rows are drawn (a short filter on a big archive matches thousands). */
export const MAX_ROWS = 400;

export type FolderTree = { roots: string[]; children: Map<string, string[]>; all: Set<string> };

// Differs from paths.ts: returns null instead of "" when the path has no "/".
const parentOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : null);
const nameOf = (path: string) => path.slice(path.lastIndexOf("/") + 1);
const fold = (s: string) => s.normalize("NFC").toLocaleLowerCase();
const isUnder = (path: string, area: string) => {
  const p = fold(path);
  const a = fold(area.replace(/^\/+|\/+$/g, ""));
  return p === a || p.startsWith(`${a}/`);
};

/** The folder paths as a tree, in the order given (the server sorts them). A path whose
 * parent is not in the list still gets one, so nothing hangs loose. */
export function buildTree(paths: string[]): FolderTree {
  const children = new Map<string, string[]>();
  const roots: string[] = [];
  const seen = new Set<string>();
  const add = (path: string) => {
    if (seen.has(path)) return;
    seen.add(path);
    const parent = parentOf(path);
    if (parent === null) {
      roots.push(path);
      return;
    }
    add(parent);
    const list = children.get(parent);
    if (list) list.push(path);
    else children.set(parent, [path]);
  };
  paths.forEach(add);
  return { roots, children, all: seen };
}

/** ``root``: the special folder itself (it carries the label), not a folder inside it;
 * ``area``: the special folder's path (what a refusal names). */
type Special = { label: string; refused: boolean; root: boolean; area: string };

/** The special folders a flow may refuse on top of the quarantine and ``##. Ongoing``
 * (always refused): the conversions refuse ``##. Important`` (the converter's own
 * folder) and the inbox (filing back into it is pointless). */
export type RefusedRoot = "important" | "inbox";

/** How a special folder (or one inside it) is labelled, and whether files may go there. */
function specialOf(
  path: string,
  folders: Status["special_folders"] | undefined,
  refuse: readonly RefusedRoot[],
): Special | null {
  if (!folders) return null;
  const root = (area: string) => fold(path) === fold(area.replace(/^\/+|\/+$/g, ""));
  if (isUnder(path, folders.quarantine)) {
    return { label: "To Delete", refused: true, root: root(folders.quarantine), area: folders.quarantine };
  }
  if (isUnder(path, folders.ongoing)) {
    return { label: "★ Ongoing, kept by the app", refused: true, root: root(folders.ongoing), area: folders.ongoing };
  }
  if (isUnder(path, folders.important)) {
    const refused = refuse.includes("important");
    if (!refused && !root(folders.important)) return null; // a group folder: an ordinary destination
    return { label: "! Important", refused, root: root(folders.important), area: folders.important };
  }
  if (refuse.includes("inbox") && isUnder(path, folders.inbox)) {
    return { label: "Inbox", refused: true, root: root(folders.inbox), area: folders.inbox };
  }
  return null;
}

type Row = { path: string; level: number; hasChildren: boolean; expanded: boolean };

const NO_REFUSE: readonly RefusedRoot[] = [];

type Props = {
  /** The field's value: pre-selected, its parents open. */
  value: string;
  onChoose: (folder: string) => void;
  onCancel: () => void;
  /** Special folders this flow refuses besides ``##. Ongoing`` and the quarantine. */
  refuse?: readonly RefusedRoot[];
};

/** "Browse folders…" (stars spec §9): the archive's folder tree in a sheet, to walk
 * instead of typing. ↑/↓ move, → opens (then goes in), ← closes (then goes up), Enter
 * chooses, Esc cancels. ``##. Ongoing`` and ``##. To Delete`` are dimmed and cannot be
 * chosen (``refuse`` adds ``##. Important`` and the inbox for the conversions); nothing
 * can be chosen before the special folders are known (``/api/status``). Choosing only
 * sets the field; nothing moves before the usual preview. "New folder" (the footer's
 * left) adds a name field under the selected folder; Enter, or leaving the field with a
 * name in it (Finder does the same), makes the folder on disk right away (its own change
 * in Activity, which can be undone there) and selects it; Choose pressed while naming
 * makes it first and chooses it. It
 * can sit over another sheet: no key press reaches the one underneath. */
export function FolderBrowser({ value, onChoose, onCancel, refuse = NO_REFUSE }: Props) {
  const ids = useId();
  const folders = useFolders();
  const special = useStatus().data?.special_folders;
  const treeRef = useRef<HTMLUListElement>(null);
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<Set<string> | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  // Folders made here (full paths): in the tree at once, before the folder list is reloaded.
  const [made, setMade] = useState<string[]>([]);
  const create = useCreateFolder();
  // A "New folder" on its way (Choose waits for it) and the folder it made last.
  const adding = useRef<Promise<string | null> | null>(null);
  const lastMade = useRef<string | null>(null);
  // What the last "New folder" did, until another row is chosen (a toast would sit under this sheet).
  const [note, setNote] = useState<string | null>(null);
  // The folder a new one is being named under (its name field is the row below it).
  const [naming, setNaming] = useState<string | null>(null);

  const tree = useMemo(() => {
    const paths = [...(folders.data ?? []), ...made];
    // The quarantine is never in /api/folders (not a filing target), and ##. Ongoing
    // only when it holds folders: both are shown, dimmed.
    for (const area of [special?.quarantine, special?.ongoing]) {
      if (area && !paths.some((p) => fold(p) === fold(area))) paths.push(area);
    }
    return buildTree(paths);
  }, [folders.data, made, special?.quarantine, special?.ongoing]);

  // Once the folders are in: open the field's folder (or its nearest existing parent).
  useEffect(() => {
    if (expanded !== null || !folders.data) return;
    const open = new Set<string>();
    const target = value.trim().replace(/^\/+|\/+$/g, "");
    let found: string | null = null;
    for (let p: string | null = target || null; p !== null && found === null; p = parentOf(p)) {
      if (tree.all.has(p)) found = p;
    }
    for (let p = found ? parentOf(found) : null; p !== null; p = parentOf(p)) open.add(p);
    setExpanded(open);
    setActive(found ?? tree.roots[0] ?? null);
  }, [folders.data, tree, value, expanded]);

  const needle = fold(filter.trim());
  const rows = useMemo((): { rows: Row[]; cut: boolean } => {
    const out: Row[] = [];
    let cut = false;
    // With a filter: the matching paths and their ancestors, all open.
    const keep = needle ? new Set<string>() : null;
    if (keep) {
      for (const path of tree.all) {
        if (!fold(path).includes(needle)) continue;
        for (let p: string | null = path; p !== null && !keep.has(p); p = parentOf(p)) keep.add(p);
      }
    }
    const visit = (path: string, level: number) => {
      if (out.length >= MAX_ROWS) {
        cut = true;
        return;
      }
      if (keep && !keep.has(path)) return;
      const kids = tree.children.get(path) ?? [];
      const open = keep ? true : (expanded?.has(path) ?? false);
      // The chevron follows the children that are shown: a row whose children are all
      // filtered or cut away has none (so → does nothing there, and nothing is "open").
      const row: Row = { path, level, hasChildren: kids.length > 0, expanded: open && kids.length > 0 };
      out.push(row);
      if (open) {
        const before = out.length;
        kids.forEach((k) => visit(k, level + 1));
        if (out.length === before) {
          row.hasChildren = false;
          row.expanded = false;
        }
      }
    };
    tree.roots.forEach((r) => visit(r, 1));
    return { rows: out, cut };
  }, [tree, expanded, needle]);

  // The active row stays one that is shown (a filter can hide it).
  const shown = rows.rows;
  const current = shown.find((r) => r.path === active) ?? shown[0] ?? null;
  const index = current ? shown.indexOf(current) : -1;
  const rowId = (i: number) => `${ids}-row-${i}`;

  useEffect(() => {
    if (index >= 0) document.getElementById(rowId(index))?.scrollIntoView({ block: "nearest" });
  }, [index]);
  useEffect(() => {
    treeRef.current?.focus();
  }, []);
  // A new filter selects its first match that can be chosen (not a parent shown for it).
  useEffect(() => {
    if (!needle) return;
    const hit = shown.find((r) => fold(r.path).includes(needle) && !(specialOf(r.path, special, refuse)?.refused ?? false));
    if (hit) setActive(hit.path);
    // Deliberately keyed on the filter only: walking the results keeps the user's row.
  }, [needle]);

  const select = (path: string) => {
    setActive(path);
    setRefusal(null);
    setNote(null);
  };
  const setOpen = (path: string, open: boolean) =>
    setExpanded((prev) => {
      const next = new Set(prev ?? []);
      if (open) next.add(path);
      else next.delete(path);
      return next;
    });
  // Before the special folders are known nothing can be chosen: a refused folder
  // would otherwise slip through.
  const refusedHere = (path: string) => !special || (specialOf(path, special, refuse)?.refused ?? false);
  const choose = (path: string | undefined) => {
    if (!path || !special) return;
    const sp = specialOf(path, special, refuse);
    if (sp?.refused) {
      setRefusal(`Files can't be filed into ${visible(sp.area)}.`);
      return;
    }
    onChoose(path);
  };

  /** ↑ ↓ and Enter work in the filter too; → and ← only on the tree (they move the caret). */
  const onKeys = (e: KeyboardEvent, inTree: boolean) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const move = (to: number) => {
      const row = shown[Math.max(0, Math.min(shown.length - 1, to))];
      if (row) select(row.path);
    };
    if (e.key === "ArrowDown") move(index + 1);
    else if (e.key === "ArrowUp") move(index - 1);
    else if (e.key === "Enter") choose(current?.path);
    else if (inTree && e.key === "Home") move(0);
    else if (inTree && e.key === "End") move(shown.length - 1);
    else if (inTree && e.key === "ArrowRight" && current?.hasChildren) {
      if (!current.expanded) {
        if (!needle) setOpen(current.path, true);
      } else move(index + 1);
    } else if (inTree && e.key === "ArrowLeft" && current) {
      if (current.expanded && !needle) setOpen(current.path, false);
      else {
        const up = parentOf(current.path);
        if (up !== null) select(up);
      }
    } else return;
    e.preventDefault(); // Enter never submits a form underneath; arrows never scroll
  };

  const chosenRefused = current ? refusedHere(current.path) : true;

  const startNew = () => {
    if (!current || chosenRefused) return;
    setFilter(""); // a filter would hide the name field's row
    setOpen(current.path, true);
    setNaming(current.path);
  };
  /** Why ``name`` cannot be a new folder under ``parent`` (null: it can). */
  const newRefusal = (parent: string, name: string): string | null => {
    if (!name) return "Enter a name.";
    if (name.includes("/")) return "A folder name can't contain “/”.";
    if (name === "." || name === "..") return "Choose another name.";
    const clash = (tree.children.get(parent) ?? []).some((p) => fold(nameOf(p)) === fold(name));
    if (clash) return `There is already a folder named ${visible(name)} here.`;
    return refusedHere(`${parent}/${name}`) ? "Files can't be filed into this folder." : null;
  };
  /** Make the folder on disk; the reason it was refused, or null once it is made. */
  const addNew = (parent: string, name: string): Promise<string | null> => {
    const run = makeFolder(parent, name).finally(() => {
      if (adding.current === run) adding.current = null;
    });
    adding.current = run;
    return run;
  };
  const makeFolder = async (parent: string, name: string): Promise<string | null> => {
    try {
      const result = await create.mutateAsync({ parent, name });
      if (result.error || result.failed) return visible(result.error ?? "an operation failed");
      const folder = result.done[0]?.dst ?? `${parent}/${name}`;
      lastMade.current = folder;
      setMade((old) => [...old, folder]);
      setNaming(null);
      setOpen(parent, true);
      select(folder);
      setNote(`Made the folder ${visible(nameOf(folder))}. Undo it from Activity.`);
      treeRef.current?.focus();
      return null;
    } catch (e) {
      return visible(e instanceof ApiError && e.detail ? e.detail : errorText(e));
    }
  };
  return (
    <Sheet
      open
      className="folder-browser"
      title="Choose a folder"
      onClose={onCancel}
      // Keys pressed here are the browser's: the sheet or page underneath never sees them.
      onKeyDown={(e) => e.stopPropagation()}
      footer={
        <>
          <button type="button" className="folder-browser-new" disabled={chosenRefused} onClick={startNew}>
            <FolderPlus size={14} aria-hidden="true" /> New folder
          </button>
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="primary"
            disabled={chosenRefused}
            onClick={() => {
              // Choose while naming: the field's blur has started making the folder; wait
              // for it and choose it (a refused name stays in the field to fix).
              const pending = adding.current;
              if (!pending) return naming === null ? choose(current?.path) : undefined;
              void pending.then((refused) => {
                if (refused === null && lastMade.current) choose(lastMade.current);
              });
            }}
          >
            Choose
          </button>
        </>
      }
    >
      <input
        type="search"
        className="folder-browser-filter"
        aria-label="Filter folders"
        placeholder="Filter folders"
        aria-controls={`${ids}-tree`}
        autoComplete="off"
        spellCheck={false}
        value={filter}
        onChange={(e) => {
          setFilter(e.target.value);
          setRefusal(null);
        }}
        onKeyDown={(e) => onKeys(e, false)}
      />
      {folders.isPending && <p className="busy">Loading folders…</p>}
      {folders.isError && (
        <p className="error" role="alert">
          The folders could not be loaded.
        </p>
      )}
      <ul
        ref={treeRef}
        id={`${ids}-tree`}
        role="tree"
        aria-label="Folders"
        className="folder-tree"
        tabIndex={0}
        aria-activedescendant={index >= 0 ? rowId(index) : undefined}
        onKeyDown={(e) => onKeys(e, true)}
      >
        {shown.map((row, i) => {
          const name = visible(nameOf(row.path));
          const sp = specialOf(row.path, special, refuse);
          const label = sp?.root ? sp.label : null; // once, on the special folder itself
          return [
            <li
              key={row.path}
              id={rowId(i)}
              role="treeitem"
              aria-label={label ? `${name}, ${label}` : name}
              aria-level={row.level}
              aria-selected={i === index}
              aria-expanded={row.hasChildren ? row.expanded : undefined}
              aria-disabled={sp?.refused || undefined}
              className={sp?.refused ? "folder-tree-row folder-tree-dimmed" : "folder-tree-row"}
              style={{ paddingLeft: `calc(6px + ${row.level - 1} * var(--tree-indent))` }}
              onClick={() => select(row.path)}
              onDoubleClick={() => choose(row.path)}
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
                    select(row.path);
                    setOpen(row.path, !row.expanded);
                    treeRef.current?.focus();
                  }}
                >
                  <ChevronRight size={12} data-open={row.expanded || undefined} aria-hidden="true" />
                </button>
              ) : (
                <span className="folder-tree-chevron" aria-hidden="true" />
              )}
              <span className="folder-tree-name">{name}</span>
              {label && <span className="folder-tree-label">{label}</span>}
            </li>,
            naming === row.path && (
              <NewFolderRow
                key="new-folder-row"
                level={row.level + 1}
                refusal={(name) => newRefusal(row.path, name)}
                onAdd={(name) => addNew(row.path, name)}
                onCancel={() => {
                  setNaming(null);
                  treeRef.current?.focus();
                }}
              />
            ),
          ];
        })}
      </ul>
      {needle && shown.length === 0 && folders.data && <p className="hint">No folder matches “{visible(filter.trim())}”.</p>}
      {rows.cut && <p className="hint">Showing the first {MAX_ROWS} folders; type more to narrow it down.</p>}
      <p className="hint folder-browser-status" role="status">
        {refusal ?? note ?? (current ? visible(current.path) : "")}
      </p>
    </Sheet>
  );
}

/** The name field of "New folder": Enter makes the folder, Esc (or leaving the field)
 * cancels; a refused name stays to fix, with the reason under it. */
function NewFolderRow({
  level,
  refusal,
  onAdd,
  onCancel,
}: {
  level: number;
  refusal: (name: string) => string | null;
  /** Makes the folder: the reason it was refused, or null when it is made. */
  onAdd: (name: string) => Promise<string | null>;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const ref = useRef<HTMLInputElement>(null);
  const done = useRef(false); // Enter or Esc, then the blur it causes: once
  const busy = useRef(false); // the request is on its way: a blur or a second Enter does nothing
  useEffect(() => {
    ref.current?.focus();
    ref.current?.scrollIntoView?.({ block: "nearest" });
  }, []);
  /** Make the folder named in the field; a refused name stays, with the reason. */
  const commit = () => {
    if (busy.current) return;
    const name = text.trim();
    const why = refusal(name);
    if (why) {
      setProblem(why);
      return;
    }
    busy.current = true;
    void onAdd(name).then((refused) => {
      busy.current = false;
      if (refused === null) done.current = true;
      else setProblem(refused);
    });
  };
  return (
    <li role="none" className="folder-tree-new" style={{ paddingLeft: `calc(6px + ${level - 1} * var(--tree-indent))` }}>
      <span className="folder-tree-chevron" aria-hidden="true" />
      <input
        ref={ref}
        aria-label="New folder name"
        aria-invalid={problem ? true : undefined}
        placeholder="New folder"
        autoComplete="off"
        spellCheck={false}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setProblem(null);
        }}
        onBlur={() => {
          if (done.current || busy.current) return;
          // Leaving the field keeps a name typed in it, like Finder; an empty field cancels.
          if (text.trim()) return commit();
          done.current = true;
          onCancel();
        }}
        onKeyDown={(e) => {
          e.stopPropagation(); // the tree's arrows and the sheet's Esc are not for this field
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            e.preventDefault(); // the sheet stays; only the field goes
            done.current = true;
            onCancel();
          }
        }}
      />
      {problem && (
        <span className="error folder-tree-new-error" role="alert">
          {problem}
        </span>
      )}
    </li>
  );
}
