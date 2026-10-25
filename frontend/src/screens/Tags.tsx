/** The Tags screen (``/tags``): every tag with its file count, grouped, with the changes
 * that tidy them: create, rename, merge, delete, pin and move into a group. A tag opens
 * its files in Browse. Tags are dam's own data, so each change is applied at once (delete
 * and merge after a confirm that says what happens) and its toast offers Undo. */
import { EllipsisVertical, FolderPlus, Merge, Pin, Plus, Tag as TagIcon } from "lucide-react";
import { type DragEvent, type FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorText,
  type TagGroup,
  type TagInfo,
  type TagMergePlan,
  type TagUndo,
  useAllTags,
  useTagActions,
} from "../api/client";
import { undoAction, useToast } from "../components/Toasts";
import { EmptyState } from "../components/ui/EmptyState";
import { IconButton } from "../components/ui/IconButton";
import { Menu, type MenuEntry } from "../components/ui/Menu";
import { Sheet } from "../components/ui/Sheet";
import { Toolbar } from "../components/ui/Toolbar";
import { plural } from "../format";
import { visible } from "../text";

const TAG_DRAG = "application/x-dam-tag";
const same = (a: string, b: string) => a.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase() === b.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
const byName = (a: TagInfo, b: TagInfo) => a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true });
const browseUrl = (name: string) => `/browse?${new URLSearchParams({ tag: name, q: "" })}`;

type Sheetful =
  | { kind: "create" }
  | { kind: "group" }
  | { kind: "rename-group"; group: TagGroup }
  | { kind: "rename"; tag: TagInfo }
  | { kind: "merge"; sources: string[]; into?: string }
  | { kind: "delete"; tag: TagInfo };

/** A sheet with one name field (a new tag or group, a new name). */
function NameSheet({
  title,
  label,
  initial = "",
  submit,
  onClose,
  clash,
}: {
  title: string;
  label: string;
  initial?: string;
  /** Does the change; throws to show the message. */
  submit: (name: string) => Promise<void>;
  onClose: () => void;
  /** Another tag the name matches: the sheet offers to merge into it instead. */
  clash?: (name: string) => { name: string; merge: () => void } | null;
}) {
  const [name, setName] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const trimmed = name.trim();
  const other = clash?.(trimmed) ?? null;
  const go = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!trimmed || trimmed === initial || other || busy) return;
    setBusy(true);
    setError(null);
    try {
      await submit(trimmed);
      onClose();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  };
  return (
    <Sheet
      open
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          {other ? (
            <button type="button" className="primary" onClick={other.merge}>
              Merge instead
            </button>
          ) : (
            <button type="button" className="primary" disabled={!trimmed || trimmed === initial || busy} onClick={() => void go()}>
              {initial ? "Rename" : "Create"}
            </button>
          )}
        </>
      }
    >
      <form onSubmit={(e) => void go(e)}>
        <label className="field">
          <span>{label}</span>
          <input value={name} onChange={(e) => setName(e.target.value)} spellCheck={false} autoFocus />
        </label>
      </form>
      {other && (
        <p className="notice">
          A tag called {visible(other.name)} already exists. Merge {visible(initial)} into it instead: its files get{" "}
          {visible(other.name)} and {visible(initial)} is removed.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </Sheet>
  );
}

/** Merge ``sources`` into another tag: pick the tag to keep, see what happens, confirm. */
function MergeSheet({
  sources,
  into: first,
  tags,
  preview,
  merge,
  onClose,
}: {
  sources: string[];
  into?: string;
  tags: TagInfo[];
  preview: (sources: string[], into: string) => Promise<TagMergePlan>;
  merge: (sources: string[], into: string) => Promise<void>;
  onClose: () => void;
}) {
  const choices = tags.filter((t) => !sources.includes(t.name)).sort(byName);
  const [into, setInto] = useState(first ?? "");
  const [plan, setPlan] = useState<{ into: string; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!into) return;
    let current = true;
    setError(null);
    preview(sources, into)
      .then((p) => current && setPlan({ into, text: p.message }))
      .catch((e) => current && setError(errorText(e)));
    return () => {
      current = false;
    };
    // the preview follows the chosen tag only
  }, [into]);
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      await merge(sources, into);
      onClose();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };
  const names = sources.map((s) => visible(s)).join(", ");
  return (
    <Sheet
      open
      title={`Merge ${names}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={!into || plan?.into !== into || busy} onClick={() => void go()}>
            Merge
          </button>
        </>
      }
    >
      <label className="field">
        <span>Into</span>
        <select value={into} onChange={(e) => setInto(e.target.value)}>
          <option value="">Choose a tag</option>
          {choices.map((t) => (
            <option key={t.name} value={t.name}>
              {visible(t.name)} ({t.files})
            </option>
          ))}
        </select>
      </label>
      {plan?.into === into && into && <p>{visible(plan.text)}.</p>}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </Sheet>
  );
}

function DeleteSheet({ tag, remove, onClose }: { tag: TagInfo; remove: () => Promise<void>; onClose: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await remove();
      onClose();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };
  return (
    <Sheet
      open
      title={`Delete ${visible(tag.name)}?`}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={busy} onClick={() => void go()}>
            Delete tag
          </button>
        </>
      }
    >
      <p>
        {tag.files === 0
          ? `${visible(tag.name)} is on no files.`
          : `${visible(tag.name)} is removed from ${plural(tag.files, "file")}.`}{" "}
        The files themselves are not touched, and you can undo this right after.
      </p>
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </Sheet>
  );
}

function TagRow({
  tag,
  groups,
  checked,
  onCheck,
  onSheet,
  onPin,
  onMove,
}: {
  tag: TagInfo;
  groups: TagGroup[];
  checked: boolean;
  onCheck: () => void;
  onSheet: (s: Sheetful) => void;
  onPin: () => void;
  onMove: (groupId: number | null) => void;
}) {
  const name = visible(tag.name);
  const entries: MenuEntry[] = [
    { label: "Rename…", onSelect: () => onSheet({ kind: "rename", tag }) },
    { label: "Merge into…", onSelect: () => onSheet({ kind: "merge", sources: [tag.name] }) },
    { label: tag.pinned ? "Unpin from the sidebar" : "Pin to the sidebar", onSelect: onPin },
    "separator",
    ...groups
      .filter((g) => g.id !== tag.group_id)
      .map((g): MenuEntry => ({ label: `Move to ${visible(g.name)}`, onSelect: () => onMove(g.id) })),
    ...(tag.group_id !== null ? [{ label: "Move out of the group", onSelect: () => onMove(null) } as MenuEntry] : []),
    "separator",
    { label: "Delete…", onSelect: () => onSheet({ kind: "delete", tag }) },
  ];
  return (
    <li
      className="tag-row"
      draggable
      onDragStart={(e: DragEvent) => {
        e.dataTransfer.setData(TAG_DRAG, tag.name);
        e.dataTransfer.effectAllowed = "move";
      }}
    >
      <input type="checkbox" aria-label={`Select ${name}`} checked={checked} onChange={onCheck} />
      <Link className="tag-row-name" to={browseUrl(tag.name)} title={`Show the files tagged ${name}`}>
        {name}
      </Link>
      {tag.pinned && <Pin size={12} className="tag-row-pin" aria-label="Pinned" />}
      <span className="tag-row-count">{plural(tag.files, "file")}</span>
      <Menu label={`Actions for ${name}`} icon={<EllipsisVertical />} entries={entries} align="end" />
    </li>
  );
}

export default function Tags() {
  const [filter, setFilter] = useState("");
  const list = useAllTags(filter.trim());
  const actions = useTagActions();
  const toast = useToast();
  const [sheet, setSheet] = useState<Sheetful | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [dropOn, setDropOn] = useState<number | "none" | null>(null);

  const tags = list.data?.tags ?? [];
  const groups = list.data?.groups ?? [];
  const known = useMemo(() => new Set(tags.map((t) => t.name)), [tags]);
  // a tag that is gone (renamed, merged) is no longer ticked
  const ticked = [...checked].filter((n) => known.has(n));

  const revert = async (undo: TagUndo) => {
    try {
      await actions.undo(undo);
      toast({ kind: "info", text: "Undone" });
    } catch (e) {
      toast({ kind: "error", text: `Could not undo: ${errorText(e)}` });
    }
  };
  /** Runs a change; its toast says what happened and offers Undo. */
  const change = async (call: () => Promise<{ message: string; undo: TagUndo | null }>) => {
    try {
      const done = await call();
      const undo = done.undo;
      toast({
        kind: "info",
        text: done.message,
        action: undo ? undoAction(() => void revert(undo)) : undefined,
      });
    } catch (e) {
      toast({ kind: "error", text: errorText(e) });
    }
  };

  const removeGroup = async (g: TagGroup) => {
    try {
      const gone = await actions.deleteGroup(g.id);
      toast({
        kind: "info",
        text: `${gone.message}; its tags stay, ungrouped`,
        action: undoAction(
          () => void actions.restoreGroup(gone.name, gone.members).catch((e) => toast({ kind: "error", text: errorText(e) })),
        ),
      });
    } catch (e) {
      toast({ kind: "error", text: errorText(e) });
    }
  };
  const move = (names: string[], groupId: number | null) => change(() => actions.setGroup(names, groupId));
  const drop = (e: DragEvent, groupId: number | null) => {
    setDropOn(null);
    const name = e.dataTransfer.getData(TAG_DRAG);
    if (!name) return;
    e.preventDefault();
    void move([name], groupId);
  };
  const dropProps = (groupId: number | null) => ({
    onDragOver: (e: DragEvent) => {
      if (!Array.from(e.dataTransfer.types).includes(TAG_DRAG)) return;
      e.preventDefault();
      setDropOn(groupId ?? "none");
    },
    onDragLeave: () => setDropOn(null),
    onDrop: (e: DragEvent) => drop(e, groupId),
    "data-drop": dropOn === (groupId ?? "none") ? "" : undefined,
  });

  const row = (t: TagInfo) => (
    <TagRow
      key={t.name}
      tag={t}
      groups={groups}
      checked={checked.has(t.name)}
      onCheck={() =>
        setChecked((now) => {
          const next = new Set(now);
          if (!next.delete(t.name)) next.add(t.name);
          return next;
        })
      }
      onSheet={setSheet}
      onPin={() => void change(() => actions.pin([t.name], !t.pinned))}
      onMove={(g) => void move([t.name], g)}
    />
  );
  const inGroup = (id: number | null) => tags.filter((t) => t.group_id === id).sort(byName);

  const body = () => {
    if (list.isPending) return <p className="placeholder">Loading…</p>;
    if (list.isError) {
      return (
        <p className="error" role="alert">
          Could not load the tags. {visible(errorText(list.error))}
        </p>
      );
    }
    if (tags.length === 0 && groups.length === 0) {
      return (
        <EmptyState
          icon={<TagIcon size={40} strokeWidth={1.25} />}
          title={filter.trim() ? "No tag matches" : "No tags yet"}
          hint={filter.trim() ? undefined : "Add tags to a file in its panel, or make one here."}
        />
      );
    }
    const loose = inGroup(null);
    return (
      <div className="tags-groups">
        {groups.map((g) => (
          <section key={g.id} className="tag-group" aria-label={`Group ${visible(g.name)}`} {...dropProps(g.id)}>
            <header className="tag-group-head">
              <h3>{visible(g.name)}</h3>
              <Menu
                label={`Actions for the group ${visible(g.name)}`}
                icon={<EllipsisVertical />}
                align="end"
                entries={[
                  { label: "Rename group…", onSelect: () => setSheet({ kind: "rename-group", group: g }) },
                  { label: "Delete group", onSelect: () => void removeGroup(g) },
                ]}
              />
            </header>
            <ul className="tag-list">{inGroup(g.id).map(row)}</ul>
            {inGroup(g.id).length === 0 && <p className="hint">Empty. Drag a tag here, or use its menu.</p>}
          </section>
        ))}
        <section
          className="tag-group"
          aria-label={groups.length > 0 ? "Tags in no group" : "All tags"}
          {...dropProps(null)}
        >
          {groups.length > 0 && (
            <header className="tag-group-head">
              <h3>No group</h3>
            </header>
          )}
          <ul className="tag-list">{loose.map(row)}</ul>
        </section>
      </div>
    );
  };

  const clash = (tag: TagInfo) => (name: string) => {
    const other = tags.find((t) => t.name !== tag.name && same(t.name, name));
    return other ? { name: other.name, merge: () => setSheet({ kind: "merge", sources: [tag.name], into: other.name }) } : null;
  };

  return (
    <div className="tags-screen">
      <Toolbar
        title="Tags"
        subtitle={list.data ? plural(tags.length, "tag") : undefined}
        actions={
          <>
            <IconButton icon={<Plus />} label="New tag" onClick={() => setSheet({ kind: "create" })} />
            <IconButton icon={<FolderPlus />} label="New group" onClick={() => setSheet({ kind: "group" })} />
            <IconButton
              icon={<Merge />}
              label="Merge selected"
              disabled={ticked.length === 0}
              disabledReason="Tick the tags to merge first"
              onClick={() => setSheet({ kind: "merge", sources: ticked })}
            />
          </>
        }
        search={
          <>
            <label htmlFor="tags-filter" className="visually-hidden">
              Filter tags
            </label>
            <input
              id="tags-filter"
              type="search"
              placeholder="Filter tags"
              value={filter}
              spellCheck={false}
              onChange={(e) => setFilter(e.target.value)}
            />
          </>
        }
      />
      {body()}
      {sheet?.kind === "create" && (
        <NameSheet
          title="New tag"
          label="Name"
          onClose={() => setSheet(null)}
          submit={async (name) => {
            const done = await actions.create(name);
            toast({ kind: "info", text: done.message, action: undoAction(() => void revert(done.undo)) });
          }}
        />
      )}
      {sheet?.kind === "group" && (
        <NameSheet
          title="New group"
          label="Name"
          onClose={() => setSheet(null)}
          submit={async (name) => {
            const g = await actions.createGroup(name);
            toast({
              kind: "info",
              text: `Created the group '${g.name}'`,
              action: undoAction(() => void actions.deleteGroup(g.id).catch((e) => toast({ kind: "error", text: errorText(e) }))),
            });
          }}
        />
      )}
      {sheet?.kind === "rename-group" && (
        <NameSheet
          title={`Rename ${visible(sheet.group.name)}`}
          label="Name"
          initial={sheet.group.name}
          onClose={() => setSheet(null)}
          submit={async (name) => {
            const g = sheet.group;
            const done = await actions.renameGroup(g.id, name);
            toast({
              kind: "info",
              text: `Renamed the group to '${done.name}'`,
              action: undoAction(() => void actions.renameGroup(g.id, g.name).catch((e) => toast({ kind: "error", text: errorText(e) }))),
            });
          }}
        />
      )}
      {sheet?.kind === "rename" && (
        <NameSheet
          title={`Rename ${visible(sheet.tag.name)}`}
          label="New name"
          initial={sheet.tag.name}
          clash={clash(sheet.tag)}
          onClose={() => setSheet(null)}
          submit={async (name) => {
            const done = await actions.rename(sheet.tag.name, name);
            toast({ kind: "info", text: done.message, action: undoAction(() => void revert(done.undo)) });
          }}
        />
      )}
      {sheet?.kind === "merge" && (
        <MergeSheet
          sources={sheet.sources}
          into={sheet.into}
          tags={tags}
          preview={actions.previewMerge}
          merge={async (sources, into) => {
            const done = await actions.merge(sources, into);
            const undo = done.undo;
            toast({
              kind: "info",
              text: `Merged: ${done.message}`,
              action: undo ? undoAction(() => void revert(undo)) : undefined,
            });
            setChecked(new Set());
          }}
          onClose={() => setSheet(null)}
        />
      )}
      {sheet?.kind === "delete" && (
        <DeleteSheet
          tag={sheet.tag}
          remove={async () => {
            const done = await actions.remove(sheet.tag.name);
            toast({ kind: "info", text: done.message, action: undoAction(() => void revert(done.undo)) });
          }}
          onClose={() => setSheet(null)}
        />
      )}
    </div>
  );
}
