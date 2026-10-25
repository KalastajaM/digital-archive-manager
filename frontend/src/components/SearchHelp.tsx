/** The ? next to a search box: a small popup listing every filter with an example and a
 * line, and a few tips. A click on an example puts it in the search box; the link opens
 * the guide's Searching section. Esc and a click outside close it. */
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FILTER_HELP } from "../searchFilters";
import { Popover } from "./ui/Popover";

const TIPS = [
  'Put a value with spaces in quotes: in:"50. Medical".',
  "In name: use * for any text and ? for one character.",
  "A - in front leaves out what matches: -tag:paid.",
  "Filters combine, and with plain words: kela type:pdf after:2025.",
];

export function SearchHelp({ onUse }: { onUse: (example: string) => void }) {
  const [anchor, setAnchor] = useState<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState(false);
  const first = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) first.current?.focus({ preventScroll: true });
  }, [open]);
  return (
    <>
      <button
        ref={setAnchor}
        type="button"
        className="search-help"
        aria-label="Search help"
        aria-expanded={open}
        title="Search filters"
        onClick={() => setOpen((o) => !o)}
      >
        ?
      </button>
      {open && (
        <Popover anchor={anchor} label="Search filters" onClose={() => setOpen(false)}>
          <div className="search-help-pop">
            <h3>Search filters</h3>
            <p className="muted">Type a filter in the search box, or click an example to start from it.</p>
            <ul className="search-help-list">
              {FILTER_HELP.map((f, i) => (
                <li key={f.name}>
                  <button
                    ref={i === 0 ? first : undefined}
                    type="button"
                    className="search-help-example"
                    onClick={() => {
                      onUse(f.example);
                      setOpen(false);
                    }}
                  >
                    {f.example}
                  </button>
                  <span>{f.text}</span>
                </li>
              ))}
            </ul>
            <ul className="search-help-tips">
              {TIPS.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
            <p>
              <Link to="/help#searching" onClick={() => setOpen(false)}>
                Searching in the guide
              </Link>
            </p>
          </div>
        </Popover>
      )}
    </>
  );
}
