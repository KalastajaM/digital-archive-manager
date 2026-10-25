import { Ellipsis } from "lucide-react";
import { forwardRef, type ReactNode, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useFolders } from "../api/client";
import { visible } from "../text";
import { FolderBrowser, type RefusedRoot } from "./FolderBrowser";
import { IconButton } from "./ui/IconButton";

const MAX_SHOWN = 50;

type Props = {
  label: string;
  value: string;
  onChange: (folder: string) => void;
  /** Marks the field required (``aria-required``; the label says so). */
  required?: boolean;
  /** Special folders the browser refuses besides ``##. Ongoing`` and the quarantine
   * (the conversions: ``##. Important`` and the inbox). */
  refuse?: readonly RefusedRoot[];
  /** A problem with this field (e.g. "Choose a folder."): shown under it, with
   * ``aria-invalid`` and ``aria-describedby`` on the input. */
  error?: string | null;
  /** Shown right after the label (an info mark). */
  labelExtra?: ReactNode;
  /** The id of an element that describes the field (e.g. the info mark in ``labelExtra``). */
  describedBy?: string;
};

/** Text field with type-to-filter suggestions from /api/folders. Any text is allowed:
 * a folder that does not exist yet shows up as "New folder" in the plan. The "…"
 * button opens the folder browser to walk the tree instead (stars spec §9). */
export const FolderPicker = forwardRef<HTMLInputElement, Props>(function FolderPicker(
  { label, value, onChange, required, refuse, error, labelExtra, describedBy },
  ref,
) {
  const id = useId();
  const listId = `${id}-list`;
  const errorId = `${id}-error`;
  const folders = useFolders();
  const [open, setOpen] = useState(false);
  // The first suggestion is active by default, so Enter takes it.
  const [active, setActive] = useState(0);
  const [browsing, setBrowsing] = useState(false);
  const input = useRef<HTMLInputElement | null>(null);
  const setInput = useCallback(
    (el: HTMLInputElement | null) => {
      input.current = el;
      if (typeof ref === "function") ref(el);
      else if (ref) ref.current = el;
    },
    [ref],
  );
  // The browser closed (chosen or cancelled): the focus goes back to the field. After
  // the sheet's own close, which would put it back on the "…" button.
  const wasBrowsing = useRef(false);
  useEffect(() => {
    if (wasBrowsing.current && !browsing) input.current?.focus();
    wasBrowsing.current = browsing;
  }, [browsing]);

  const matches = useMemo(() => {
    const needle = value.trim().toLocaleLowerCase();
    const all = folders.data ?? [];
    const hits = needle ? all.filter((f) => f.toLocaleLowerCase().includes(needle)) : all;
    return hits.slice(0, MAX_SHOWN);
  }, [folders.data, value]);
  const shown = open && matches.length > 0;

  const choose = (folder: string) => {
    onChange(folder);
    setOpen(false);
    setActive(0);
  };

  return (
    <div className="folder-picker">
      {labelExtra ? (
        <div className="field-label-row">
          <label htmlFor={id}>{label}</label>
          {labelExtra}
        </div>
      ) : (
        <label htmlFor={id}>{label}</label>
      )}
      <div className="folder-picker-row">
        <input
          ref={setInput}
          id={id}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={shown}
          aria-controls={listId}
          aria-activedescendant={shown && active < matches.length ? `${listId}-${active}` : undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={[error ? errorId : null, describedBy].filter(Boolean).join(" ") || undefined}
          className={error ? "invalid" : undefined}
          autoComplete="off"
          spellCheck={false}
          aria-required={required || undefined}
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
            setOpen(true);
            setActive(0);
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
              setActive((i) => Math.max(0, Math.min(matches.length - 1, i + step)));
            } else if (e.key === "Enter" && !e.metaKey && !e.ctrlKey && shown && matches[active]) {
              e.preventDefault();
              choose(matches[active]);
            } else if (e.key === "Escape" && shown) {
              e.stopPropagation(); // first Esc closes the list, the next one leaves the field
              setOpen(false);
            }
          }}
        />
        <IconButton
          icon={<Ellipsis size={16} />}
          label="Browse folders…"
          className="folder-picker-browse"
          onClick={() => {
            setOpen(false);
            setBrowsing(true);
          }}
        />
      </div>
      {error && (
        <p id={errorId} className="error field-error" role="alert">
          {visible(error)}
        </p>
      )}
      {browsing && (
        <FolderBrowser
          value={value}
          refuse={refuse}
          onCancel={() => setBrowsing(false)}
          onChoose={(folder) => {
            onChange(folder);
            setBrowsing(false);
          }}
        />
      )}
      {shown && (
        <ul id={listId} role="listbox" aria-label={`${label} suggestions`} className="listbox">
          {matches.map((folder, i) => (
            <li
              key={folder}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              // mousedown, not click: the input's blur would close the list first
              onMouseDown={(e) => {
                e.preventDefault();
                choose(folder);
              }}
            >
              {visible(folder)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
});
