/** A collection's members as a tree of groups (nested to any depth) plus "Ungrouped"
 * (only when there are groups: otherwise the members are a plain list).
 *
 * Each group folds, renames inline (Enter or a double-click on its name), has a
 * summary line and a ⋯ menu (rename, summary, subgroup, move up/down, remove). Each
 * header is a drop target: dropping members on it puts them in that group. Member rows
 * are drag sources, ``data-quicklook`` rows (Space opens Quick Look), and carry the
 * attention tags (open tray items, still in the inbox).
 *
 * A folder member opens in place (the chevron, → and ← on its row): its files and
 * subfolders are listed as in Finder's list view, fetched when opened. A file in there
 * is selected like a member (``onSelectEntry``), though it is not one: the page shows
 * its preview and Open / Show in Finder. The folder's ⋯ menu has "Show in Browse". */
import { ChevronRight, Ellipsis, File, Folder } from "lucide-react";
import { type CSSProperties, type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AIProposal } from "./ai/AIProposal";
import { type Collection, type CollectionChange, type DirEntry, errorText, type Group, type GroupChange, type Member, type MemberAttention, useBrowse } from "../api/client";
import { setDragFiles, useDropTarget } from "../dnd";
import { formatDate, plural } from "../format";
import { visible } from "../text";
import { useFileLaunch } from "./FileLaunch";
import { Menu, type MenuEntry } from "./ui/Menu";
import { Tag, type TagTone } from "./ui/Tag";
import { SaveState } from "./SavedNote";
import { useAutoSave } from "./useAutoSave";
import { MarkIcons } from "./MarkIcons";
import { FitText } from "./FitText";

/** The fold key of "Ungrouped". */
export const UNGROUPED = "ungrouped";
export type FoldKey = number | typeof UNGROUPED;

export const baseName = (path: string) => path.slice(path.lastIndexOf("/") + 1);
const folderOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
export const memberName = (m: Member) => visible(m.path ? baseName(m.path) : m.drive_id);

/** The groups by parent (siblings by position), and the members by group. A member
 * whose group is unknown counts as ungrouped. */
export function treeOf(c: Collection) {
  const known = new Set(c.groups.map((g) => g.id));
  const children = new Map<number | null, Group[]>();
  for (const g of c.groups) {
    const parent = g.parent_id !== null && known.has(g.parent_id) ? g.parent_id : null;
    children.set(parent, [...(children.get(parent) ?? []), g]);
  }
  for (const list of children.values()) list.sort((a, b) => a.position - b.position || a.id - b.id);
  const members = new Map<number | null, Member[]>();
  for (const m of c.members) {
    const g = m.group_id !== null && known.has(m.group_id) ? m.group_id : null;
    members.set(g, [...(members.get(g) ?? []), m]);
  }
  return { children, members };
}

type Tree = ReturnType<typeof treeOf>;

/** Every group in tree order (depth first), with its path ("House › Sale"). */
export function groupPaths(c: Collection): { group: Group; path: string }[] {
  const { children } = treeOf(c);
  const out: { group: Group; path: string }[] = [];
  const walk = (parent: number | null, prefix: string) => {
    for (const g of children.get(parent) ?? []) {
      const path = prefix ? `${prefix} › ${g.name}` : g.name;
      out.push({ group: g, path });
      walk(g.id, path);
    }
  };
  walk(null, "");
  return out;
}

/** The members in the order the tree shows them, leaving out folded groups. */
export function visibleMembers(c: Collection, folded: Set<FoldKey>): Member[] {
  const { children, members } = treeOf(c);
  const out: Member[] = [];
  const walk = (parent: number | null) => {
    for (const g of children.get(parent) ?? []) {
      if (folded.has(g.id)) continue;
      walk(g.id);
      out.push(...(members.get(g.id) ?? []));
    }
  };
  walk(null);
  // without groups there is no Ungrouped header to fold: the plain list is always shown
  if (c.groups.length === 0 || !folded.has(UNGROUPED)) out.push(...(members.get(null) ?? []));
  return out;
}

/** The members of group ``gid`` and of its subgroups, at any depth. */
function membersIn(tree: Tree, gid: number): Member[] {
  const out = [...(tree.members.get(gid) ?? [])];
  for (const g of tree.children.get(gid) ?? []) out.push(...membersIn(tree, g.id));
  return out;
}

/** What the members are: "3 files", "1 folder", "3 files, 1 folder" ("0 files" for none). */
export function memberCount(members: Member[]): string {
  const folders = members.filter((m) => m.is_dir).length;
  const files = members.length - folders;
  if (folders === 0) return plural(files, "file");
  if (files === 0) return plural(folders, "folder");
  return `${plural(files, "file")}, ${plural(folders, "folder")}`;
}

const LEVEL_TONE: Record<string, TagTone> = { overdue: "red", today: "orange", soon: "orange", undated: "grey" };

/** The tags of a member that needs attention: one per open tray item, and "In inbox". */
export function attentionTags(a: MemberAttention | undefined, { long = false } = {}): { key: string; tone: TagTone; text: string }[] {
  if (!a) return [];
  const tags = a.items.map(({ item, level }) => {
    const date = item.date ? ` · ${formatDate(item.date)}` : "";
    const what = long ? `${item.tray_name}: ${item.title}` : item.tray_name;
    return { key: `i${item.id}`, tone: level ? LEVEL_TONE[level] : ("grey" as TagTone), text: visible(`${what}${date}`) };
  });
  if (a.in_inbox) tags.push({ key: "inbox", tone: "blue", text: "In inbox" });
  return tags;
}

/** Changes the tree asks for: ``run`` is guarded (one at a time) and reports the
 * result; ``save`` is for the auto-saved summary lines (they queue themselves). */
export type TreeActions = {
  /** Null when the change did not happen (the page shows why). */
  run: (change: GroupChange, done: string) => Promise<CollectionChange | null>;
  save: (change: GroupChange) => Promise<CollectionChange>;
  /** Ask before removing the group (the parent shows the sheet). */
  remove: (group: Group) => void;
};

type Props = {
  collection: Collection;
  attention: Map<string, MemberAttention>;
  selected: string | null;
  onSelect: (driveId: string) => void;
  folded: Set<FoldKey>;
  onToggle: (key: FoldKey) => void;
  /** Another change is running: drops are refused until it is done. */
  busy: boolean;
  /** The group whose name is being edited (a new group starts there). */
  renaming: number | null;
  setRenaming: (gid: number | null) => void;
  actions: TreeActions;
  /** AI summary proposals by group (summarize-collection): each with Use or Discard. */
  proposals?: GroupProposals;
  /** The file inside a folder member that is selected (its drive id), if any. */
  entry?: string | null;
  onSelectEntry?: (entry: DirEntry) => void;
};

export type GroupProposals = {
  text: (gid: number) => string | undefined;
  use: (group: Group) => void;
  discard: (group: Group) => void;
  busy: boolean;
};

/** The name input of a group being renamed: Enter or leaving it saves, Esc cancels. */
function NameInput({
  name,
  onSave,
  onCancel,
}: {
  name: string;
  /** True once saved (the input then goes); false keeps it open with the typed name. */
  onSave: (name: string) => Promise<boolean>;
  onCancel: () => void;
}) {
  const [text, setText] = useState(name);
  const ref = useRef<HTMLInputElement>(null);
  const settled = useRef(false); // Enter, then the blur it causes: one save
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);
  const finish = async (save: boolean) => {
    if (settled.current) return;
    settled.current = true;
    if (!save) {
      onCancel();
      return;
    }
    if (!(await onSave(text))) {
      settled.current = false; // refused: the name stays to fix or retry
      ref.current?.focus();
    }
  };
  return (
    <input
      ref={ref}
      className="group-name-input"
      aria-label="Group name"
      value={text}
      maxLength={120}
      spellCheck={false}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => void finish(true)}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter") {
          e.preventDefault();
          void finish(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          void finish(false);
        }
      }}
    />
  );
}

/** A group's summary line: its text (a click edits it), or the input while editing,
 * saved on blur or Enter (an empty one removes it). The input holds the raw text, as
 * the note editors do; everything shown outside it goes through ``visible``. */
function SummaryLine({
  group,
  editing,
  setEditing,
  save,
}: {
  group: Group;
  editing: boolean;
  setEditing: (on: boolean) => void;
  save: TreeActions["save"];
}) {
  const auto = useAutoSave(group.summary, async (summary: string) => {
    const r = await save({ op: "update", gid: group.id, summary });
    return r.collection.groups.find((g) => g.id === group.id)?.summary ?? summary;
  });
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) ref.current?.focus();
  }, [editing]);
  if (!editing && !auto.shown) return null;
  return (
    <div className="group-summary">
      {editing ? (
        <input
          ref={ref}
          aria-label={`Summary of ${visible(group.name)}`}
          placeholder="Add a summary…"
          value={auto.shown}
          maxLength={4000}
          onChange={(e) => auto.change(e.target.value)}
          onBlur={() => {
            void auto.commit();
            setEditing(false);
          }}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter" || e.key === "Escape") {
              e.preventDefault();
              ref.current?.blur();
            }
          }}
        />
      ) : (
        <button type="button" className="group-summary-text" title="Click to edit the summary" onClick={() => setEditing(true)}>
          {visible(auto.shown)}
        </button>
      )}
      {auto.status?.kind === "error" && <SaveState status={auto.status} />}
    </div>
  );
}

/** ↑/↓ over the rows as drawn (a folder's contents are rows too: the page's own j/k
 * only know the members) and, on a folder row, → opens and ← closes; ← on a row
 * inside goes to its folder. Returns false for a key it does not handle. */
function rowKeys(e: KeyboardEvent<HTMLElement>, level: number, folder: { open: boolean; setOpen: (open: boolean) => void } | null) {
  if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
  const root = e.currentTarget.closest(".group-tree");
  const rows = Array.from(root?.querySelectorAll<HTMLElement>(".member-row") ?? []);
  const at = rows.indexOf(e.currentTarget);
  const go = (to: number) => {
    const row = rows[to];
    if (!row) return;
    row.focus();
    row.click(); // selects it, as a click does
  };
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    // without an open folder the page's own ↑/↓ do the same
    if (!root?.querySelector(".folder-contents")) return;
    go(at + (e.key === "ArrowDown" ? 1 : -1));
  } else if (e.key === "ArrowRight" && folder) {
    if (!folder.open) folder.setOpen(true);
    else go(at + 1);
  } else if (e.key === "ArrowLeft") {
    if (folder?.open) folder.setOpen(false);
    else {
      let up = at - 1;
      while (up >= 0 && Number(rows[up].dataset.level ?? 0) >= level) up -= 1;
      if (level === 0 || up < 0) return;
      go(up);
    }
  } else return;
  e.preventDefault();
  e.stopPropagation(); // the page's j/k and arrows are not for this one
}

/** The disclosure triangle of a folder row. */
function Chevron({ name, open, onToggle }: { name: string; open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      tabIndex={-1}
      className="member-chevron"
      aria-label={`${open ? "Collapse" : "Expand"} ${name}`}
      aria-expanded={open}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
    >
      <ChevronRight size={12} data-open={open || undefined} aria-hidden="true" />
    </button>
  );
}

/** ⋯ on a folder row: where the folder is, in Browse or in Finder. */
function FolderMenu({ driveId, path, name }: { driveId: string; path: string; name: string }) {
  const navigate = useNavigate();
  const launch = useFileLaunch(driveId);
  const entries: MenuEntry[] = [
    { label: "Show in Browse", onSelect: () => navigate(`/browse?path=${encodeURIComponent(path)}`) },
    { label: "Show in Finder", disabled: launch.busy, onSelect: () => void launch.run("reveal") },
  ];
  return <Menu label={`Actions for ${name}`} icon={<Ellipsis size={16} />} entries={entries} className="member-menu" />;
}

type EntryProps = {
  /** The file of a folder's contents that is selected (its drive id), if any. */
  entry: string | null;
  onSelectEntry: (entry: DirEntry) => void;
};

/** What is inside the folder ``path`` (fetched once it is shown): files and subfolders,
 * the latter opening in turn. */
function FolderContents({ path, level, entry, onSelectEntry }: EntryProps & { path: string; level: number }) {
  const listing = useBrowse(path);
  const pad = { "--lvl": level } as CSSProperties;
  if (listing.isPending) {
    return (
      <li className="member-note busy" style={pad}>
        Loading…
      </li>
    );
  }
  if (listing.isError) {
    return (
      <li className="member-note error" role="alert" style={pad}>
        The folder could not be listed: {visible(errorText(listing.error))}
      </li>
    );
  }
  if (listing.data.length === 0) {
    return (
      <li className="member-note" style={pad}>
        Nothing in this folder.
      </li>
    );
  }
  return (
    <>
      {listing.data.map((e) => (
        <EntryRow key={e.path} e={e} level={level} entry={entry} onSelectEntry={onSelectEntry} />
      ))}
    </>
  );
}

/** One file or subfolder inside a folder member. */
function EntryRow({ e, level, entry, onSelectEntry }: EntryProps & { e: DirEntry; level: number }) {
  const [open, setOpen] = useState(false);
  const name = visible(e.name);
  const Icon = e.is_dir ? Folder : File;
  const selected = !e.is_dir && e.drive_id === entry;
  return (
    <>
      <li
        className="member member-entry"
        data-quicklook={e.is_dir ? undefined : ""}
        aria-current={selected ? "true" : undefined}
        style={{ "--lvl": level } as CSSProperties}
      >
        {e.is_dir && <Chevron name={name} open={open} onToggle={() => setOpen((o) => !o)} />}
        <button
          type="button"
          className="member-row"
          data-level={level}
          onClick={() => (e.is_dir ? setOpen((o) => !o) : onSelectEntry(e))}
          onKeyDown={(ev) => rowKeys(ev, level, e.is_dir ? { open, setOpen } : null)}
        >
          <Icon className="member-icon" size={16} strokeWidth={1.5} aria-hidden="true" />
          <span className="member-text">
            <span className={e.is_dir ? "entry-name member-dir" : "entry-name"}>
              {name}
              <MarkIcons marks={e.marks} />
            </span>
          </span>
        </button>
      </li>
      {e.is_dir && open && <FolderContents path={e.path} level={level + 1} entry={entry} onSelectEntry={onSelectEntry} />}
    </>
  );
}

function MemberRow({
  m,
  attention,
  selected,
  onSelect,
  entry,
  onSelectEntry,
}: EntryProps & {
  m: Member;
  attention: MemberAttention | undefined;
  selected: boolean;
  onSelect: () => void;
}) {
  const name = memberName(m);
  const gone = m.missing || m.quarantined;
  const Icon = m.is_dir ? Folder : File;
  // A folder that is there can be opened in place to see its files.
  const folder = m.is_dir && !!m.path && !gone;
  const [open, setOpen] = useState(false);
  // Only a live file is dragged (to a group or a tray): a folder, a missing file or one
  // in ##. To Delete is regrouped with the side panel's Group select.
  const draggable = !m.is_dir && !gone;
  return (
    <>
      <li
        className={`member${gone ? " member-gone" : ""}${folder ? " member-folder-row" : ""}`}
        data-quicklook
        aria-current={selected ? "true" : undefined}
        style={folder ? ({ "--lvl": 0 } as CSSProperties) : undefined}
        draggable={draggable || undefined}
        onDragStart={
          draggable
            ? (e) => {
                onSelect();
                setDragFiles(e, [m.drive_id], name, m.path === null ? undefined : [m.path]);
              }
            : undefined
        }
      >
        {folder && <Chevron name={name} open={open} onToggle={() => setOpen((o) => !o)} />}
        <button
          type="button"
          className="member-row"
          data-level={0}
          onClick={onSelect}
          onKeyDown={(e) => rowKeys(e, 0, folder ? { open, setOpen } : null)}
        >
          <Icon className="member-icon" size={16} strokeWidth={1.5} aria-hidden="true" />
          <span className="member-text">
            <span className={m.is_dir ? "entry-name member-dir" : "entry-name"}>
              {name}
              <MarkIcons marks={m.marks} />
            </span>
            {m.path && <FitText mode="path" className="member-folder" text={visible(folderOf(m.path) || "(top)")} />}
          </span>
          <span className="member-tags">
            {m.is_dir && <span className="badge">folder</span>}
            {m.missing && <span className="badge badge-error">file missing</span>}
            {!m.missing && m.quarantined && <span className="badge badge-error">in ##. To Delete</span>}
            {attentionTags(attention).map((t) => (
              <Tag key={t.key} tone={t.tone}>
                {t.text}
              </Tag>
            ))}
          </span>
        </button>
        {folder && <FolderMenu driveId={m.drive_id} path={m.path!} name={name} />}
      </li>
      {folder && open && <FolderContents path={m.path!} level={1} entry={entry} onSelectEntry={onSelectEntry} />}
    </>
  );
}

/** A group header or the Ungrouped one: fold toggle, name, count, menu; a drop target. */
function Header({
  label,
  count,
  expanded,
  onToggle,
  accept,
  onDrop,
  onRename,
  editing,
  menu,
}: {
  label: string;
  /** What it holds, said by kind ("1 file, 1 folder"). */
  count: string;
  expanded: boolean;
  onToggle: () => void;
  accept: (ids: string[]) => boolean | string;
  onDrop: (ids: string[]) => void;
  onRename?: () => void;
  editing?: ReactNode;
  menu?: ReactNode;
}) {
  const drop = useDropTarget({ accept, onDrop });
  // One folder icon whatever the fold: swapping the <svg> under the pointer between the
  // two clicks of a double-click would keep the browser from firing dblclick.
  return (
    <div className="group-header" {...drop.props}>
      {editing ? (
        <span className="group-toggle group-toggle-editing">
          <ChevronRight className="group-chevron" size={14} aria-hidden="true" data-open={expanded || undefined} />
          <Folder className="group-icon" size={16} strokeWidth={1.5} aria-hidden="true" />
          {editing}
        </span>
      ) : (
        <button
          type="button"
          className="group-toggle"
          aria-expanded={expanded}
          title={onRename ? "Double-click or press Enter to rename" : undefined}
          onClick={onToggle}
          onDoubleClick={onRename}
          onKeyDown={(e) => {
            if (e.key === "Enter" && onRename) {
              e.preventDefault();
              e.stopPropagation();
              onRename();
            }
          }}
        >
          <ChevronRight className="group-chevron" size={14} aria-hidden="true" data-open={expanded || undefined} />
          <Folder className="group-icon" size={16} strokeWidth={1.5} aria-hidden="true" />
          <span className="group-name">{label}</span>
        </button>
      )}
      <span className="group-count">{count}</span>
      {menu}
    </div>
  );
}

export function GroupTree({
  collection: c,
  attention,
  selected,
  onSelect,
  folded,
  onToggle,
  busy,
  renaming,
  setRenaming,
  actions,
  proposals,
  entry = null,
  onSelectEntry = () => {},
}: Props) {
  const tree = treeOf(c);
  const [editingSummary, setEditingSummary] = useState<number | null>(null);
  const groupName = new Map(c.groups.map((g) => [g.id, g.name]));
  const groupOf = new Map(c.members.map((m) => [m.drive_id, m.group_id !== null && groupName.has(m.group_id) ? m.group_id : null]));

  /** Dropping on group ``gid`` (null: Ungrouped): refused when every file is there already. */
  const accept = (gid: number | null) => (ids: string[]) => {
    if (busy) return "Another change is still running";
    if (ids.every((id) => groupOf.has(id) && groupOf.get(id) === gid)) {
      return `Already in ${gid === null ? "Ungrouped" : visible(groupName.get(gid) ?? "")}`;
    }
    return true;
  };
  const dropInto = (gid: number | null) => (ids: string[]) => {
    const where = gid === null ? "Ungrouped" : (groupName.get(gid) ?? "");
    void actions.run(
      { op: "members", id: c.id, drive_ids: ids, group_id: gid },
      ids.length === 1 ? `Moved to ${where}` : `Moved ${ids.length} files to ${where}`,
    );
  };

  const rows = (list: Member[] | undefined) =>
    (list ?? []).map((m) => (
      <MemberRow
        key={m.drive_id}
        m={m}
        attention={attention.get(m.drive_id)}
        selected={m.drive_id === selected}
        onSelect={() => onSelect(m.drive_id)}
        entry={entry}
        onSelectEntry={onSelectEntry}
      />
    ));

  const renderGroup = (g: Group, siblings: Group[], index: number): ReactNode => {
    const name = visible(g.name);
    const expanded = !folded.has(g.id);
    const files = tree.members.get(g.id) ?? [];
    const subgroups = tree.children.get(g.id) ?? [];
    const proposed = proposals?.text(g.id);
    const rename = async (text: string) => {
      const next = text.trim();
      if (next && next !== g.name) {
        const r = await actions.run({ op: "update", gid: g.id, name: next }, `Renamed the group to ${next}`);
        if (!r) return false; // refused: the input stays, the page says why
      }
      setRenaming(null);
      return true;
    };
    const move = (delta: number) =>
      void actions.run({ op: "update", gid: g.id, position: g.position + delta }, `Moved ${g.name} ${delta < 0 ? "up" : "down"}`);
    const entries: MenuEntry[] = [
      { label: "Rename", onSelect: () => setRenaming(g.id) },
      { label: g.summary ? "Edit summary" : "Add a summary", onSelect: () => setEditingSummary(g.id) },
      {
        label: "New subgroup",
        onSelect: () => void actions.run({ op: "create", id: c.id, name: freeName(subgroups), parent_id: g.id }, `Added a group to ${g.name}`),
      },
      "separator",
      { label: "Move up", disabled: index === 0, onSelect: () => move(-1) },
      { label: "Move down", disabled: index === siblings.length - 1, onSelect: () => move(1) },
      "separator",
      { label: "Remove group…", danger: true, onSelect: () => actions.remove(g) },
    ];
    return (
      <section key={g.id} className="group" aria-label={name}>
        <Header
          label={name}
          count={memberCount(membersIn(tree, g.id))}
          expanded={expanded}
          onToggle={() => onToggle(g.id)}
          accept={accept(g.id)}
          onDrop={dropInto(g.id)}
          onRename={() => setRenaming(g.id)}
          editing={renaming === g.id ? <NameInput name={g.name} onSave={rename} onCancel={() => setRenaming(null)} /> : undefined}
          menu={<Menu label={`Actions for ${name}`} icon={<Ellipsis size={16} />} entries={entries} className="group-menu" />}
        />
        <SummaryLine
          group={g}
          editing={editingSummary === g.id}
          setEditing={(on) => setEditingSummary(on ? g.id : null)}
          save={actions.save}
        />
        {proposed !== undefined && proposals && (
          <div className="group-summary">
            <AIProposal
              label={`AI summary of ${g.name}`}
              text={proposed}
              busy={proposals.busy}
              onUse={() => proposals.use(g)}
              onDiscard={() => proposals.discard(g)}
            />
          </div>
        )}
        {expanded && (
          <div className="group-body">
            {subgroups.map((s, i) => renderGroup(s, subgroups, i))}
            {files.length > 0 && <ul className="group-files">{rows(files)}</ul>}
            {files.length === 0 && subgroups.length === 0 && <p className="group-empty">Drag files here.</p>}
          </div>
        )}
      </section>
    );
  };

  const top = tree.children.get(null) ?? [];
  const ungrouped = tree.members.get(null) ?? [];
  const ungroupedOpen = !folded.has(UNGROUPED);
  return (
    <section className="group-tree" aria-label="Members">
      {c.members.length === 0 && c.groups.length === 0 && (
        <p className="hint">No files yet. Add files from Browse or when filing.</p>
      )}
      {top.map((g, i) => renderGroup(g, top, i))}
      {/* without groups the members are a plain list: "Ungrouped" would say nothing */}
      {c.groups.length === 0 && ungrouped.length > 0 && <ul className="group-files group-plain">{rows(ungrouped)}</ul>}
      {c.groups.length > 0 && (
        <section className="group group-ungrouped" aria-label="Ungrouped">
          <Header
            label="Ungrouped"
            count={memberCount(ungrouped)}
            expanded={ungroupedOpen}
            onToggle={() => onToggle(UNGROUPED)}
            accept={accept(null)}
            onDrop={dropInto(null)}
          />
          {ungroupedOpen && (
            <div className="group-body">
              {ungrouped.length > 0 ? <ul className="group-files">{rows(ungrouped)}</ul> : <p className="group-empty">Nothing ungrouped.</p>}
            </div>
          )}
        </section>
      )}
    </section>
  );
}

/** "New group", or "New group 2", … : a name none of ``siblings`` has (case-folded). */
export function freeName(siblings: Group[], base = "New group"): string {
  const taken = new Set(siblings.map((g) => g.name.normalize("NFC").toLocaleLowerCase()));
  if (!taken.has(base.toLocaleLowerCase())) return base;
  for (let n = 2; ; n++) if (!taken.has(`${base} ${n}`.toLocaleLowerCase())) return `${base} ${n}`;
}
