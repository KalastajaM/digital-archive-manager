/** The Tags screen (``/tags``): every tag with its file count, grouped, with the changes
 * that tidy them: create, rename, merge, delete, pin and move into a group. A tag opens
 * its files in Browse. Tags are dam's own data, so each change is applied at once (delete
 * and merge after a confirm that says what happens) and its toast offers Undo. */
import { EllipsisVertical, FolderPlus, Merge, Pin, Plus, Tag as TagIcon } from "lucide-react";
import { type DragEvent, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { errorText, type TagInfo, useAllTags } from "../api/client";
import { useTagManager } from "../components/useTagManager";
import { EmptyState } from "../components/ui/EmptyState";
import { IconButton } from "../components/ui/IconButton";
import { Menu, type MenuEntry } from "../components/ui/Menu";
import { Toolbar } from "../components/ui/Toolbar";
import { plural } from "../format";
import { tagFilter } from "../searchFilters";
import { visible } from "../text";

const TAG_DRAG = "application/x-dam-tag";
const byName = (a: TagInfo, b: TagInfo) => a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true });
const browseUrl = (name: string) => `/browse?${new URLSearchParams({ q: tagFilter(name) })}`;

function TagRow({
  tag,
  checked,
  onCheck,
  entries,
}: {
  tag: TagInfo;
  checked: boolean;
  onCheck: () => void;
  /** Its menu (Rename, Merge into, Pin, the groups, Delete): ``useTagManager().menuFor``. */
  entries: MenuEntry[];
}) {
  const name = visible(tag.name);
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
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [dropOn, setDropOn] = useState<number | "none" | null>(null);

  const tags = useMemo(() => list.data?.tags ?? [], [list.data]);
  const manager = useTagManager(tags, () => setChecked(new Set()));
  const groups = list.data?.groups ?? [];
  const known = useMemo(() => new Set(tags.map((t) => t.name)), [tags]);
  // a tag that is gone (renamed, merged) is no longer ticked
  const ticked = [...checked].filter((n) => known.has(n));

  const drop = (e: DragEvent, groupId: number | null) => {
    setDropOn(null);
    const name = e.dataTransfer.getData(TAG_DRAG);
    if (!name) return;
    e.preventDefault();
    void manager.move([name], groupId);
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
      checked={checked.has(t.name)}
      onCheck={() =>
        setChecked((now) => {
          const next = new Set(now);
          if (!next.delete(t.name)) next.add(t.name);
          return next;
        })
      }
      entries={manager.menuFor(t, groups)}
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
                entries={manager.groupMenu(g)}
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


  return (
    <div className="tags-screen">
      <Toolbar
        title="Tags"
        subtitle={list.data ? plural(tags.length, "tag") : undefined}
        actions={
          <>
            <IconButton icon={<Plus />} label="New tag" onClick={() => manager.open({ kind: "create" })} />
            <IconButton icon={<FolderPlus />} label="New group" onClick={() => manager.open({ kind: "group" })} />
            <IconButton
              icon={<Merge />}
              label="Merge selected"
              disabled={ticked.length === 0}
              disabledReason="Tick the tags to merge first"
              onClick={() => manager.open({ kind: "merge", sources: ticked })}
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
      {manager.view}
    </div>
  );
}
