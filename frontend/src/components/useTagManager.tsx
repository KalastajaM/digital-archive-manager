/** Managing tags (rename, merge, pin, group, delete; new tags and groups), each with its
 * sheet and an Undo in the toast: one place for the Tags screen and Browse's tag tree. */
import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { errorText, type TagGroup, type TagInfo, type TagMergePlan, type TagUndo, useTagActions } from "../api/client";
import { plural } from "../format";
import { visible } from "../text";
import { undoAction, useToast } from "./Toasts";
import { type MenuEntry } from "./ui/Menu";
import { Sheet } from "./ui/Sheet";

const byName = (a: TagInfo, b: TagInfo) => a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true });
const same = (a: string, b: string) => a.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase() === b.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

export type Sheetful =
  | { kind: "create" }
  | { kind: "group" }
  | { kind: "rename-group"; group: TagGroup }
  | { kind: "rename"; tag: TagInfo }
  | { kind: "merge"; sources: string[]; into?: string }
  | { kind: "delete"; tag: TagInfo };

/** A sheet with one name field (a new tag or group, a new name). */
function NameSheet({
  title,
  label,
  initial = "",
  submit,
  onClose,
  clash,
}: {
  title: string;
  label: string;
  initial?: string;
  /** Does the change; throws to show the message. */
  submit: (name: string) => Promise<void>;
  onClose: () => void;
  /** Another tag the name matches: the sheet offers to merge into it instead. */
  clash?: (name: string) => { name: string; merge: () => void } | null;
}) {
  const [name, setName] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const trimmed = name.trim();
  const other = clash?.(trimmed) ?? null;
  const go = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!trimmed || trimmed === initial || other || busy) return;
    setBusy(true);
    setError(null);
    try {
      await submit(trimmed);
      onClose();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  };
  return (
    <Sheet
      open
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          {other ? (
            <button type="button" className="primary" onClick={other.merge}>
              Merge instead
            </button>
          ) : (
            <button type="button" className="primary" disabled={!trimmed || trimmed === initial || busy} onClick={() => void go()}>
              {initial ? "Rename" : "Create"}
            </button>
          )}
        </>
      }
    >
      <form onSubmit={(e) => void go(e)}>
        <label className="field">
          <span>{label}</span>
          <input value={name} onChange={(e) => setName(e.target.value)} spellCheck={false} autoFocus />
        </label>
      </form>
      {other && (
        <p className="notice">
          A tag called {visible(other.name)} already exists. Merge {visible(initial)} into it instead: its files get{" "}
          {visible(other.name)} and {visible(initial)} is removed.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </Sheet>
  );
}

/** Merge ``sources`` into another tag: pick the tag to keep, see what happens, confirm. */
function MergeSheet({
  sources,
  into: first,
  tags,
  preview,
  merge,
  onClose,
}: {
  sources: string[];
  into?: string;
  tags: TagInfo[];
  preview: (sources: string[], into: string) => Promise<TagMergePlan>;
  merge: (sources: string[], into: string) => Promise<void>;
  onClose: () => void;
}) {
  const choices = tags.filter((t) => !sources.includes(t.name)).sort(byName);
  const [into, setInto] = useState(first ?? "");
  const [plan, setPlan] = useState<{ into: string; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!into) return;
    let current = true;
    setError(null);
    preview(sources, into)
      .then((p) => current && setPlan({ into, text: p.message }))
      .catch((e) => current && setError(errorText(e)));
    return () => {
      current = false;
    };
    // the preview follows the chosen tag only
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sources is fixed while the sheet is open; preview is a new function each render
  }, [into]);
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      await merge(sources, into);
      onClose();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };
  const names = sources.map((s) => visible(s)).join(", ");
  return (
    <Sheet
      open
      title={`Merge ${names}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={!into || plan?.into !== into || busy} onClick={() => void go()}>
            Merge
          </button>
        </>
      }
    >
      <label className="field">
        <span>Into</span>
        <select value={into} onChange={(e) => setInto(e.target.value)}>
          <option value="">Choose a tag</option>
          {choices.map((t) => (
            <option key={t.name} value={t.name}>
              {visible(t.name)} ({t.files})
            </option>
          ))}
        </select>
      </label>
      {plan?.into === into && into && <p>{visible(plan.text)}.</p>}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </Sheet>
  );
}

function DeleteSheet({ tag, remove, onClose }: { tag: TagInfo; remove: () => Promise<void>; onClose: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await remove();
      onClose();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };
  return (
    <Sheet
      open
      title={`Delete ${visible(tag.name)}?`}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={busy} onClick={() => void go()}>
            Delete tag
          </button>
        </>
      }
    >
      <p>
        {tag.files === 0
          ? `${visible(tag.name)} is on no files.`
          : `${visible(tag.name)} is removed from ${plural(tag.files, "file")}.`}{" "}
        The files themselves are not touched, and you can undo this right after.
      </p>
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </Sheet>
  );
}

/** The sheets and actions for ``tags`` (the list shown, for name clashes and merges).
 * ``onMerged``: after a merge (the Tags screen clears its ticks). */
export function useTagManager(tags: TagInfo[], onMerged?: () => void) {
  const actions = useTagActions();
  const toast = useToast();
  const [sheet, setSheet] = useState<Sheetful | null>(null);
  const revert = async (undo: TagUndo) => {
    try {
      await actions.undo(undo);
      toast({ kind: "info", text: "Undone" });
    } catch (e) {
      toast({ kind: "error", text: `Could not undo: ${errorText(e)}` });
    }
  };
  /** Runs a change; its toast says what happened and offers Undo. */
  const change = async (call: () => Promise<{ message: string; undo: TagUndo | null }>) => {
    try {
      const done = await call();
      const undo = done.undo;
      toast({
        kind: "info",
        text: done.message,
        action: undo ? undoAction(() => void revert(undo)) : undefined,
      });
    } catch (e) {
      toast({ kind: "error", text: errorText(e) });
    }
  };

  const removeGroup = async (g: TagGroup) => {
    try {
      const gone = await actions.deleteGroup(g.id);
      toast({
        kind: "info",
        text: `${gone.message}; its tags stay, ungrouped`,
        action: undoAction(
          () => void actions.restoreGroup(gone.name, gone.members).catch((e) => toast({ kind: "error", text: errorText(e) })),
        ),
      });
    } catch (e) {
      toast({ kind: "error", text: errorText(e) });
    }
  };
  const move = (names: string[], groupId: number | null) => change(() => actions.setGroup(names, groupId));
  const clash = (tag: TagInfo) => (name: string) => {
    const other = tags.find((t) => t.name !== tag.name && same(t.name, name));
    return other ? { name: other.name, merge: () => setSheet({ kind: "merge", sources: [tag.name], into: other.name }) } : null;
  };
  const rename = (tag: TagInfo): MenuEntry => ({ label: "Rename…", onSelect: () => setSheet({ kind: "rename", tag }) });
  const mergeInto = (tag: TagInfo): MenuEntry => ({ label: "Merge into…", onSelect: () => setSheet({ kind: "merge", sources: [tag.name] }) });
  const pin = (tag: TagInfo): MenuEntry => ({
    label: tag.pinned ? "Unpin from the sidebar" : "Pin to the sidebar",
    onSelect: () => void change(() => actions.pin([tag.name], !tag.pinned)),
  });
  const remove = (tag: TagInfo): MenuEntry => ({ label: "Delete…", onSelect: () => setSheet({ kind: "delete", tag }) });
  /** A tag's menu: Rename, Merge into, Pin, the groups, Delete. */
  const menuFor = (tag: TagInfo, groups: TagGroup[]): MenuEntry[] => [
    rename(tag),
    mergeInto(tag),
    pin(tag),
    "separator",
    ...groups
      .filter((g) => g.id !== tag.group_id)
      .map((g): MenuEntry => ({ label: `Move to ${visible(g.name)}`, onSelect: () => void move([tag.name], g.id) })),
    ...(tag.group_id !== null ? [{ label: "Move out of the group", onSelect: () => void move([tag.name], null) } as MenuEntry] : []),
    "separator",
    remove(tag),
  ];
  /** A tag's menu where its group is not shown (the sidebar): Rename, Merge into, Pin, Delete. */
  const shortMenu = (tag: TagInfo): MenuEntry[] => [rename(tag), mergeInto(tag), pin(tag), "separator", remove(tag)];
  /** A group's menu: Rename group, Delete group. */
  const groupMenu = (g: TagGroup): MenuEntry[] => [
    { label: "Rename group…", onSelect: () => setSheet({ kind: "rename-group", group: g }) },
    { label: "Delete group", onSelect: () => void removeGroup(g) },
  ];
  const view: ReactNode = (
    <>
      {sheet?.kind === "create" && (
        <NameSheet
          title="New tag"
          label="Name"
          onClose={() => setSheet(null)}
          submit={async (name) => {
            const done = await actions.create(name);
            toast({ kind: "info", text: done.message, action: undoAction(() => void revert(done.undo)) });
          }}
        />
      )}
      {sheet?.kind === "group" && (
        <NameSheet
          title="New group"
          label="Name"
          onClose={() => setSheet(null)}
          submit={async (name) => {
            const g = await actions.createGroup(name);
            toast({
              kind: "info",
              text: `Created the group '${g.name}'`,
              action: undoAction(() => void actions.deleteGroup(g.id).catch((e) => toast({ kind: "error", text: errorText(e) }))),
            });
          }}
        />
      )}
      {sheet?.kind === "rename-group" && (
        <NameSheet
          title={`Rename ${visible(sheet.group.name)}`}
          label="Name"
          initial={sheet.group.name}
          onClose={() => setSheet(null)}
          submit={async (name) => {
            const g = sheet.group;
            const done = await actions.renameGroup(g.id, name);
            toast({
              kind: "info",
              text: `Renamed the group to '${done.name}'`,
              action: undoAction(() => void actions.renameGroup(g.id, g.name).catch((e) => toast({ kind: "error", text: errorText(e) }))),
            });
          }}
        />
      )}
      {sheet?.kind === "rename" && (
        <NameSheet
          title={`Rename ${visible(sheet.tag.name)}`}
          label="New name"
          initial={sheet.tag.name}
          clash={clash(sheet.tag)}
          onClose={() => setSheet(null)}
          submit={async (name) => {
            const done = await actions.rename(sheet.tag.name, name);
            toast({ kind: "info", text: done.message, action: undoAction(() => void revert(done.undo)) });
          }}
        />
      )}
      {sheet?.kind === "merge" && (
        <MergeSheet
          sources={sheet.sources}
          into={sheet.into}
          tags={tags}
          preview={actions.previewMerge}
          merge={async (sources, into) => {
            const done = await actions.merge(sources, into);
            const undo = done.undo;
            toast({
              kind: "info",
              text: `Merged: ${done.message}`,
              action: undo ? undoAction(() => void revert(undo)) : undefined,
            });
            onMerged?.();
          }}
          onClose={() => setSheet(null)}
        />
      )}
      {sheet?.kind === "delete" && (
        <DeleteSheet
          tag={sheet.tag}
          remove={async () => {
            const done = await actions.remove(sheet.tag.name);
            toast({ kind: "info", text: done.message, action: undoAction(() => void revert(done.undo)) });
          }}
          onClose={() => setSheet(null)}
        />
      )}
    </>
  );
  return { open: setSheet, change, move, menuFor, shortMenu, groupMenu, view };
}
