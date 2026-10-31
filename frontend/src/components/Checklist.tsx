/** A checklist on a file, collection or item: add (Enter), tick, click a text to edit it
 * inline, drag a row by its grip (or Option-Up/Down on a focused row) to reorder, and a
 * delete button shown on hover or focus. Every change goes to the API; the order shown is always the
 * server's (``position`` from the reloaded list), the UI only asks for a move. */
import { GripVertical, X } from "lucide-react";
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
import { Collapsible } from "./Collapsible";
import { IconButton } from "./ui/IconButton";

const CHECK_DRAG_TYPE = "application/x-dam-checklist-entry";

function Entry({
  entry,
  first,
  last,
  busy,
  run,
  dragged,
  setDragged,
  announce,
}: {
  entry: ChecklistItem;
  first: boolean;
  last: boolean;
  busy: boolean;
  run: (change: ChecklistChange) => Promise<boolean>;
  /** The id of the entry being dragged in this list, or null. */
  dragged: number | null;
  setDragged: (id: number | null) => void;
  /** Says a new position to screen readers. */
  announce: (text: string) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const text = visible(entry.text);
  const saving = useRef(false); // Enter then blur sends the edit once
  const cancelled = useRef(false); // Esc: the blur that follows never saves
  const textButton = useRef<HTMLButtonElement>(null);

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

  const moveTo = async (position: number) => {
    if (await run({ op: "move", id: entry.id, position })) {
      announce(`${text} moved to position ${position + 1}`);
      return true;
    }
    return false;
  };

  const classes = ["check"];
  if (entry.done) classes.push("check-done");
  if (dragged === entry.id) classes.push("check-dragging");
  if (over && dragged !== null && dragged !== entry.id) classes.push("check-drop");

  return (
    <li
      className={classes.join(" ")}
      draggable={editing === null && !busy}
      onDragStart={(e) => {
        e.dataTransfer.setData(CHECK_DRAG_TYPE, String(entry.id));
        e.dataTransfer.effectAllowed = "move";
        setDragged(entry.id);
      }}
      onDragEnd={() => {
        setDragged(null);
        setOver(false);
      }}
      onDragOver={(e) => {
        if (dragged === null || dragged === entry.id) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        if (dragged === null) return;
        e.preventDefault();
        const id = dragged;
        setDragged(null);
        setOver(false);
        if (id !== entry.id) void run({ op: "move", id, position: entry.position });
      }}
      onKeyDown={(e) => {
        if (editing !== null || !e.altKey || busy) return;
        if (e.key === "ArrowUp" && !first) {
          e.preventDefault();
          void moveTo(entry.position - 1).then(() => textButton.current?.focus());
        } else if (e.key === "ArrowDown" && !last) {
          e.preventDefault();
          void moveTo(entry.position + 1).then(() => textButton.current?.focus());
        }
      }}
    >
      <span className="check-grip" aria-hidden="true">
        <GripVertical size={14} />
      </span>
      <input
        type="checkbox"
        aria-label={text}
        checked={entry.done}
        disabled={busy}
        onChange={(e) => void run({ op: "set", id: entry.id, done: e.target.checked })}
      />
      {editing === null ? (
        <button
          ref={textButton}
          type="button"
          className="check-text"
          title="Click to edit. Option-Up or Option-Down moves it."
          onClick={() => {
            cancelled.current = false;
            setEditing(entry.text);
          }}
        >
          {text}
        </button>
      ) : (
        <input
          className="check-text"
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
      <IconButton
        className="check-delete"
        icon={<X />}
        label={`Delete ${text}`}
        tip="Delete"
        disabled={busy}
        onClick={() => void run({ op: "remove", id: entry.id })}
      />
    </li>
  );
}

export function Checklist({ kind, target }: { kind: NoteKind; target: string }) {
  const list = useChecklist(kind, target);
  const change = useChecklistChange();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [dragged, setDragged] = useState<number | null>(null);
  const [announcement, setAnnouncement] = useState("");
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
    <Collapsible
      name="checklist"
      title="Checklist"
      className="checklist"
      aside={entries.length > 0 ? <span className="check-count">{`${entries.filter((e) => e.done).length} of ${entries.length}`}</span> : undefined}
      hint={entries.length === 0 ? "Nothing yet" : `${entries.filter((e) => e.done).length} of ${entries.length} done`}
    >
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
              dragged={dragged}
              setDragged={setDragged}
              announce={setAnnouncement}
            />
          ))}
        </ul>
      )}
      <p className="visually-hidden" role="status">
        {announcement}
      </p>
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
    </Collapsible>
  );
}
