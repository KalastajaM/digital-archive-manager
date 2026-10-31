import { type InputHTMLAttributes, useState } from "react";
import { chooseFolder, errorText } from "../api/client";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "onChange"> & {
  value: string;
  onChange: (path: string) => void;
};

/** A typed folder path with a "Choose…" button that opens the operating system's folder
 * dialog (shown by the local server, because a browser cannot give a page an absolute
 * path). Typing keeps working; when no dialog can be shown a plain message says so. The
 * dialog never creates or changes anything. */
export function FolderPathInput({ value, onChange, disabled, ...input }: Props) {
  const [choosing, setChoosing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const choose = async () => {
    setChoosing(true);
    setMessage(null);
    try {
      const answer = await chooseFolder(value.trim() || undefined);
      if (answer.path) onChange(answer.path);
      else if (answer.unavailable) setMessage(answer.unavailable);
    } catch (e) {
      setMessage(`${errorText(e)} Type the path instead.`);
    } finally {
      setChoosing(false);
    }
  };

  return (
    <>
      <div className="path-row">
        <input {...input} type="text" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
        <button type="button" className="path-choose" disabled={disabled || choosing} onClick={() => void choose()}>
          {choosing ? "Choosing…" : "Choose…"}
        </button>
      </div>
      {message && (
        <p className="first-run-hint path-message" aria-live="polite">
          {message}
        </p>
      )}
    </>
  );
}
