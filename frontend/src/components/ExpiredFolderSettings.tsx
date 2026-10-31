/** Settings → Archive folders: the name of the Expired folder, inside the folder of an
 * item, where a renewal moves the old file. */
import { useEffect, useState } from "react";
import { errorText, useExpiredFolder, useSetExpiredFolder } from "../api/client";
import { visible } from "../text";

export function ExpiredFolderSettings() {
  const current = useExpiredFolder();
  const save = useSetExpiredFolder();
  const saved = current.data?.name;
  const [name, setName] = useState("");
  useEffect(() => {
    if (saved !== undefined) setName(saved);
  }, [saved]);
  return (
    <section aria-label="Expired folder">
      <h3>Expired folder</h3>
      <p className="hint">When a renewal attaches a new file, the old one moves to this folder inside its own folder.</p>
      {current.isError && (
        <p className="error" role="alert">
          Could not load the name: {visible(errorText(current.error))}
        </p>
      )}
      <form
        className="field"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(name.trim());
        }}
      >
        <label htmlFor="expired-folder-name">Expired folder</label>
        <input
          id="expired-folder-name"
          type="text"
          value={name}
          autoComplete="off"
          spellCheck={false}
          disabled={saved === undefined}
          onChange={(e) => {
            setName(e.target.value);
            save.reset();
          }}
        />
        <div className="archive-forget-actions">
          <button type="submit" disabled={save.isPending || saved === undefined || name.trim() === "" || name.trim() === saved}>
            Save
          </button>
        </div>
      </form>
      {save.isError && (
        <p className="error" role="alert">
          {visible(errorText(save.error))}
        </p>
      )}
    </section>
  );
}
