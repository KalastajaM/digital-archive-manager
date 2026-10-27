/** "Moved outside dam": a file without a Drive id that was renamed or moved in Finder or
 * Explorer gets a new index row, and its tags, notes, collections and the rest stay on the
 * old, missing one. The check pairs the two by size and content; Reconnect moves it all to
 * the new row after a preview. It changes only the app's own records, so it is not in
 * Activity; Undo in the message afterwards puts the old rows back. A file whose content
 * matches more than one file is only listed. */
import { FileSearch } from "lucide-react";
import { useState } from "react";
import { type MovedPair, useReconnectMoved, useUndoReconnect } from "../../api/client";
import { formatSize, plural } from "../../format";
import { visible } from "../../text";
import { undoAction, useBlockToastActions, useToast } from "../Toasts";
import { Sheet } from "../ui/Sheet";
import { Tag } from "../ui/Tag";
import { IgnoreButton, useIgnore } from "./Ignore";
import { browseTo, Capped, CheckCard, ListHead, refusal, useTicks } from "./ListChecks";
import { ShowInBrowse } from "./ShowInBrowse";
import { useMaintenanceJob } from "./useMaintenanceJob";

const keyOf = (p: { old_id: string; new_id: string }) => `${p.old_id}>${p.new_id}`;

const WORDS: Record<string, (n: number) => string> = {
  tags: (n) => plural(n, "tag"),
  collections: (n) => plural(n, "collection"),
  tray_items: (n) => plural(n, "tray item"),
  note: () => "the note",
  checklist: (n) => plural(n, "checklist entry", "checklist entries"),
  lock: () => "the lock",
  from_for: () => "From and For",
  filing_code: () => "the filing code",
  summaries: () => "the summary",
  fields: () => "the scan fields",
  rule_outcomes: () => "the filing history",
};

/** What would move, in words: "1 tag, 2 collections and the note". */
export function movesText(moves: Record<string, number>) {
  const parts = Object.entries(moves).map(([k, n]) => (WORDS[k] ? WORDS[k](n) : k));
  return parts.length <= 1 ? (parts[0] ?? "nothing") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

export function Moved() {
  const check = useMaintenanceJob("moved");
  const reconnect = useReconnectMoved();
  const undoReconnect = useUndoReconnect();
  const toast = useToast();
  const ignore = useIgnore(check.reload);
  const [preview, setPreview] = useState<MovedPair[] | null>(null);
  useBlockToastActions(reconnect.isPending || undoReconnect.isPending || preview !== null);
  const result = check.job?.moved ?? null;
  const items = result?.items ?? [];
  const offered = items.filter((p) => !p.ambiguous);
  const ticks = useTicks(offered.map(keyOf));
  const chosen = offered.filter((p) => ticks.has(keyOf(p)));
  const body = (pairs: MovedPair[], dry_run: boolean) => ({ pairs: pairs.map((p) => ({ old: p.old_id, new: p.new_id })), dry_run });

  const showPreview = (pairs: MovedPair[]) => {
    if (reconnect.isPending || pairs.length === 0) return;
    reconnect
      .mutateAsync(body(pairs, true))
      .then((dry) => setPreview(dry.pairs))
      .catch((e) => toast({ kind: "error", text: `Not reconnected: ${visible(refusal(e))}` }));
  };
  const apply = (pairs: MovedPair[]) => {
    setPreview(null);
    reconnect
      .mutateAsync(body(pairs, false))
      .then((done) => {
        const undoId = done.undo_id;
        if (done.pairs.length > 0)
          toast({
            kind: "info",
            text: `Reconnected ${plural(done.pairs.length, "file")}`,
            action: undoId ? undoAction(() => undo(undoId)) : undefined,
          });
        if (done.errors.length > 0) toast({ kind: "error", text: visible(done.errors.join("; ")) });
        check.reload();
      })
      .catch((e) => toast({ kind: "error", text: `Not reconnected: ${visible(refusal(e))}` }));
  };

  const undo = (undoId: string) => {
    undoReconnect
      .mutateAsync(undoId)
      .then((back) => {
        if (back.pairs.length > 0) toast({ kind: "info", text: `Put ${plural(back.pairs.length, "file")} back as they were` });
        if (back.errors.length > 0) toast({ kind: "error", text: visible(back.errors.join("; ")) });
        check.reload();
      })
      .catch((e) => toast({ kind: "error", text: `Not undone: ${visible(refusal(e))}` }));
  };

  return (
    <CheckCard
      title="Moved outside dam"
      icon={<FileSearch />}
      kind="moved"
      intro="Files without a Drive id that were renamed or moved in Finder or Explorer. The app then sees a new file, and the tags, notes, collections and tray items stay with the old, missing one. A pair is listed when both have the same size and content. Reconnect gives the file back what it had; the files themselves are not touched."
      check={check}
      empty="No file was found that was moved outside dam and lost what it had."
      ignores="moved"
      found={result !== null && (items.length > 0 || result.unhashed > 0 || !result.complete)}
      summary={plural(result?.total ?? 0, "moved file")}
    >
      {result && (
        <>
          {items.length > 0 && (
            <>
              {offered.length > 0 ? (
                <ListHead count={plural(result.total, "moved file")} all={ticks.all} onAll={ticks.setAll} what="moved files" />
              ) : (
                <p>
                  <strong>{plural(result.total, "moved file")}</strong>
                </p>
              )}
              <ul className="check-list">
                {items.map((p) => {
                  const where = (
                    <span className="ref-entry">
                      <span>
                        <code>{visible(p.old_path)}</code> <span className="hint">is now</span> <code>{visible(p.new_path)}</code>
                      </span>
                      <span className="hint">
                        {formatSize(p.size)}.{" "}
                        {p.ambiguous
                          ? "Its content matches more than one file, so the app does not choose."
                          : `Moves ${movesText(p.moves)}.`}
                      </span>
                    </span>
                  );
                  return (
                    <li key={keyOf(p)}>
                      {p.ambiguous ? (
                        <span className="check">{where}</span>
                      ) : (
                        <label className="check">
                          <input type="checkbox" checked={ticks.has(keyOf(p))} onChange={() => ticks.toggle(keyOf(p))} />
                          {where}
                        </label>
                      )}
                      <span className="dup-actions">
                        {p.ambiguous && <Tag tone="orange">More than one match</Tag>}
                        {!p.same_ext && <Tag tone="grey">Extension changed</Tag>}
                        {!p.ambiguous && (
                          <button type="button" disabled={reconnect.isPending} onClick={() => showPreview([p])}>
                            Reconnect…
                          </button>
                        )}
                        <IgnoreButton
                          label={p.new_path}
                          disabled={ignore.busy}
                          onClick={() => void ignore.ignore({ kind: "moved", key: keyOf(p), label: `${p.old_path} → ${p.new_path}` })}
                        />
                        <ShowInBrowse to={browseTo(p.new_path, p.new_id)} />
                      </span>
                    </li>
                  );
                })}
              </ul>
              <Capped shown={items.length} total={result.total} />
              {offered.length > 0 && (
                <div className="check-actions">
                  <button type="button" disabled={chosen.length === 0 || reconnect.isPending} onClick={() => showPreview(chosen)}>
                    Reconnect {plural(chosen.length, "file")}…
                  </button>
                </div>
              )}
            </>
          )}
          {items.length === 0 && <p className="hint">No file was found that was moved outside dam and lost what it had.</p>}
          {result.unhashed > 0 && (
            <p className="hint">
              {plural(result.unhashed, "missing file")} with tags or other things {result.unhashed === 1 ? "was" : "were"} never read,
              so {result.unhashed === 1 ? "it" : "they"} cannot be compared.
            </p>
          )}
          {!result.complete && <p className="hint">The check was stopped before it read every file.</p>}
        </>
      )}
      {preview && (
        <Sheet
          open
          title={`Reconnect ${plural(preview.length, "file")}?`}
          onClose={() => setPreview(null)}
          footer={
            <>
              <button type="button" onClick={() => setPreview(null)}>
                Cancel
              </button>
              <button type="button" className="primary" disabled={reconnect.isPending} onClick={() => apply(preview)}>
                Reconnect
              </button>
            </>
          }
        >
          <ul className="check-list">
            {preview.map((p) => (
              <li key={keyOf(p)}>
                <span className="ref-entry">
                  <span>
                    <code>{visible(p.old_path)}</code> <span className="hint">is now</span> <code>{visible(p.new_path)}</code>
                  </span>
                  <span className="hint">Moves {movesText(p.moves)}.</span>
                </span>
              </li>
            ))}
          </ul>
          <p>
            This changes only the app&apos;s own records: the files stay where they are. It is not listed in Activity; Undo in
            the message afterwards puts it back.
          </p>
        </Sheet>
      )}
    </CheckCard>
  );
}
