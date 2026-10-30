/** Naming a new collection, inside another one or at the top (the collection's ⋯ menu,
 * Browse's collection tree). */
import { useId, useRef, useState } from "react";
import { errorText, useCreateCollection } from "../api/client";
import { visible } from "../text";
import { COLLECTION_NAME_MAX } from "./CollectionPicker";
import { Sheet } from "./ui/Sheet";

export function NewCollectionSheet({
  parent,
  onCreated,
  onCancel,
}: {
  /** Where it goes; null: at the top. */
  parent: { id: number; name: string } | null;
  onCreated: (child: { id: number; name: string }) => void;
  onCancel: () => void;
}) {
  const ids = useId();
  const create = useCreateCollection();
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const inFlight = useRef(false); // Enter and a click (or two clicks) create one collection
  const submit = async () => {
    const name = text.trim();
    if (!name || inFlight.current) return;
    inFlight.current = true;
    setProblem(null);
    try {
      onCreated(await create.mutateAsync(parent ? { name, parent_id: parent.id } : name));
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      inFlight.current = false;
    }
  };
  return (
    <Sheet
      open
      title={parent ? `New collection inside ${visible(parent.name)}` : "New collection"}
      onClose={onCancel}
      onKeyDown={(e) => e.stopPropagation()}
      footer={
        <>
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" form={`${ids}-form`} className="primary" disabled={!text.trim() || create.isPending}>
            Create
          </button>
        </>
      }
    >
      <form
        id={`${ids}-form`}
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="field">
          <label htmlFor={`${ids}-name`}>Name</label>
          <input
            id={`${ids}-name`}
            value={text}
            autoFocus
            maxLength={COLLECTION_NAME_MAX}
            spellCheck={false}
            placeholder="e.g. Stove"
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        {problem && (
          <p className="error" role="alert">
            {visible(problem)}
          </p>
        )}
      </form>
    </Sheet>
  );
}
