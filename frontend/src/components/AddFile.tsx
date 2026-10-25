/** Choose a file of the archive: search as you type (the whole archive, with each path), or
 * browse folders. ``choose`` does what choosing means (attach the file to an item, or put
 * it in a tray); the file stays where it is either way. Arrow keys move through the list
 * (↓ from the search box into it, ↑ from the first entry back), Enter takes the one under
 * the focus, Esc closes. */
import { ChevronLeft, Folder } from "lucide-react";
import { type KeyboardEvent, useId, useRef, useState } from "react";
import { errorText, useBrowse } from "../api/client";
import { MarkIcons } from "./MarkIcons";
import { visible } from "../text";
import { useSearch } from "../screens/useSearch";

type Chosen = { drive_id: string; name: string };

type Props = {
  /** Drive ids that are in already. */
  taken: string[];
  /** ``hide``: left out of the hits; ``mark``: listed, marked with ``takenLabel`` and not
   * choosable. */
  takenMode?: "hide" | "mark";
  takenLabel?: string;
  choose: (hit: Chosen) => Promise<unknown>;
  onDone: () => void;
};

const parentOf = (path: string) => path.slice(0, Math.max(0, path.lastIndexOf("/")));

export function AddFile({ taken, takenMode = "hide", takenLabel = "already there", choose, onDone }: Props) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [browsing, setBrowsing] = useState(false);
  const [folder, setFolder] = useState("");
  const search = useSearch(query.trim());
  const listing = useBrowse(folder, browsing);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  const isTaken = (driveId: string) => taken.includes(driveId);
  const add = async (hit: Chosen) => {
    setError(null);
    setBusy(true);
    try {
      await choose(hit);
      onDone();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };

  const entries = () => Array.from(box.current?.querySelectorAll<HTMLButtonElement>("ul.entries button.entry:not(:disabled)") ?? []);
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onDone();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const list = entries();
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    if (document.activeElement === input.current) {
      if (e.key === "ArrowDown" && list.length > 0) list[0].focus();
      else return;
    } else if (at >= 0) {
      if (e.key === "ArrowDown") list[Math.min(at + 1, list.length - 1)].focus();
      else if (at === 0) input.current?.focus();
      else list[at - 1].focus();
    } else return;
    e.preventDefault();
    e.stopPropagation();
  };

  const searchHits = (search.hits ?? []).filter((h) => takenMode === "mark" || !isTaken(h.drive_id));
  const searching = query.trim() !== "";
  const rows = browsing && !searching ? (listing.data ?? []) : null;

  const fileButton = (h: { drive_id: string; name: string; marks?: Parameters<typeof MarkIcons>[0]["marks"]; path: string }) => {
    const already = isTaken(h.drive_id);
    return (
      <li key={h.drive_id}>
        <button type="button" className="entry" disabled={busy || already} onClick={() => void add(h)}>
          <span className="entry-name">
            {already ? `${visible(h.name)} (${takenLabel})` : `Add ${visible(h.name)}`}
          </span>
          <MarkIcons marks={h.marks} />
          <code className="entry-path">{visible(h.path)}</code>
        </button>
      </li>
    );
  };

  return (
    <div className="add-file" ref={box} onKeyDown={onKeyDown}>
      <label htmlFor={id}>Find a file</label>
      <input
        ref={input}
        id={id}
        type="search"
        value={query}
        autoFocus
        spellCheck={false}
        onChange={(e) => setQuery(e.target.value)}
      />
      <button
        type="button"
        className="link-button add-file-browse"
        aria-expanded={browsing}
        onClick={() => setBrowsing((b) => !b)}
      >
        {browsing ? "Hide folders" : "Browse folders…"}
      </button>
      {search.error && (
        <p className="error" role="alert">
          Search failed. {visible(search.error)}
        </p>
      )}
      {searching && search.hits !== null && searchHits.length === 0 && <p className="hint">No other files match.</p>}
      {searching && searchHits.length > 0 && <ul className="entries">{searchHits.map(fileButton)}</ul>}
      {browsing && !searching && (
        <div className="add-file-folder" role="group" aria-label="Folders">
          <p className="add-file-where">
            {folder !== "" && (
              <button
                type="button"
                className="link-button"
                aria-label="Up one folder"
                onClick={() => setFolder(parentOf(folder))}
              >
                <ChevronLeft size={14} aria-hidden="true" />
              </button>
            )}
            <code>{folder === "" ? "Archive" : visible(folder)}</code>
          </p>
          {listing.isError && (
            <p className="error" role="alert">
              Could not open the folder. {visible(errorText(listing.error))}
            </p>
          )}
          {rows && rows.length === 0 && <p className="hint">Nothing in this folder.</p>}
          {rows && rows.length > 0 && (
            <ul className="entries">
              {rows.map((r) =>
                r.is_dir ? (
                  <li key={r.drive_id}>
                    <button type="button" className="entry" onClick={() => setFolder(r.path)}>
                      <Folder size={14} aria-hidden="true" />
                      <span className="entry-name">Open folder {visible(r.name)}</span>
                    </button>
                  </li>
                ) : (
                  fileButton(r)
                ),
              )}
            </ul>
          )}
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </div>
  );
}
