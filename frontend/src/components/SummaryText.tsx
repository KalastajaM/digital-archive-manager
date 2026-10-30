/** A summary that is edited where it stands (New look; a file's and a collection's): the
 * text is a button that turns into a field on a click, and the field saves when it loses
 * focus. Esc puts the text back. An empty summary shows a placeholder to click into. The
 * button's name is the text itself, so a screen reader reads the summary.
 * Read-only: the text is plain, and ``readOnly`` says why. */
import { useId, useRef, useState } from "react";
import { errorText } from "../api/client";
import { visible } from "../text";
import { useAutoGrow } from "./useAutoGrow";

export function SummaryText({
  value,
  onSave,
  allowEmpty = false,
  maxLength,
  placeholder = "Add a summary…",
  readOnly = null,
}: {
  value: string;
  /** Saves the text; a rejection keeps the field open with the error under it. */
  onSave: (text: string) => Promise<unknown>;
  /** An emptied field saves (a collection's summary can be cleared); else it puts the text back. */
  allowEmpty?: boolean;
  maxLength: number;
  placeholder?: string;
  readOnly?: string | null;
}) {
  const id = useId();
  const ref = useRef<HTMLTextAreaElement>(null);
  const [draft, setDraft] = useState<string | null>(null);
  // what was saved, shown until the new value comes back from the server
  const [saved, setSaved] = useState<{ text: string; over: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false);
  useAutoGrow(ref, draft ?? "");
  const shown = saved && saved.over === value ? saved.text : value;

  const finish = async () => {
    if (draft === null || busy.current) return;
    const text = draft.trim();
    if (text === shown.trim() || (!text && !allowEmpty)) {
      setDraft(null);
      setError(null);
      return;
    }
    busy.current = true;
    try {
      await onSave(text);
      setSaved({ text, over: value });
      setDraft(null);
      setError(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      busy.current = false;
    }
  };

  if (draft !== null) {
    return (
      <div className="summary-text-edit">
        <label htmlFor={id} className="visually-hidden">
          Summary
        </label>
        <textarea
          id={id}
          ref={ref}
          rows={3}
          maxLength={maxLength}
          placeholder={placeholder}
          value={draft}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void finish()}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              setDraft(null);
              setError(null);
            }
          }}
        />
        {error && (
          <p className="error" role="alert">
            {visible(error)}
          </p>
        )}
      </div>
    );
  }
  const empty = shown.trim() === "";
  if (readOnly !== null) {
    return (
      <p className={empty ? "summary-text is-empty" : "summary-text"} data-tip={readOnly}>
        {empty ? "No summary yet." : visible(shown)}
      </p>
    );
  }
  return (
    <button
      type="button"
      className={empty ? "click-edit summary-text is-empty" : "click-edit summary-text"}
      title="Click to edit"
      onClick={() => setDraft(shown)}
    >
      {empty ? placeholder : visible(shown)}
    </button>
  );
}
