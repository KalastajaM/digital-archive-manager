/** The tag part of Browse's search box: the active tag filters as removable chips, and
 * the tags that match what is being typed. */
import { useId } from "react";
import { visible } from "../text";

export function TagChips({ tags, onRemove }: { tags: string[]; onRemove: (name: string) => void }) {
  if (tags.length === 0) return null;
  return (
    <ul className="search-tags" aria-label="Tag filters">
      {tags.map((t) => (
        <li key={t} className="tag-token">
          {visible(t)}
          <button type="button" aria-label={`Remove tag ${visible(t)}`} onClick={() => onRemove(t)}>
            ×
          </button>
        </li>
      ))}
    </ul>
  );
}

/** The tags offered while typing; ``active`` is the one the arrow keys are on. A tag is
 * taken on mouse down so the box keeps the focus. */
export function TagSuggestions({
  offered,
  active,
  onPick,
}: {
  offered: { name: string; files: number }[];
  active: number;
  onPick: (name: string) => void;
}) {
  const id = useId();
  if (offered.length === 0) return null;
  return (
    <ul id={id} className="tag-suggest" role="listbox" aria-label="Matching tags">
      {offered.map((t, i) => (
        <li
          key={t.name}
          role="option"
          aria-selected={i === active}
          className={i === active ? "active" : undefined}
          onMouseDown={(e) => {
            e.preventDefault();
            onPick(t.name);
          }}
        >
          {visible(t.name)}
          <span className="tag-suggest-count">{t.files}</span>
        </li>
      ))}
    </ul>
  );
}
