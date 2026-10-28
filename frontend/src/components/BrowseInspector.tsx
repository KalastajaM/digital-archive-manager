/** What Browse's details panel (the New look) holds besides a file's own panel: the list of
 * actions with their keys, and, for several selected files, the summary on top of it. The
 * screen decides what each action does (it hands over the same functions the old header's
 * buttons run); this only draws them. */
import type { ReactElement } from "react";
import { Link } from "react-router-dom";
import { useCollectionsWithMarked } from "../api/client";
import { formatSize } from "../format";
import { parentOf } from "../paths";
import { visible } from "../text";
import { Menu, type MenuEntry } from "./ui/Menu";

type Common = {
  label: string;
  /** Off now; ``reason`` is the tooltip then. */
  disabled?: boolean;
  reason?: string | null;
  /** A thin rule above the action: a new group. */
  rule?: boolean;
};

/** A button (``keys``: the shortcut it also has), or a pull-down (``menu``). */
export type InspectorAction =
  | (Common & { run: () => void; keys?: string; danger?: boolean; pressed?: boolean })
  | (Common & { menu: MenuEntry[] });

function Action({ action }: { action: InspectorAction }) {
  const off = action.disabled === true || !!action.reason;
  const wrap = (node: ReactElement) =>
    off && action.reason ? (
      <span className="inspector-action-tip" data-tip={action.reason}>
        {node}
      </span>
    ) : (
      node
    );
  if ("menu" in action) {
    return off ? (
      wrap(
        <button type="button" className="inspector-action" disabled>
          <span className="inspector-action-label">{action.label}</span>
        </button>,
      )
    ) : (
      <Menu label={action.label} text={action.label} icon={null} entries={action.menu} triggerClassName="inspector-action" className="inspector-action-menu" />
    );
  }
  return wrap(
    <button
      type="button"
      className={action.danger ? "inspector-action is-danger" : "inspector-action"}
      aria-pressed={action.pressed}
      disabled={off}
      onClick={action.run}
    >
      <span className="inspector-action-label">{action.label}</span>
      {action.keys && <kbd className="inspector-action-keys">{action.keys}</kbd>}
    </button>,
  );
}

export function InspectorActions({ actions }: { actions: InspectorAction[] }) {
  return (
    <ul className="inspector-actions" aria-label="Actions">
      {actions.map((a) => (
        <li key={a.label} className={a.rule ? "has-rule" : undefined}>
          <Action action={a} />
        </li>
      ))}
    </ul>
  );
}

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
                <Link to={`/collections/${c.id}`}>{visible(c.name)}</Link> ({n} of {files.length})
              </span>
            ))}
          </dd>
        </dl>
      )}
    </div>
  );
}
