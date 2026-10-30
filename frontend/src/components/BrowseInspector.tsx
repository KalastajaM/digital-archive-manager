/** What Browse's details panel (the New look) holds besides a file's own panel: the hint under
 * it and, for several selected files, the summary (the icon rows under it are
 * ``FileActionIcons``). */
import { Link } from "react-router-dom";
import { useCollectionsWithMarked } from "../api/client";
import { formatSize } from "../format";
import { parentOf } from "../paths";
import { visible } from "../text";
import { collectionHref } from "../collectionHref";

/** The one-line hint under the panel: what a drop does. */
export function InspectorHint() {
  return (
    <p className="inspector-hint">
      Drag files or a folder to the other pane, a folder in the tree, or a collection in the sidebar. Every drop is shown first and can be undone.
    </p>
  );
}

type Picked = { drive_id: string; path: string; size?: number | null };

/** Several files selected: a stack for a picture, how many and how big, where they are, and the
 * collections some or all of them are in (read from the collections the screen has loaded). */
export function SelectionSummary({ files }: { files: Picked[] }) {
  const collections = useCollectionsWithMarked();
  const sizes = files.map((f) => f.size);
  const known = sizes.every((s): s is number => typeof s === "number");
  const folders = new Set(files.map((f) => parentOf(f.path)));
  const place =
    folders.size === 1 ? `all in ${visible([...folders][0]) || "Archive"}` : `in ${folders.size} folders`;
  const ids = new Set(files.map((f) => f.drive_id));
  const shared = (collections.data ?? [])
    .filter((c) => c.kind == null && c.state === "open")
    .map((c) => ({ c, n: c.members.filter((m) => ids.has(m.drive_id)).length }))
    .filter((x) => x.n > 0);
  return (
    <div className="inspector-selection">
      <div className="inspector-stack" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <div className="inspector-selection-head">
        <h2>{files.length} files selected</h2>
        <p>{known ? `${formatSize(sizes.reduce((a, b) => a + b, 0))}, ${place}` : place[0].toUpperCase() + place.slice(1)}</p>
      </div>
      {shared.length > 0 && (
        <dl className="inspector-facts">
          <dt>Collections</dt>
          <dd>
            {shared.map(({ c, n }, i) => (
              <span key={c.id}>
                {i > 0 && ", "}
                <Link to={collectionHref(c)}>{visible(c.name)}</Link> ({n} of {files.length})
              </span>
            ))}
          </dd>
        </dl>
      )}
    </div>
  );
}
