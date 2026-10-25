/** The tags field: the tags as removable chips with an input at the end (shared by a
 * file's details and the Inbox cards). Enter or a comma adds, ⌫ in the empty input
 * removes the last. While typing, the existing tags that start with the text (most used
 * first) are listed: ↑ ↓ choose, Enter adds the chosen one, Esc closes the list.
 *
 * The "…" button beside the field opens every tag by group with its count to pick from.
 *
 * Controlled: ``onChange`` gets the whole new list (the caller writes it at once, or
 * keeps it until filing). */
import { Ellipsis } from "lucide-react";
import { type KeyboardEvent, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { useTagSuggestions } from "../api/client";
import { isCmdEnter } from "../keyboard";
import { visible } from "../text";
import { TagBrowser } from "./TagBrowser";
import { IconButton } from "./ui/IconButton";

/** How many existing tags the field suggests at most. */
const SUGGEST_MAX = 8;

const fold = (s: string) => s.normalize("NFC").toLocaleLowerCase();

export function TagInput({
  value,
  onChange,
  label,
  id,
  placeholder = "Add a tag",
  disabled = false,
  disabledReason,
  passCmdEnter = false,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  /** The input's accessible name (when no ``<label htmlFor={id}>`` names it). */
  label?: string;
  id?: string;
  /** Shown while there are no tags. */
  placeholder?: string;
  disabled?: boolean;
  /** Why the field is off, shown on hover (the disabled input itself shows no tip). */
  disabledReason?: string | null;
  /** ⌘↩ adds the text being typed and then reaches the page's shortcut (the Inbox's
   * File it), which sees the tags with it. */
  passCmdEnter?: boolean;
}) {
  const [text, setText] = useState("");
  const [browsing, setBrowsing] = useState(false);
  // the list as last given or changed here, so two quick changes both count
  const latest = useRef(value);
  latest.current = value;
  const change = (next: string[]) => {
    latest.current = next;
    onChange(next);
  };
  const add = (raw: string[]) => {
    const have = new Set(latest.current.map(fold));
    const added: string[] = [];
    for (const t of raw.map((x) => x.trim()).filter(Boolean)) {
      if (!have.has(fold(t))) {
        have.add(fold(t));
        added.push(t);
      }
    }
    if (added.length > 0) change([...latest.current, ...added]);
  };

  // Suggestions: the tags in use that start with what is typed, minus the file's own.
  const listId = useId();
  const [focused, setFocused] = useState(false);
  const [active, setActive] = useState(-1);
  const [dismissed, setDismissed] = useState(false);
  const typed = text.trim();
  const found = useTagSuggestions(typed, Math.min(50, SUGGEST_MAX + value.length), focused && !disabled && typed !== "");
  const own = new Set(value.map(fold));
  const suggestions = typed === "" ? [] : (found.data ?? []).filter((t) => !own.has(fold(t.name))).slice(0, SUGGEST_MAX);
  const listOpen = focused && !dismissed && suggestions.length > 0;
  const chosen = listOpen && active >= 0 && active < suggestions.length ? suggestions[active] : null;
  const take = (name: string) => {
    add([name]);
    setText("");
    setActive(-1);
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (passCmdEnter && isCmdEnter(e.nativeEvent)) {
      // render the added tag before the page's own handler (which runs next) reads them
      flushSync(() => {
        add([text]);
        setText("");
      });
      return;
    }
    e.stopPropagation(); // page shortcuts never see keys typed here
    if (listOpen && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      const n = suggestions.length;
      setActive((a) => (e.key === "ArrowDown" ? (a + 1) % n : a <= 0 ? n - 1 : a - 1));
    } else if (e.key === "Escape" && listOpen) {
      e.preventDefault();
      setDismissed(true);
      setActive(-1);
    } else if (e.key === "Enter" && chosen) {
      e.preventDefault();
      take(chosen.name);
    } else if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add([text]);
      setText("");
    } else if (e.key === "Backspace" && text === "" && latest.current.length > 0) {
      e.preventDefault();
      change(latest.current.slice(0, -1));
    }
  };
  return (
    <div className="tag-field-wrap">
      <div className={disabled ? "tag-field disabled" : "tag-field"} title={disabled ? (disabledReason ?? undefined) : undefined}>
        {value.map((t) => (
          <span key={t} className="tag-token">
            {visible(t)}
            <button
              type="button"
              aria-label={`Remove tag ${visible(t)}`}
              disabled={disabled}
              onClick={() => change(latest.current.filter((x) => x !== t))}
            >
              ×
            </button>
          </span>
        ))}
        <input
          id={id}
          aria-label={label}
          value={text}
          placeholder={value.length === 0 ? placeholder : ""}
          disabled={disabled}
          spellCheck={false}
          role="combobox"
          aria-expanded={listOpen}
          aria-controls={listOpen ? listId : undefined}
          aria-autocomplete="list"
          aria-activedescendant={chosen ? `${listId}-${active}` : undefined}
          onFocus={() => setFocused(true)}
          onChange={(e) => {
            const v = e.target.value;
            setDismissed(false);
            setActive(-1);
            if (v.includes(",")) {
              // pasted or typed with commas: every part is a tag, the last stays being typed
              const parts = v.split(",");
              add(parts.slice(0, -1));
              setText(parts[parts.length - 1]);
            } else setText(v);
          }}
          onKeyDown={onKey}
          onBlur={() => {
            setFocused(false);
            setActive(-1);
            add([text]);
            setText("");
          }}
        />
      </div>
      <IconButton
        icon={<Ellipsis size={16} />}
        label="Browse tags…"
        className="folder-picker-browse"
        disabled={disabled}
        onClick={() => setBrowsing(true)}
      />
      {browsing && (
        <TagBrowser
          taken={value}
          onCancel={() => setBrowsing(false)}
          onChoose={(name) => {
            setBrowsing(false);
            add([name]);
          }}
        />
      )}
      {listOpen && (
        <ul id={listId} className="tag-suggest" role="listbox" aria-label="Existing tags">
          {suggestions.map((t, i) => (
            <li
              key={t.name}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : undefined}
              // mousedown, not click: the input keeps the focus (a blur would add the typed text)
              onMouseDown={(e) => {
                e.preventDefault();
                take(t.name);
              }}
            >
              {visible(t.name)}
              <span className="tag-suggest-count">{t.files}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
