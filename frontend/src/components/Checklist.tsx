/** A checklist on a file, collection or item: add (Enter), tick, edit inline, remove,
 * and move up/down. Every change goes to the API; the order shown is always the
 * server's (``position`` from the reloaded list), the UI only asks for a move. */
import { useId, useRef, useState } from "react";
import {
  type ChecklistChange,
  type ChecklistItem,
  errorText,
  type NoteKind,
  useChecklist,
  useChecklistChange,
} from "../api/client";
import { visible } from "../text";

function Entry({
  entry,
  first,
  last,
  busy,
  run,
}: {
  entry: ChecklistItem;
  first: boolean;
  last: boolean;
  busy: boolean;
  run: (change: ChecklistChange) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const text = visible(entry.text);
  const checkId = useId();
  const saving = useRef(false); // Enter then blur sends the edit once
  const cancelled = useRef(false); // Esc: the blur that follows never saves

  const saveEdit = async () => {
    if (editing === null || saving.current || cancelled.current) return;
    const value = editing.trim();
    if (!value || value === entry.text) {
      setEditing(null);
      return;
    }
    saving.current = true;
    try {
      if (await run({ op: "set", id: entry.id, text: value })) setEditing(null);
    } finally {
      saving.current = false;
    }
  };

  return (
    <li className={entry.done ? "check check-done" : "check"}>
      <input
        id={checkId}
        type="checkbox"
        checked={entry.done}
        disabled={busy}
        onChange={(e) => void run({ op: "set", id: entry.id, done: e.target.checked })}
      />
      {editing === null ? (
        <>
          <label htmlFor={checkId} className="check-text">
            {text}
          </label>
          <button
            type="button"
            aria-label={`Edit ${text}`}
            onClick={() => {
              cancelled.current = false;
              setEditing(entry.text);
            }}
          >
            Edit
          </button>
        </>
      ) : (
        <input
          aria-label="Edit checklist entry"
          value={editing}
          autoFocus
          onChange={(e) => setEditing(e.target.value)}
          onBlur={() => void saveEdit()}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void saveEdit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              cancelled.current = true;
              setEditing(null);
            }
          }}
        />
      )}
      <button
        type="button"
        aria-label={`Move ${text} up`}
        disabled={busy || first}
        onClick={() => void run({ op: "move", id: entry.id, position: entry.position - 1 })}
      >
        ↑
      </button>
      <button
        type="button"
        aria-label={`Move ${text} down`}
        disabled={busy || last}
        onClick={() => void run({ op: "move", id: entry.id, position: entry.position + 1 })}
      >
        ↓
      </button>
      <button type="button" aria-label={`Remove ${text}`} disabled={busy} onClick={() => void run({ op: "remove", id: entry.id })}>
        ×
      </button>
    </li>
  );
}

export function Checklist({ kind, target }: { kind: NoteKind; target: string }) {
  const list = useChecklist(kind, target);
  const change = useChecklistChange();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const headingId = useId();
  const addId = useId();

  /** Send one change; true if it was stored (else the error is shown). */
  const run = async (c: ChecklistChange) => {
    setError(null);
    try {
      await change.mutateAsync(c);
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    }
  };

  const add = async () => {
    const value = text.trim();
    if (!value) return;
    if (await run({ op: "add", kind, target, text: value })) setText("");
  };

  const entries = list.data ?? [];
  return (
    <section className="checklist" aria-labelledby={headingId}>
      <h3 id={headingId}>Checklist</h3>
      {list.isError && (
        <p className="error" role="alert">
          Could not load the checklist. {visible(errorText(list.error))}
        </p>
      )}
      {entries.length > 0 && (
        <ul className="checks">
          {entries.map((entry, i) => (
            <Entry
              key={entry.id}
              entry={entry}
              first={i === 0}
              last={i === entries.length - 1}
              busy={change.isPending}
              run={run}
            />
          ))}
        </ul>
      )}
      <div className="field">
        <label htmlFor={addId}>Add to checklist</label>
        <input
          id={addId}
          placeholder="Type a to-do and press Enter"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void add();
            }
          }}
        />
      </div>
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </section>
  );
}
