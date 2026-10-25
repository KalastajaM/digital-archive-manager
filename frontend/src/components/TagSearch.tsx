/** The filter part of Browse's search: the active filters as removable chips (in a row of
 * the results pane), the + Tag control, All / Any for the tags, and the suggestions for
 * what is being typed. */
import { useId, useRef, useState } from "react";
import { useTagSuggestions } from "../api/client";
import { filterToken, positiveTags, type SearchFilter } from "../searchFilters";
import { visible } from "../text";
import type { Completion } from "./useSearchCompletions";
import { Segmented } from "./ui/Segmented";

export function FilterChips({ filters, onRemove }: { filters: SearchFilter[]; onRemove: (filter: SearchFilter) => void }) {
  if (filters.length === 0) return null;
  return (
    <ul className="search-tags" aria-label="Search filters">
      {filters.map((f) => (
        <li key={filterToken(f)} className={f.negated ? "tag-token filter-not" : "tag-token"}>
          <span className="filter-name">
            {f.negated ? "not " : ""}
            {f.name}:
          </span>
          {visible(f.value)}
          <button type="button" aria-label={`Remove filter ${filterToken(f)}`} onClick={() => onRemove(f)}>
            ×
          </button>
        </li>
      ))}
    </ul>
  );
}

/** What the box offers while typing: a filter name (``collection:``) or a value for the
 * filter being typed. ``active`` is the one the arrow keys are on. Taken on mouse down so
 * the box keeps the focus. */
export function SearchSuggestions({
  offered,
  active,
  onPick,
}: {
  offered: Completion[];
  active: number;
  onPick: (c: Completion) => void;
}) {
  const id = useId();
  if (offered.length === 0) return null;
  return (
    <ul id={id} className="tag-suggest" role="listbox" aria-label="Suggestions">
      {offered.map((c, i) => (
        <li
          key={c.key}
          role="option"
          aria-selected={i === active}
          className={i === active ? "active" : undefined}
          onMouseDown={(e) => {
            e.preventDefault();
            onPick(c);
          }}
        >
          {visible(c.label)}
          {c.hint !== undefined && <span className="tag-suggest-count">{c.hint}</span>}
        </li>
      ))}
    </ul>
  );
}

/** The tags offered in "+ Tag"; ``active`` is the one the arrow keys are on. A tag is
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

export type TagMode = "all" | "any";

/** "+ Tag": a small field with suggestions that adds one more tag filter. */
function AddTag({ tags, onAdd }: { tags: string[]; onAdd: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [on, setOn] = useState(-1); // the arrow keys' place in the list
  const inputRef = useRef<HTMLInputElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const suggested = useTagSuggestions(value.trim(), 8, open);
  const offered = (open ? (suggested.data ?? []) : [])
    .filter((t) => !tags.some((a) => a.toLowerCase() === t.name.toLowerCase()))
    .slice(0, 6);
  const close = () => {
    setOpen(false);
    setValue("");
    setOn(-1);
  };
  const pick = (name: string) => {
    onAdd(name);
    close();
    buttonRef.current?.focus();
  };
  if (!open) {
    return (
      <button
        ref={buttonRef}
        type="button"
        className="tag-add"
        onClick={() => {
          setOpen(true);
          setTimeout(() => inputRef.current?.focus(), 0);
        }}
      >
        + Tag
      </button>
    );
  }
  return (
    <div
      className="tag-add-field"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) close();
      }}
    >
      <input
        ref={inputRef}
        type="text"
        aria-label="Tag to add"
        placeholder="Tag name"
        value={value}
        spellCheck={false}
        autoFocus
        onChange={(e) => {
          setValue(e.target.value);
          setOn(-1);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            close();
            buttonRef.current?.focus();
          } else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && offered.length > 0) {
            e.preventDefault();
            const by = e.key === "ArrowDown" ? 1 : -1;
            setOn((n) => Math.max(-1, Math.min(offered.length - 1, n + by)));
          } else if (e.key === "Enter") {
            e.preventDefault();
            const typed = value.trim().toLowerCase();
            const exact = offered.find((t) => t.name.toLowerCase() === typed);
            const chosen = offered[on] ?? exact ?? offered[0];
            if (chosen) pick(chosen.name);
          }
        }}
      />
      <TagSuggestions offered={offered} active={on} onPick={pick} />
    </div>
  );
}

/** The row under a results pane's toolbar while anything filters: each filter as a
 * removable chip, + Tag, and (with two or more tags) the All / Any switch. */
export function FilterBar({
  filters,
  mode,
  onMode,
  onRemove,
  onAdd,
}: {
  filters: SearchFilter[];
  mode: TagMode;
  onMode: (mode: TagMode) => void;
  onRemove: (filter: SearchFilter) => void;
  onAdd: (name: string) => void;
}) {
  const tags = positiveTags(filters).map((f) => f.value);
  return (
    <div className="tag-bar">
      <FilterChips filters={filters} onRemove={onRemove} />
      <AddTag tags={filters.filter((f) => f.name === "tag").map((f) => f.value)} onAdd={onAdd} />
      {tags.length > 1 && (
        <Segmented<TagMode>
          ariaLabel="Match tags"
          className="tag-mode"
          value={mode}
          onChange={onMode}
          options={[
            { value: "all", label: "All", title: "A file needs every one of the tags" },
            { value: "any", label: "Any", title: "A file needs at least one of the tags" },
          ]}
        />
      )}
    </div>
  );
}
