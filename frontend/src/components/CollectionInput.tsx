/** The collections field, like the tags field: the collections as chips (× removes one),
 * an input that lists the matching open collections as you type (↑ ↓ choose, Enter or a
 * click adds), and "Create collection ‘…’" when the typed name is none yet. The "…"
 * button beside it opens the collections as a tree (``CollectionBrowser``) instead.
 *
 * What adding and removing *do* is the caller's: a file's collections apply at once, the
 * Inbox card and a rule keep the names until filing or saving. For a name that is no
 * collection yet the caller creates it (at once, or when filing). A refusal thrown by
 * ``onAdd`` (the server's name rules) is shown under the field. */
import { Ellipsis } from "lucide-react";
import { type KeyboardEvent, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { errorText, useCollections } from "../api/client";
import { visible } from "../text";
import { CollectionBrowser } from "./CollectionBrowser";
import { COLLECTION_NAME_MAX } from "./CollectionPicker";
import { pathLabel } from "./collectionTree";
import { IconButton } from "./ui/IconButton";

/** How many matching collections the list shows at most. */
const MAX_SHOWN = 50;

const fold = (name: string) => name.trim().normalize("NFC").toLowerCase().replace(/ß/g, "ss");

/** A chip: ``key`` tells chips apart (a collection's id), ``to`` makes the name a link,
 * ``removable`` false leaves out the × (a built-in, a closed collection, one that comes
 * through a folder). */
export type CollectionChip = {
  key: string;
  name: string;
  to?: string;
  suffix?: string;
  removable?: boolean;
};

type Option = { kind: "existing" | "create"; name: string; label: string };

export function CollectionInput({
  value,
  onAdd,
  onRemove,
  label,
  visibleLabel = false,
  placeholder = "Add a collection",
  removeLabel = (name) => `Remove ${name}`,
  text: givenText,
  onTextChange,
  disabled = false,
  disabledReason,
  autoFocus = false,
  onEscape,
}: {
  value: (string | CollectionChip)[];
  /** Adds the collection (the name of an open one, or a new name); may throw a refusal. */
  onAdd: (name: string) => void | Promise<void>;
  onRemove: (chip: CollectionChip) => void;
  /** The input's accessible name. */
  label: string;
  /** Show ``label`` as a visible label above the field (the Inbox card and the rule sheet). */
  visibleLabel?: boolean;
  /** Shown while there are no chips. */
  placeholder?: string;
  /** The name of the × button of a chip. */
  removeLabel?: (name: string) => string;
  /** The typed text, when the owner needs it (to refuse filing with a half-typed name). */
  text?: string;
  onTextChange?: (text: string) => void;
  disabled?: boolean;
  /** Why the field is off, shown on hover (the disabled input itself shows no tip). */
  disabledReason?: string | null;
  autoFocus?: boolean;
  /** Esc in the field when its list is closed. */
  onEscape?: () => void;
}) {
  const id = useId();
  const listId = `${id}-list`;
  const [ownText, setOwnText] = useState("");
  const text = givenText ?? ownText;
  const setText = (t: string) => {
    if (onTextChange) onTextChange(t);
    else setOwnText(t);
  };
  const chips = useMemo(
    () => value.map((v): CollectionChip => (typeof v === "string" ? { key: v, name: v } : v)),
    [value],
  );
  const collections = useCollections("open");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [problem, setProblem] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);
  const busy = useRef(false);
  const [pending, setPending] = useState(false);

  const openOnly = useMemo(
    () => (collections.data ?? []).filter((c) => c.kind == null && c.state === "open"),
    [collections.data],
  );
  const chosen = useMemo(() => new Set(chips.map((c) => fold(c.name))), [chips]);
  const needle = fold(text);
  const options = useMemo((): Option[] => {
    const hits = openOnly
      .map((c) => ({ name: c.name, label: pathLabel(c) }))
      .filter(({ name, label: path }) => !chosen.has(fold(name)) && (!needle || fold(path).includes(needle)))
      .slice(0, MAX_SHOWN)
      .map(({ name, label: path }): Option => ({
        kind: "existing",
        name,
        label: path,
      }));
    const exists = openOnly.some((c) => fold(c.name) === needle) || chosen.has(needle);
    if (needle && !exists)
      hits.push({
        kind: "create",
        name: text.trim(),
        label: `Create collection "${text.trim()}"`,
      });
    return hits;
  }, [openOnly, chosen, needle, text]);
  // the list is for typing: it opens with text (or ↓ on an empty field)
  const shown = open && !disabled && options.length > 0;

  const add = async (raw: string) => {
    const name = raw.trim();
    if (!name || busy.current) return;
    if (name.length > COLLECTION_NAME_MAX) {
      setProblem(`A collection name is at most ${COLLECTION_NAME_MAX} characters.`);
      return;
    }
    setProblem(null);
    if (chosen.has(fold(name))) {
      setText("");
      return;
    }
    busy.current = true;
    setPending(true);
    try {
      await onAdd(name);
      setText("");
      setOpen(false);
      setActive(-1);
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      busy.current = false;
      setPending(false);
    }
  };
  /** Enter: the highlighted option, else the open collection named exactly so, else a new one. */
  const enter = () => {
    if (shown && active >= 0) return void add(options[active].name);
    const existing = openOnly.find((c) => fold(c.name) === needle);
    void add(existing ? existing.name : text);
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) return; // the page's File it
    e.stopPropagation(); // page shortcuts never see keys typed here
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return setOpen(true);
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => Math.max(-1, Math.min(options.length - 1, i + step)));
    } else if (e.key === "Enter") {
      e.preventDefault();
      enter();
    } else if (e.key === "Escape") {
      if (shown) {
        e.preventDefault();
        setOpen(false);
        setActive(-1);
      } else if (onEscape) onEscape();
    } else if (e.key === "Backspace" && text === "") {
      const last = [...chips].reverse().find((c) => c.removable !== false);
      if (last) {
        e.preventDefault();
        onRemove(last);
      }
    }
  };

  const field = (
    <div className="collection-input-row">
      <div className="tag-field-wrap">
        <div className={disabled ? "tag-field disabled" : "tag-field"} title={disabled ? (disabledReason ?? undefined) : undefined}>
          {chips.map((c) => (
            <span key={c.key} className="tag-token">
              {c.to ? (
                <Link to={c.to}>
                  {visible(c.name)}
                  {c.suffix}
                </Link>
              ) : (
                <>
                  {visible(c.name)}
                  {c.suffix}
                </>
              )}
              {c.removable !== false && (
                <button
                  type="button"
                  aria-label={removeLabel(visible(c.name))}
                  disabled={disabled || pending}
                  onClick={() => onRemove(c)}
                >
                  ×
                </button>
              )}
            </span>
          ))}
          <input
            id={id}
            aria-label={visibleLabel ? undefined : label}
            role="combobox"
            aria-expanded={shown}
            aria-controls={shown ? listId : undefined}
            aria-autocomplete="list"
            aria-activedescendant={shown && active >= 0 ? `${listId}-${active}` : undefined}
            autoComplete="off"
            spellCheck={false}
            autoFocus={autoFocus}
            disabled={disabled}
            placeholder={chips.length === 0 ? placeholder : ""}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setProblem(null);
              setOpen(true);
              setActive(-1);
            }}
            onBlur={() => {
              setOpen(false);
              setActive(-1);
            }}
            onKeyDown={onKey}
          />
        </div>
        {shown && (
          <ul id={listId} className="tag-suggest" role="listbox" aria-label="Collections">
            {options.map((option, i) => (
              <li
                key={`${option.kind}:${option.name}`}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                className={i === active ? "active" : undefined}
                // mousedown, not click: the input keeps the focus (a blur would close the list first)
                onMouseDown={(e) => {
                  e.preventDefault();
                  void add(option.name);
                }}
              >
                {visible(option.label)}
              </li>
            ))}
          </ul>
        )}
      </div>
      <IconButton
        icon={<Ellipsis size={16} />}
        label="Browse collections…"
        className="folder-picker-browse"
        disabled={disabled || pending}
        onClick={() => {
          setOpen(false);
          setBrowsing(true);
        }}
      />
    </div>
  );
  return (
    <div className="collection-input">
      {visibleLabel ? (
        <div className="field">
          <label htmlFor={id}>{label}</label>
          {field}
        </div>
      ) : (
        field
      )}
      {browsing && (
        <CollectionBrowser
          onCancel={() => setBrowsing(false)}
          onChoose={(name) => {
            setBrowsing(false);
            void add(name);
          }}
        />
      )}
      {collections.isError && (
        <p className="hint">Collections could not be loaded: {visible(errorText(collections.error))}</p>
      )}
      {pending && (
        <p className="hint" role="status">
          Adding…
        </p>
      )}
      {problem && (
        <p className="error" role="alert">
          {visible(problem)}
        </p>
      )}
    </div>
  );
}

/** The field for names kept until later (the Inbox card's "Also add to collection", a
 * rule's "Add to collection"): the chips are ``value``, nothing is applied or created
 * here (a new name is created when the files are filed). ``text`` is the owner's, so it
 * can refuse to go on with a half-typed name (``pendingCollection``). */
export function CollectionNamesInput({
  value,
  onChange,
  text,
  onTextChange,
  label = "Also add to collection",
}: {
  value: string[];
  onChange: (names: string[]) => void;
  text: string;
  onTextChange: (text: string) => void;
  label?: string;
}) {
  return (
    <CollectionInput
      label={label}
      visibleLabel
      placeholder="e.g. Sauna conversion"
      value={value}
      text={text}
      onTextChange={onTextChange}
      onAdd={(name) => onChange([...value, name])}
      onRemove={(chip) => onChange(value.filter((n) => n !== chip.name))}
    />
  );
}
