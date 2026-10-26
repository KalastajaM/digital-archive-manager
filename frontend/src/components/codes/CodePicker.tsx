/** Assign a filing code to inbox files from the app, as if a sticker were on them: a
 * small popover at the Inbox toolbar, opened with its button or the ``c`` key. Typing
 * filters the codes (by code first, then by label); ↑/↓ move, Enter or a click assigns,
 * Esc closes. */
import { useEffect, useId, useRef, useState } from "react";
import type { FilingCode } from "../../api/client";
import { visible } from "../../text";
import { Popover } from "../ui/Popover";

/** The entry that takes the assigned code away. */
export const NO_CODE = "No assigned code";

type Props = {
  anchor: HTMLElement | null;
  codes: FilingCode[];
  /** How many files the code goes to (said in the field's label). */
  count: number;
  /** One of the files has an assigned code: offer to take it away. */
  canClear: boolean;
  onPick: (code: string | null) => void;
  onClose: () => void;
};

/** The codes ``query`` matches: codes starting with it first, then labels holding it. */
export function matchCodes(codes: FilingCode[], query: string): FilingCode[] {
  const q = query.trim().toUpperCase();
  if (!q) return codes;
  const byCode = codes.filter((c) => c.code.startsWith(q));
  const byLabel = codes.filter((c) => !byCode.includes(c) && c.label.toUpperCase().includes(q));
  return [...byCode, ...byLabel];
}

export function CodePicker({ anchor, codes, count, canClear, onPick, onClose }: Props) {
  const listId = useId();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  // The popover is hidden until it is placed, and a hidden field cannot take the focus
  // (``autoFocus`` would miss): focus it on the next frame.
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const frame = requestAnimationFrame(() => field.current?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(frame);
  }, []);
  const shown = matchCodes(codes, query);
  // the codes, then "No assigned code" (when there is one to take away and no filter)
  const options: (string | null)[] = [...shown.map((c) => c.code), ...(canClear && !query.trim() ? [null] : [])];
  const at = Math.min(active, options.length - 1);

  return (
    <Popover anchor={anchor} label="Assign a filing code" onClose={onClose}>
      <div className="code-picker">
        <input
          ref={field}
          type="text"
          role="combobox"
          aria-label={count > 1 ? `Filing code for ${count} files` : "Filing code"}
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={options.length > 0 ? `${listId}-${at}` : undefined}
          placeholder="Code or label"
          value={query}
          spellCheck={false}
          autoComplete="off"
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              e.preventDefault();
              const step = e.key === "ArrowDown" ? 1 : -1;
              setActive(Math.max(0, Math.min(options.length - 1, at + step)));
            } else if (e.key === "Enter") {
              e.preventDefault();
              if (options.length > 0) onPick(options[at]);
            }
          }}
        />
        {options.length === 0 ? (
          <p className="hint">No code matches.</p>
        ) : (
          <ul id={listId} className="code-picker-list" role="listbox" aria-label="Filing codes">
            {options.map((code, i) => {
              const fc = shown.find((c) => c.code === code);
              return (
                <li
                  key={code ?? ""}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-label={fc ? `${visible(fc.code)}: ${visible(fc.label)}` : NO_CODE}
                  aria-selected={i === at}
                  className={i === at ? "active" : undefined}
                  onMouseDown={(e) => e.preventDefault()} // keep the focus in the field
                  onMouseEnter={() => setActive(i)}
                  onClick={() => onPick(code)}
                >
                  {fc ? (
                    <>
                      <span className="code-picker-code">{visible(fc.code)}</span>
                      <span className="code-picker-label">{visible(fc.label)}</span>
                    </>
                  ) : (
                    <span className="code-picker-label">{NO_CODE}</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Popover>
  );
}
