/** Settings → Archive folders: the name of the subfolder older versions of a file move to,
 * inside the file's own folder. */
import { useEffect, useState } from "react";
import { errorText, useVersionsFolder, useSetVersionsFolder } from "../api/client";
import { visible } from "../text";

export function VersionsFolderSettings() {
  const current = useVersionsFolder();
  const save = useSetVersionsFolder();
  const saved = current.data?.name;
  const [name, setName] = useState("");
  useEffect(() => {
    if (saved !== undefined) setName(saved);
  }, [saved]);
  return (
    <section aria-labelledby="versions-folder-heading">
      <h3 id="versions-folder-heading">Older versions folder</h3>
      <p className="hint">Older versions of a file move to this folder inside the file's own folder, when you ask. Changing the name moves nothing: a folder under the old name stays, and its files no longer count as versions.</p>
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
        <label htmlFor="versions-folder-name">Folder name</label>
        <input
          id="versions-folder-name"
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
      {save.isSuccess && (
        <p className="hint" role="status">
          Saved
        </p>
      )}
      {save.isError && (
        <p className="error" role="alert">
          {visible(errorText(save.error))}
        </p>
      )}
    </section>
  );
}
