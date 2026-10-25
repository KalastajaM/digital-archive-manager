import { useId, useState } from "react";
import { errorText, type TagInfo, useAllTags } from "../api/client";
import { plural } from "../format";
import { visible } from "../text";
import { Sheet } from "./ui/Sheet";

const byName = (a: TagInfo, b: TagInfo) =>
  a.name.localeCompare(b.name, undefined, {
    sensitivity: "base",
    numeric: true,
  });

/** "Browse tags…": every tag by group with its file count (the Tags screen's list), to
 * pick from instead of typing. Choosing only hands the name back; a tag the field
 * already has is greyed out. */
export function TagBrowser({
  taken,
  onChoose,
  onCancel,
}: {
  taken: string[];
  onChoose: (name: string) => void;
  onCancel: () => void;
}) {
  const ids = useId();
  const [filter, setFilter] = useState("");
  const list = useAllTags(filter.trim());
  const have = new Set(taken.map((t) => t.normalize("NFC").toLocaleLowerCase()));
  const tags = list.data?.tags ?? [];
  const groups = list.data?.groups ?? [];
  const row = (t: TagInfo) => (
    <li key={t.name}>
      <button
        type="button"
        className="tag-browser-row"
        disabled={have.has(t.name.normalize("NFC").toLocaleLowerCase())}
        onClick={() => onChoose(t.name)}
      >
        <span>{visible(t.name)}</span>
        <span className="tag-suggest-count">{plural(t.files, "file")}</span>
      </button>
    </li>
  );
  const sections = [
    ...groups.map((g) => ({
      key: `g${g.id}`,
      title: g.name,
      tags: tags.filter((t) => t.group_id === g.id).sort(byName),
    })),
    {
      key: "loose",
      title: groups.length > 0 ? "Other tags" : null,
      tags: tags.filter((t) => t.group_id === null).sort(byName),
    },
  ].filter((s) => s.tags.length > 0);
  return (
    <Sheet
      open
      className="folder-browser"
      title="Choose a tag"
      onClose={onCancel}
      // Keys pressed here are the browser's: the sheet or page underneath never sees them.
      onKeyDown={(e) => e.stopPropagation()}
      footer={
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      }
    >
      <input
        type="search"
        className="folder-browser-filter"
        aria-label="Filter tags"
        placeholder="Filter tags"
        autoComplete="off"
        spellCheck={false}
        autoFocus
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      {list.isPending && <p className="busy">Loading tags…</p>}
      {list.isError && (
        <p className="error" role="alert">
          The tags could not be loaded: {visible(errorText(list.error))}
        </p>
      )}
      {list.data && sections.length === 0 && (
        <p className="hint">{filter.trim() ? "No tag matches." : "No tags yet."}</p>
      )}
      <div className="tag-browser" aria-label="Tags">
        {sections.map((s) => (
          <section key={s.key} aria-labelledby={s.title ? `${ids}-${s.key}` : undefined}>
            {s.title && (
              <h3 id={`${ids}-${s.key}`} className="tag-browser-group">
                {visible(s.title)}
              </h3>
            )}
            <ul className="tag-browser-list">{s.tags.map(row)}</ul>
          </section>
        ))}
      </div>
    </Sheet>
  );
}
