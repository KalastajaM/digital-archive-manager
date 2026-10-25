/** A note saved on blur (auto-save), and the "Saving…/Saved/error" line that edited
 * values show. Shared by the item, collection and file panels. */
import { errorText, type NoteKind, useNote, useSetNote } from "../api/client";
import { visible } from "../text";
import { Collapsible, firstLine } from "./Collapsible";
import { NoteEditor } from "./NoteEditor";
import { type SaveStatus, useAutoSave } from "./useAutoSave";

export function SaveState({ status }: { status: SaveStatus }) {
  if (status === null) return null;
  if (status.kind === "error") {
    return (
      <p className="error" role="alert">
        {visible(status.text)}
      </p>
    );
  }
  return (
    <span className="save-state" role="status">
      {status.kind === "saving" ? "Saving…" : "Saved"}
    </span>
  );
}

/** The note of a file, collection or item: edited in a NoteEditor, saved on blur
 * (``PUT /api/notes/<kind>/<target>``; blank text removes it). */
export function SavedNote({ kind, target, label }: { kind: NoteKind; target: string; label?: string }) {
  const note = useNote(kind, target);
  const setNote = useSetNote();
  const save = async (text: string) => (await setNote.mutateAsync({ kind, target, text })).text;
  const auto = useAutoSave(note.data?.text ?? "", save);
  if (note.isError) {
    return (
      <p className="error" role="alert">
        Could not load the note. {visible(errorText(note.error))}
      </p>
    );
  }
  return (
    <Collapsible name="notes" title="Notes" className="item-note" hint={firstLine(auto.shown) || "No note yet"}>
      <div onBlur={() => void auto.commit()}>
        <NoteEditor value={auto.shown} onChange={auto.change} label={label} />
        <SaveState status={auto.status} />
      </div>
    </Collapsible>
  );
}
