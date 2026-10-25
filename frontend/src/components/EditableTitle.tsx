/** A heading edited in place: click it (it is a button, so the keyboard reaches it too).
 * Enter or leaving the field saves, Esc
 * cancels, an empty title is refused with the message the server gives for it. The save
 * is the caller's (``save`` returns the stored title); "Saving…/Saved" shows beside it. */
import { useEffect, useRef, useState } from "react";
import { visible } from "../text";
import { SaveState } from "./SavedNote";
import { ClickToEdit } from "./ui/ClickToEdit";
import { useAutoSave } from "./useAutoSave";

export const BLANK_TITLE = "A title must not be blank";

export function EditableTitle({
  value,
  save,
  headingId,
}: {
  value: string;
  save: (title: string) => Promise<string>;
  headingId?: string;
}) {
  const auto = useAutoSave(value, save);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const finished = useRef(false); // Enter or Esc happened: the blur that follows does nothing
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) input.current?.select();
  }, [editing]);

  const start = () => {
    finished.current = false;
    setDraft(auto.shown);
    setProblem(null);
    setEditing(true);
  };
  const cancel = () => {
    finished.current = true;
    setProblem(null);
    setEditing(false);
  };
  const submit = () => {
    const title = draft.trim();
    if (!title) {
      setProblem(BLANK_TITLE); // stays open: nothing is sent
      return;
    }
    finished.current = true;
    setProblem(null);
    setEditing(false);
    if (title !== auto.shown) auto.change(title);
    void auto.commit(title);
  };

  if (editing) {
    return (
      <div className="editable-title editing">
        <input
          ref={input}
          className="editable-title-input"
          aria-label="Title"
          value={draft}
          autoFocus
          spellCheck={false}
          aria-invalid={problem !== null}
          onChange={(e) => {
            setDraft(e.target.value);
            setProblem(null);
          }}
          onBlur={() => {
            if (!finished.current) submit();
          }}
          onKeyDown={(e) => {
            e.stopPropagation(); // page shortcuts never see keys typed here
            if (e.key === "Enter") {
              e.preventDefault();
              submit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              cancel();
            }
          }}
        />
        {problem && (
          <p className="error" role="alert">
            {problem}
          </p>
        )}
      </div>
    );
  }
  return (
    <div className="editable-title">
      <h2 id={headingId} className="editable-title-text" aria-label={visible(auto.shown)}>
        <ClickToEdit label="Edit title" tip="Click to edit the title" onClick={start}>
          {visible(auto.shown)}
        </ClickToEdit>
      </h2>
      <SaveState status={auto.status} />
    </div>
  );
}
