/** From (who sent a document) and For (who it is for), said by hand. The Inbox card shows
 * both as chips with where they came from; the Inbox batch and a Browse selection open the
 * same sheet for many documents at once. */
import { useId, useState } from "react";
import { useStyle } from "../../appearance";
import { errorText, type InboxEntry, usePeople, usePutAssignments, useSenders, useWaitForPage1 } from "../../api/client";
import { plural } from "../../format";
import { visible } from "../../text";
import { Sheet } from "../ui/Sheet";

export type AssignKind = "sender" | "person";

const WORD: Record<AssignKind, string> = { sender: "From", person: "For" };
/** What an empty chip says in the New look (a dashed button, as drawn). */
const EMPTY: Record<AssignKind, string> = { sender: "Who sent it?", person: "Who is it for?" };

/** The sheet that sets From or For on these documents. ``current``: what one document has
 * would be preselected (a person found in the address area counts); ``assigned``: this
 * one document has an assignment in this field, so there is something to clear. For many
 * documents Clear is always offered and takes the field away from all of them. */
export function AssignSheet({
  kind,
  driveIds,
  current = null,
  assigned = false,
  onClose,
}: {
  kind: AssignKind;
  driveIds: string[];
  current?: string | null;
  assigned?: boolean;
  onClose: () => void;
}) {
  const ids = useId();
  const senders = useSenders(kind === "sender");
  const people = usePeople();
  const put = usePutAssignments();
  const [value, setValue] = useState(current ?? "");
  const [error, setError] = useState<string | null>(null);

  const save = async (next: string | null) => {
    setError(null);
    try {
      await put.mutateAsync({ drive_ids: driveIds, [kind]: next });
      onClose();
    } catch (e) {
      setError(errorText(e));
    }
  };
  const choices =
    kind === "sender"
      ? (senders.data ?? []).map((s) => ({ name: s.sender, note: String(s.count) }))
      : (people.data?.people ?? []).map((p) => ({ name: p.name, note: "" }));
  const what = driveIds.length === 1 ? "this document" : `these ${plural(driveIds.length, "document")}`;
  const title = driveIds.length === 1 ? WORD[kind] : `${WORD[kind]} (${plural(driveIds.length, "document")})`;
  const typed = value.trim();

  return (
    <Sheet
      open
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>Cancel</button>
          {(driveIds.length > 1 || assigned) && (
            <button type="button" disabled={put.isPending} onClick={() => void save(null)}>
              Clear
            </button>
          )}
          <button type="button" className="primary" disabled={!typed || put.isPending} onClick={() => void save(typed)}>
            Save
          </button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (typed) void save(typed);
        }}
      >
        <p>{kind === "sender" ? `Who sent ${what}?` : `Who is ${what} for?`}</p>
        {kind === "sender" && (
          <div className="field">
            <label htmlFor={`${ids}-sender`}>Sender</label>
            <input id={`${ids}-sender`} value={value} placeholder="Pohjola" autoFocus onChange={(e) => setValue(e.target.value)} />
          </div>
        )}
        {choices.length > 0 && (
          <ul className="assign-choices" aria-label={kind === "sender" ? "Senders you have used" : "People"}>
            {choices.map((c) => (
              <li key={c.name}>
                <button
                  type="button"
                  className="assign-choice"
                  aria-pressed={typed === c.name}
                  onClick={() => setValue(c.name)}
                >
                  {visible(c.name)}
                  {c.note && <span className="assign-count"> {c.note}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
        {kind === "person" && people.data && choices.length === 0 && (
          <p className="hint">No people yet. Add them in Settings, under Filing rules.</p>
        )}
        {error && <p className="error" role="alert">{visible(error)}</p>}
      </form>
    </Sheet>
  );
}

/** Where a person came from, in words. */
function personSource(entry: InboxEntry): string | null {
  const { person, person_source: source } = entry.suggestion;
  if (!person) return null;
  if (source === "assigned") return entry.assignment?.set_by === "filing" ? "filed" : "you set this";
  if (source === "address area") return "address area";
  if (source === "document area") return "this document's address area";
  if (source?.startsWith("rule:")) return `rule ${source.slice("rule:".length)}`;
  return source ?? null;
}

/** "From: <sender>" and "For: <person>" on the Inbox card, each with its source; a click
 * opens the picker. A letter to several people asks "For whom?". While page 1 is not read
 * the suggestion cannot say, and the card says so quietly. */
export function FromFor({ entry }: { entry: InboxEntry }) {
  const id = entry.record.drive_id;
  const { person, people_found: found, waiting_for_page1: reading, page1_unavailable: unavailable } = entry.suggestion;
  const sender = entry.assignment?.sender ?? null;
  const [picking, setPicking] = useState<AssignKind | null>(null);
  const [look] = useStyle();
  const isNew = look === "new";
  const put = usePutAssignments();
  const [error, setError] = useState<string | null>(null);
  useWaitForPage1(id, reading);

  const chip = (kind: AssignKind, value: string | null, source: string | null) => (
    <button type="button" className={value ? "from-for-chip" : "from-for-chip from-for-empty"} onClick={() => setPicking(kind)}>
      <span className="from-for-word">{isNew ? WORD[kind] : `${WORD[kind]}:`}</span>{" "}
      {isNew ? (
        <span className="from-for-value">{value ? visible(value) : EMPTY[kind]}</span>
      ) : value ? (
        visible(value)
      ) : (
        <span className="hint">not set</span>
      )}
      {value && source && (
        <>
          {" "}
          <span className="from-for-source">· {source}</span>
        </>
      )}
    </button>
  );
  const choose = async (name: string) => {
    setError(null);
    try {
      await put.mutateAsync({ drive_ids: [id], person: name });
    } catch (e) {
      setError(errorText(e));
    }
  };
  return (
    <div className="from-for">
      <div className="from-for-chips">
        {chip("sender", sender, sender ? (entry.assignment?.set_by === "filing" ? "filed" : "you set this") : null)}
        {chip("person", person ?? null, personSource(entry))}
      </div>
      {found.length >= 2 && (
        <div className="from-for-whom" role="group" aria-label="For whom?">
          <span className="hint">For whom?</span>
          {found.map((name) => (
            <button key={name} type="button" className="assign-choice" disabled={put.isPending} onClick={() => void choose(name)}>
              {visible(name)}
            </button>
          ))}
        </div>
      )}
      {reading && (
        <p className="hint" role="status">
          Reading page 1…
        </p>
      )}
      {unavailable && (
        <p className="hint" role="status">
          Page 1 could not be read: {visible(unavailable)}.
        </p>
      )}
      {error && <p className="error" role="alert">{visible(error)}</p>}
      {picking && (
        <AssignSheet
          kind={picking}
          driveIds={[id]}
          current={picking === "sender" ? sender : (person ?? null)}
          assigned={picking === "sender" ? sender !== null : (entry.assignment?.person ?? null) !== null}
          onClose={() => setPicking(null)}
        />
      )}
    </div>
  );
}
