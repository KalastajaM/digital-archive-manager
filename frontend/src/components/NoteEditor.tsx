import { useId, useRef } from "react";
import { useAutoGrow } from "./useAutoGrow";

/** The API's limit (``NOTE_MAX``); the textarea stops there. */
export const NOTE_MAX = 10_000;
const COUNT_FROM = NOTE_MAX - 1_000;

const grouped = (n: number) => String(n).replace(/\B(?=(\d{3})+$)/g, " ");

/** An optional note: one plain textarea, with a character count near the limit. */
export function NoteEditor({
  value,
  onChange,
  label = "Note (optional)",
  placeholder = "Add a note…",
}: {
  value: string;
  onChange: (text: string) => void;
  label?: string;
  placeholder?: string;
}) {
  const id = useId();
  const ref = useRef<HTMLTextAreaElement>(null);
  useAutoGrow(ref, value);
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea
        id={id}
        ref={ref}
        className="note-editor"
        rows={2}
        maxLength={NOTE_MAX}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {value.length >= COUNT_FROM && (
        <p className="hint">
          {grouped(value.length)} / {grouped(NOTE_MAX)}
        </p>
      )}
    </div>
  );
}
