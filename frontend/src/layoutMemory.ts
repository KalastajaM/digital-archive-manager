/** What this browser remembers about the layout, and the way to forget it all at once
 * (Settings → Appearance → Reset layout).
 *
 * Three kinds: the widths of the panes you dragged (every ``useSplitWidth`` key, one per
 * screen), the order and folds of Today's cards and whether Browse shows its folder tree
 * beside two panes. Each key is kept per archive (the
 * archive "main" under the plain key, the others under ``<key>.<archive id>``), so a reset
 * clears the plain key and every archive's copy. Every storage access is in try/catch:
 * private windows and blocked site data throw. A test keeps this list in step with the
 * ``useSplitWidth`` calls in the source. */

export const PANE_WIDTH_KEYS = [
  "dam.browse.panesplit",
  "dam.browse.treewidth",
  "dam.browse.inspectorwidth",
  "dam.inbox.listwidth",
  "dam.inbox.panelwidth",
  "dam.trays.listwidth",
  "dam.collection.inspectorwidth",
];
export const TODAY_LAYOUT_KEYS = ["dam.today.layout.v1"];
/** Browse with two panes: whether the folder tree is shown beside them (hidden until asked for). */
export const BROWSE_TREE_KEYS = ["dam.browse.treeshown"];

export type Remembered = Record<string, string>;

const isOurs = (name: string) =>
  [...PANE_WIDTH_KEYS, ...TODAY_LAYOUT_KEYS, ...BROWSE_TREE_KEYS].some((key) => name === key || name.startsWith(`${key}.`));

/** Forgets every remembered pane width and Today's card layout, for every archive.
 * Returns what was removed, so an Undo can put it back with ``restoreLayout``. */
export function forgetLayout(): Remembered {
  const removed: Remembered = {};
  try {
    const names: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const name = localStorage.key(i);
      if (name !== null && isOurs(name)) names.push(name);
    }
    for (const name of names) {
      const value = localStorage.getItem(name);
      if (value !== null) removed[name] = value;
      localStorage.removeItem(name);
    }
  } catch {
    // storage blocked: nothing was remembered, nothing to forget
  }
  return removed;
}

export function restoreLayout(saved: Remembered) {
  try {
    for (const [name, value] of Object.entries(saved)) if (isOurs(name)) localStorage.setItem(name, value);
  } catch {
    // storage blocked: the layout stays at its defaults
  }
}
