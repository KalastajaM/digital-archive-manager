/** Merge into…: a collection goes into another. Its files and the collections inside it join
 * that one, its note, checklist and summary are added to that one's, and it goes. There is
 * no Undo: a snapshot is taken first, and the sheet says so before anything happens. */
import { useState } from "react";
import { type CollectionRow, errorText, useMergeCollection } from "../api/client";
import { visible } from "../text";
import { childrenOf } from "./collectionTree";
import { Sheet } from "./ui/Sheet";

export function MergeCollectionSheet({
  c,
  all,
  onDone,
  onCancel,
}: {
  c: { id: number; name: string };
  all: CollectionRow[];
  /** After the merge: the collection it went into. */
  onDone: (into: { id: number; name: string }) => void;
  onCancel: () => void;
}) {
  const { merge, check } = useMergeCollection();
  const [into, setInto] = useState<CollectionRow | null>(null);
  const [problems, setProblems] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // the open ordinary collections, not this one nor any inside it (that would be a cycle)
  const kids = childrenOf(all);
  const inside = new Set<number>();
  const walk = (id: number) => (kids.get(id) ?? []).forEach((k) => (inside.add(k.id), walk(k.id)));
  walk(c.id);
  const targets = all.filter((x) => !x.kind && x.state === "open" && x.id !== c.id && !inside.has(x.id));

  const choose = (x: CollectionRow) => {
    setInto(x);
    setProblems(null);
    setError(null);
    check(c.id, x.id).then(setProblems, (e) => setError(errorText(e)));
  };
  const go = async () => {
    if (!into) return;
    try {
      await merge.mutateAsync({ id: c.id, into: into.id });
      onDone(into);
    } catch (e) {
      setError(errorText(e));
    }
  };
  const name = visible(c.name);
  return (
    <Sheet
      open
      title={`Merge ${name} into…`}
      onClose={onCancel}
      onKeyDown={(e) => e.stopPropagation()}
      footer={
        <>
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          {into && problems && problems.length === 0 && (
            <button type="button" className="primary danger" disabled={merge.isPending} onClick={() => void go()}>
              Merge
            </button>
          )}
        </>
      }
    >
      <ul role="listbox" aria-label="Collections to merge into" className="pick-list">
        {targets.map((x) => (
          <li key={x.id}>
            <button type="button" role="option" aria-selected={into?.id === x.id} title={visible(x.name)} onClick={() => choose(x)}>
              {visible(x.name)}
            </button>
          </li>
        ))}
        {targets.length === 0 && <li className="hint">No other open collection to merge into.</li>}
      </ul>
      {into && problems && problems.length > 0 && (
        <p className="error" role="alert">
          {problems.map(visible).join(" ")}
        </p>
      )}
      {into && problems && problems.length === 0 && (
        <div className="merge-explain">
          <p>
            {name} goes into <b>{visible(into.name)}</b>: its files and the collections inside it join {visible(into.name)}, its note,
            checklist and summary are added to {visible(into.name)}&apos;s, and {name} is removed. Your files stay where they are; in
            ##. Ongoing its links move into {visible(into.name)}&apos;s folder.
          </p>
          <p>
            <b>This cannot be undone.</b> A snapshot is taken first (Settings, Snapshots), so restoring it is the way back.
          </p>
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </Sheet>
  );
}
