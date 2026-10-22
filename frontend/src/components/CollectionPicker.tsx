import { Ellipsis } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { errorText, useCollections, useCollectionsWithMarked } from "../api/client";
import { visible } from "../text";
import { CollectionBrowser } from "./CollectionBrowser";
import { pathLabel } from "./collectionTree";
import { IconButton } from "./ui/IconButton";

const MAX_SHOWN = 50;
/** The API's limit (``NAME_MAX``); every other rule on names is the server's. */
export const COLLECTION_NAME_MAX = 120;

/** Close to the server's ``casefold`` on NFC names (enough to spot duplicates here;
 * the server has the last word). */
const fold = (name: string) => name.trim().normalize("NFC").toLowerCase().replace(/ß/g, "ss");

/** Text typed in the picker but not added: filing must not go ahead without it being
 * added or cleared (it would silently be left out). */
export function pendingCollection(text: string): string | null {
  const name = text.trim();
  return name ? `Press Enter to add ‘${name}’ or clear it` : null;
}

type Option = { kind: "existing" | "create" | "all" | "marked"; name: string; label: string };

const MARK_GLYPH = { starred: "★", important: "!" } as const;

type Props = {
  value: string[];
  onChange: (names: string[]) => void;
  /** The typed text, owned by the card so it can refuse to file while it is pending. */
  text: string;
  onTextChange: (text: string) => void;
  label?: string;
  /** Pick one existing collection: choosing replaces ``value``; nothing can be created
   * here and no chips are shown (the caller shows the choice). */
  single?: boolean;
  /** With ``single``: a first option with this label (e.g. "All files") that clears the
   * choice (``onChange([])``). */
  allOption?: string;
  /** Focus the field when shown (a picker opened from a button). */
  autoFocus?: boolean;
  /** Esc in the field when its list is closed (a picker opened from a button). */
  onEscape?: () => void;
  /** With ``single``: the built-in ★ Ongoing and ! Important as well, under a "Marked"
   * heading (the Browse collection filter only; every other picker leaves them out). */
  marked?: boolean;
};

/** "Also add to collection": type to filter the open collections (each shown with its
 * path, "Houses › Sauna"; the name or the path matches), Enter (or a click)
 * adds the highlighted one, an existing one named exactly so, or a new one ("Create
 * ‘…’", created when filing). Chosen names show as chips. Enter here never previews or
 * files: it only adds. The "…" button opens the collections as a tree to pick from
 * instead (``CollectionBrowser``); picking there is the same as picking from the list. */
export function CollectionPicker({
  value,
  onChange,
  text,
  onTextChange: setText,
  label = "Also add to collection",
  single = false,
  allOption,
  autoFocus = false,
  onEscape,
  marked = false,
}: Props) {
  const id = useId();
  const listId = `${id}-list`;
  const ordinary = useCollections("open");
  const withMarked = useCollectionsWithMarked(marked);
  // the marked list holds closed ones too: only the open ordinary ones are offered
  const collections = marked ? withMarked : ordinary;
  const openOnly = useMemo(
    () => (collections.data ?? []).filter((c) => c.kind == null && c.state === "open"),
    [collections.data],
  );
  // The built-ins as the server lists them (★ first), "★ Ongoing" and "! Important"
  const markedRows = useMemo((): Option[] => {
    if (!marked) return [];
    const rows = (collections.data ?? []).filter((c) => c.kind != null);
    rows.sort((a, b) => (a.kind === "starred" ? 0 : 1) - (b.kind === "starred" ? 0 : 1));
    return rows.map((c) => ({ kind: "marked", name: c.name, label: `${MARK_GLYPH[c.kind!]} ${c.name}` }));
  }, [marked, collections.data]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [problem, setProblem] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);

  const chosen = useMemo(() => new Set(value.map(fold)), [value]);
  const needle = fold(text);
  const options = useMemo((): Option[] => {
    const list = openOnly;
    const names = list.map((c) => c.name);
    // Shown with its full path ("Houses › Sauna"); typing matches the name or the path.
    const hits = list
      .map((c) => ({ name: c.name, label: pathLabel(c) }))
      .filter(({ name, label }) => !chosen.has(fold(name)) && (!needle || fold(label).includes(needle)))
      .slice(0, MAX_SHOWN)
      .map(({ name, label }): Option => ({ kind: "existing", name, label }));
    const exists = names.some((n) => fold(n) === needle) || chosen.has(needle);
    if (!single && needle && !exists) {
      hits.push({ kind: "create", name: text.trim(), label: `Create ‘${text.trim()}’` });
    }
    if (single && allOption && (!needle || fold(allOption).includes(needle))) {
      hits.unshift({ kind: "all", name: "", label: allOption });
    }
    if (single && marked) {
      hits.push(...markedRows.filter((o) => !needle || fold(o.label).includes(needle) || fold(o.name).includes(needle)));
    }
    return hits;
  }, [openOnly, markedRows, chosen, needle, text, single, allOption, marked]);
  const shown = open && options.length > 0;

  const clear = () => {
    setProblem(null);
    onChange([]);
    setText("");
    setOpen(false);
    setActive(-1);
  };
  const pick = (option: Option) => (option.kind === "all" ? clear() : add(option.name));
  const add = (raw: string) => {
    const name = raw.trim();
    if (!name) return;
    if (name.length > COLLECTION_NAME_MAX) {
      setProblem(`A collection name is at most ${COLLECTION_NAME_MAX} characters.`);
      return;
    }
    setProblem(null);
    if (single) onChange([name]);
    else if (!chosen.has(fold(name))) onChange([...value, name]);
    setText("");
    setOpen(false);
    setActive(-1);
  };
  /** Enter: the highlighted option, else the open collection named exactly so, else new. */
  const enter = () => {
    if (shown && active >= 0) return pick(options[active]);
    const existing = openOnly.find((c) => fold(c.name) === needle) ?? markedRows.find((o) => fold(o.name) === needle);
    if (single && !existing) {
      if (text.trim()) setProblem(`No collection named ‘${text.trim()}’`);
      return;
    }
    add(existing ? existing.name : text);
  };

  return (
    <div className="field folder-picker collection-picker">
      <label htmlFor={id}>{label}</label>
      <div className="folder-picker-row">
        <input
          id={id}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={shown}
          aria-controls={listId}
          aria-activedescendant={shown && active >= 0 ? `${listId}-${active}` : undefined}
          autoComplete="off"
          spellCheck={false}
          placeholder={single ? "Type to find a collection" : "e.g. Sauna conversion"}
          autoFocus={autoFocus}
          onFocus={() => {
            if (autoFocus) setOpen(true);
          }}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setProblem(null);
            setOpen(true);
            setActive(-1);
          }}
          onBlur={() => setOpen(false)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              e.preventDefault();
              if (!open) {
                setOpen(true);
                return;
              }
              const step = e.key === "ArrowDown" ? 1 : -1;
              setActive((i) => Math.max(-1, Math.min(options.length - 1, i + step)));
            } else if (e.key === "Enter" && !e.metaKey && !e.ctrlKey) {
              e.preventDefault();
              e.stopPropagation();
              enter();
            } else if (e.key === "Escape" && shown) {
              e.stopPropagation(); // first Esc closes the list, the next one leaves the field
              setOpen(false);
            } else if (e.key === "Escape" && onEscape) {
              e.stopPropagation();
              onEscape();
            }
          }}
        />
        <IconButton
          icon={<Ellipsis size={16} />}
          label="Browse collections…"
          className="folder-picker-browse"
          onClick={() => {
            setOpen(false);
            setBrowsing(true);
          }}
        />
      </div>
      {browsing && (
        <CollectionBrowser
          onCancel={() => setBrowsing(false)}
          onChoose={(name) => {
            setBrowsing(false);
            add(name);
          }}
        />
      )}
      {shown && (
        <ul id={listId} role="listbox" aria-label="Collections" className="listbox">
          {options.map((option, i) => [
            option.kind === "marked" && options[i - 1]?.kind !== "marked" && (
              <li key="marked-heading" role="presentation" className="listbox-heading">
                Marked
              </li>
            ),
            <li
              key={`${option.kind}:${option.name}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              // mousedown, not click: the input's blur would close the list first
              onMouseDown={(e) => {
                e.preventDefault();
                pick(option);
              }}
            >
              {visible(option.label)}
            </li>,
          ])}
        </ul>
      )}
      {collections.isError && (
        <p className="hint">Collections could not be loaded: {visible(errorText(collections.error))}</p>
      )}
      {problem && <p className="hint">{problem}</p>}
      {!problem && !single && text.trim() && <p className="hint">Press Enter to add.</p>}
      {!single && value.length > 0 && (
        <ul className="chips" aria-label="Collections to add">
          {value.map((name) => (
            <li key={fold(name)} className="chip">
              {visible(name)}
              <button
                type="button"
                aria-label={`Remove ${visible(name)}`}
                onClick={() => onChange(value.filter((n) => n !== name))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
