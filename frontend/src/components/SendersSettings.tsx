/** Settings → Senders (New look): each business ID found on two or more documents, most
 * documents first (the count opens Browse on them), with the company name read next to it. A confirmed name becomes From on
 * every document that carries the ID, except where you set From or For yourself; clearing
 * it takes those back. */
import { type FormEvent, useId, useState } from "react";
import { Link } from "react-router-dom";
import { errorText, type IdentifierName, useIdentifierNames, usePutIdentifierName } from "../api/client";
import { visible } from "../text";
import { useMarkOwn } from "./FoundIdentifiers";
import { undoAction, useToast } from "./Toasts";

type Put = { kind: string; value: string; name: string | null };

const documents = (n: number) => (n === 1 ? "1 document" : `${n} documents`);

/** "Y-tunnus" from "Business ID (Y-tunnus)". */
const shortLabel = (label: string) => /\(([^)]+)\)/.exec(label)?.[1] ?? label;

function SenderRow({ row, undo }: { row: IdentifierName; undo: (body: Put) => void }) {
  const put = usePutIdentifierName();
  const own = useMarkOwn();
  const toast = useToast();
  const [draft, setDraft] = useState<string | null>(null);
  const stateId = useId();
  const shown = draft ?? row.name ?? row.suggested ?? "";
  const clean = shown.trim();
  const changed = row.name === null ? clean !== "" : clean !== "" && clean !== row.name;

  const send = (name: string | null, before: string | null) => {
    const body = { kind: row.kind, value: row.value };
    put.mutate(
      { ...body, name },
      {
        onSuccess: ({ changed: n, name: kept }) => {
          setDraft(null);
          toast({
            kind: "info",
            text: kept === null ? `${row.value} has no name now; From taken back on ${documents(n)}.` : `${kept} is now From on ${documents(n)}.`,
            action: undoAction(() => undo({ ...body, name: before })),
          });
        },
      },
    );
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (changed) send(clean, row.name);
  };

  return (
    <li className="senders-row" aria-label={`${shortLabel(row.label)} ${row.value}`}>
      <div className="senders-head">
        <span className="senders-id mono trunc" title={`${row.label} ${row.value}`}>
          {row.value}
        </span>
        <Link
          className="hint senders-count"
          to={`/browse?q=${encodeURIComponent(`id:${row.value}`)}`}
          title={`Show the documents that carry ${row.value} in Browse`}
        >
          {documents(row.files)}
        </Link>
      </div>
      {row.own ? (
        <div className="senders-form">
          <p className="hint senders-state">Yours: it names no sender and links no files.</p>
          <button type="button" disabled={own.pending} onClick={() => own.mark(row.kind, row.value, false)}>
            Not mine
          </button>
        </div>
      ) : (
        <>
          <form className="senders-form" onSubmit={submit}>
            <input
              type="text"
              aria-label={`Name for ${row.value}`}
              aria-describedby={stateId}
              readOnly={put.isPending}
              value={shown}
              maxLength={80}
              placeholder="Company name"
              onChange={(e) => setDraft(e.target.value)}
            />
            {row.name === null ? (
              <button type="submit" className="primary" disabled={!changed || put.isPending}>
                Confirm
              </button>
            ) : (
              <>
                {changed && (
                  <button type="submit" className="primary" disabled={put.isPending}>
                    Save
                  </button>
                )}
                <button type="button" disabled={put.isPending} onClick={() => send(null, row.name)}>
                  Clear
                </button>
              </>
            )}
          </form>
          <p className="hint senders-state" id={stateId}>
            {row.name !== null
              ? `Confirmed · From on ${row.filled} of ${row.files}`
              : row.suggested
                ? "Name read next to the ID in the documents"
                : "No name found next to the ID"}
          </p>
        </>
      )}
      {put.isError && (
        <p className="error" role="alert">
          {visible(errorText(put.error))}
        </p>
      )}
    </li>
  );
}

export function SendersSettings() {
  const query = useIdentifierNames();
  const toast = useToast();
  // Undo outlives its row (a cleared ID on one document leaves the list), so it is sent
  // from here and says when it fails
  const undoPut = usePutIdentifierName();
  const undo = (body: Put) =>
    undoPut.mutate(body, { onError: (e) => toast({ kind: "error", text: `Could not undo: ${errorText(e)}` }) });
  const [find, setFind] = useState("");
  const want = find.trim().toLocaleLowerCase();
  const rows = (query.data?.names ?? []).filter(
    (r) =>
      !want ||
      r.value.includes(want) ||
      [r.name, r.suggested].some((n) => n?.toLocaleLowerCase().includes(want)),
  );

  return (
    <section aria-label="Senders" className="senders-settings">
      <h3>Senders</h3>
      <p className="hint">
        Business IDs found on two or more documents. Confirm a company&apos;s name once and it becomes From on every
        document that carries its ID, now and later. A From or For you set yourself is never changed, and Clear takes
        the names back.
      </p>
      {query.isError && (
        <p className="error" role="alert">
          Could not load the senders: {visible(errorText(query.error))}
        </p>
      )}
      {query.data && query.data.names.length === 0 && (
        <p className="hint">
          No business ID is on two or more documents yet. They are read from the documents&apos; text in the background,
          with Finland on under Reading documents.
        </p>
      )}
      {query.data && query.data.names.length > 0 && (
        <>
          <input
            type="search"
            className="senders-find"
            aria-label="Find a sender"
            placeholder="Find a name or ID"
            value={find}
            onChange={(e) => setFind(e.target.value)}
          />
          <ul className="senders-list">
            {rows.map((r) => (
              <SenderRow key={`${r.kind} ${r.value}`} row={r} undo={undo} />
            ))}
          </ul>
          {rows.length === 0 && <p className="hint">No sender matches.</p>}
        </>
      )}
    </section>
  );
}
