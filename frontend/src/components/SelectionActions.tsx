/** What several selected files in Browse can have done to them at once: a tag put on or
 * taken off, added to, removed from or moved between collections. Each is one step with
 * Undo in its toast. Splitting a tag or a collection is these steps on a selection. */
import { EllipsisVertical } from "lucide-react";
import { type KeyboardEvent, useId, useMemo, useState } from "react";
import { apiPost, type CollectionRow, errorText, useAllTags, useCollectionMembers, useCreateCollection, useTagActions } from "../api/client";
import { childrenOf } from "./collectionTree";
import { visible } from "../text";
import { undoAction, useToast } from "./Toasts";
import { Menu, type MenuEntry } from "./ui/Menu";
import { Sheet } from "./ui/Sheet";

type File = { drive_id: string; name: string };
type Sheetful = "add-tag" | "remove-tag" | "add" | "remove" | "move";

/** A name as names are compared (case and accents ignored). */
const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").trim().toLowerCase();

/** A sheet that picks one name from ``options``, or (``allowNew``) a new one typed. */
function PickSheet({
  title,
  options,
  allowNew,
  refuse,
  hint,
  onPick,
  onClose,
}: {
  title: string;
  options: string[] | null;
  allowNew?: boolean;
  /** Why a typed name cannot be made new (a closed collection's), or null. */
  refuse?: (typed: string) => string | null;
  hint?: string;
  onPick: (name: string, isNew: boolean) => void;
  onClose: () => void;
}) {
  const ids = useId();
  const [typed, setTyped] = useState("");
  const shown = (options ?? []).filter((o) => fold(o).includes(fold(typed)));
  const exact = (options ?? []).find((o) => fold(o) === fold(typed));
  const refused = allowNew && typed.trim() && !exact ? (refuse?.(typed.trim()) ?? null) : null;
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter" || !typed.trim()) return;
    e.preventDefault();
    if (exact) onPick(exact, false);
    else if (allowNew && !refused) onPick(typed.trim(), true);
  };
  return (
    <Sheet open title={title} onClose={onClose} onKeyDown={(e) => e.stopPropagation()}>
      {hint && <p className="hint">{hint}</p>}
      <input
        role="combobox"
        aria-expanded="true"
        aria-controls={`${ids}-list`}
        aria-label={allowNew ? "Name, or a new one" : "Name"}
        className="pick-filter"
        value={typed}
        autoFocus
        spellCheck={false}
        placeholder={allowNew ? "Type a name, or pick one" : "Filter"}
        onChange={(e) => setTyped(e.target.value)}
        onKeyDown={onKeyDown}
      />
      {options === null ? (
        <p className="placeholder">Loading…</p>
      ) : (
        <ul id={`${ids}-list`} role="listbox" aria-label={title} className="pick-list">
          {shown.map((o) => (
            <li key={o}>
              <button type="button" role="option" aria-selected="false" title={visible(o)} onClick={() => onPick(o, false)}>
                {visible(o)}
              </button>
            </li>
          ))}
          {refused && <li className="hint">{visible(refused)}</li>}
          {allowNew && typed.trim() && !exact && !refused && (
            <li>
              <button type="button" role="option" aria-selected="false" onClick={() => onPick(typed.trim(), true)}>
                New: {visible(typed.trim())}
              </button>
            </li>
          )}
          {shown.length === 0 && !(allowNew && typed.trim()) && <li className="hint">Nothing to choose</li>}
        </ul>
      )}
    </Sheet>
  );
}

type Props = {
  files: File[];
  /** The collection Browse shows (its search), if any: Remove and Move act within its tree. */
  scope: CollectionRow | null;
  all: CollectionRow[];
  onDone: () => void;
};

/** The selection bar's pull-down: the actions and their sheets. */
export function SelectionActions(props: Props) {
  const { files } = props;
  const actions = useSelectionActions(props);
  return (
    <>
      <Menu
        label={`Actions for ${files.length === 1 ? visible(files[0].name) : `${files.length} selected files`}`}
        icon={<EllipsisVertical />}
        text="Selected"
        entries={actions.entries}
      />
      {actions.view}
    </>
  );
}

/** The actions on ``files`` (``entries``) and their sheets (render ``view``); ``open``
 * starts one from elsewhere (Browse's right-click menu: Add tag…, Add to collection…). */
export function useSelectionActions({ files, scope: shown, all, onDone }: Props) {
  // Starred and Important are marks, set with the star and the !: shown, they act as no collection
  const scope = shown && !shown.kind ? shown : null;
  const ids = files.map((f) => f.drive_id);
  const what = files.length === 1 ? visible(files[0].name) : `${files.length} files`;
  const tags = useAllTags();
  const tagActions = useTagActions();
  const members = useCollectionMembers();
  const create = useCreateCollection();
  const toast = useToast();
  const [sheet, setSheet] = useState<Sheetful | null>(null);
  const [carried, setCarried] = useState<string[] | null>(null);

  const ordinary = useMemo(() => all.filter((c) => !c.kind), [all]);
  const open = ordinary.filter((c) => c.state === "open");
  const byName = (name: string) => ordinary.find((c) => fold(c.name) === fold(name));
  /** A typed name that is a closed collection's: it cannot be made again, nor used. */
  const closedName = (name: string) => {
    const c = byName(name);
    return c && c.state === "closed" ? `${c.name} is closed: reopen it first` : null;
  };
  /** Within the shown tree: each file's own collection (the scope, or the child it is in). */
  const homeOf = useMemo(() => {
    if (!scope) return null;
    const kids = childrenOf(all);
    const tree: CollectionRow[] = [];
    const walk = (c: CollectionRow) => {
      tree.push(c);
      (kids.get(c.id) ?? []).forEach(walk);
    };
    walk(scope);
    return (id: string) => tree.find((c) => c.members.some((m) => m.drive_id === id)) ?? null;
  }, [scope, all]);

  const close = () => setSheet(null);
  const fail = (e: unknown) => toast({ kind: "error", text: visible(errorText(e)) });
  const done = () => {
    close();
    onDone();
  };
  /** A collection by name, made first when it is new. */
  const target = async (name: string, isNew: boolean) => (isNew ? await create.mutateAsync(name) : byName(name)!);

  const addTag = async (name: string) => {
    try {
      const r = await tagActions.apply(name, ids);
      done();
      toast({ kind: "info", text: r.message, action: undoAction(() => void tagActions.undo(r.undo).catch(fail)) });
    } catch (e) {
      fail(e);
    }
  };
  const removeTag = async (name: string) => {
    try {
      const r = await tagActions.removeFrom(name, ids);
      done();
      toast({ kind: "info", text: r.message, action: undoAction(() => void tagActions.undo(r.undo).catch(fail)) });
    } catch (e) {
      fail(e);
    }
  };
  const addTo = async (name: string, isNew: boolean) => {
    try {
      const c = await target(name, isNew);
      const had = new Set(c && "members" in c ? c.members.map((m) => m.drive_id) : []);
      const added = ids.filter((id) => !had.has(id));
      await members.mutateAsync({ id: c.id, add: ids });
      done();
      toast({
        kind: "info",
        text: `Added ${what} to ${visible(c.name)}`,
        action: added.length ? undoAction(() => void members.mutateAsync({ id: c.id, removeMany: added }).catch(fail)) : undefined,
      });
    } catch (e) {
      fail(e);
    }
  };
  /** Files by the collection they leave: within the shown tree each its own; else ``from``,
   * for the files that are in it. */
  const bySource = (from: CollectionRow | null) => {
    const out = new Map<number, { c: CollectionRow; ids: string[] }>();
    for (const id of ids) {
      const c = homeOf ? homeOf(id) : from;
      if (!c || !c.members.some((m) => m.drive_id === id)) continue;
      const entry = out.get(c.id) ?? { c, ids: [] };
      entry.ids.push(id);
      out.set(c.id, entry);
    }
    return [...out.values()];
  };
  const removeFrom = async (from: CollectionRow | null) => {
    try {
      const groups = bySource(from);
      for (const g of groups) await members.mutateAsync({ id: g.c.id, removeMany: g.ids });
      done();
      const where = groups.length === 1 ? visible(groups[0].c.name) : `${groups.length} collections`;
      const gone = groups.flatMap((g) => g.ids);
      const which = gone.length === 1 ? visible(files.find((f) => f.drive_id === gone[0])!.name) : `${gone.length} files`;
      toast({
        kind: "info",
        text: `Removed ${which} from ${where}`,
        action: undoAction(() => void Promise.all(groups.map((g) => members.mutateAsync({ id: g.c.id, add: g.ids }))).catch(fail)),
      });
    } catch (e) {
      fail(e);
    }
  };
  /** "a.pdf" for one of the selected files, "3 files" for more. */
  const named = (some: string[]) => (some.length === 1 ? visible(files.find((f) => f.drive_id === some[0])!.name) : `${some.length} files`);
  const moveTo = async (name: string, isNew: boolean) => {
    let to: { id: number; name: string; members: { drive_id: string }[] };
    try {
      to = await target(name, isNew);
    } catch (e) {
      fail(e);
      return;
    }
    // files already in the target stay there: they only leave their own collection
    const had = new Set(to.members.map((m) => m.drive_id));
    const groups = bySource(scope).filter((g) => g.c.id !== to.id);
    // one request per collection the files leave: if one fails, the ones done keep their Undo
    const moved: typeof groups = [];
    let error: unknown = null;
    for (const g of groups) {
      try {
        await members.mutateAsync({ id: g.c.id, move: { to: to.id, ids: g.ids } });
        moved.push(g);
      } catch (e) {
        error = e;
        break;
      }
    }
    if (error !== null && moved.length === 0) {
      fail(error);
      return;
    }
    done();
    const back = (g: { c: CollectionRow; ids: string[] }) => {
      const out = g.ids.filter((id) => !had.has(id));
      const kept = g.ids.filter((id) => had.has(id));
      return [
        ...(out.length ? [members.mutateAsync({ id: to.id, move: { to: g.c.id, ids: out } })] : []),
        ...(kept.length ? [members.mutateAsync({ id: g.c.id, add: kept })] : []),
      ];
    };
    const left = groups.filter((g) => !moved.includes(g)).flatMap((g) => g.ids);
    toast({
      kind: error === null ? "info" : "warning",
      text:
        error === null
          ? `Moved ${what} to ${visible(to.name)}`
          : `Moved ${named(moved.flatMap((g) => g.ids))} to ${visible(to.name)}, but not ${named(left)}: ${visible(errorText(error))}`,
      action: moved.length ? undoAction(() => void Promise.all(moved.flatMap(back)).catch(fail)) : undefined,
    });
  };

  const openRemoveTag = () => {
    setCarried(null);
    setSheet("remove-tag");
    // the tags any selected file carries, read in one call when the sheet opens
    void apiPost("/api/tags/carried", { body: { drive_ids: ids } })
      .then((r) => setCarried(r.tags))
      .catch((e) => {
        close();
        fail(e);
      });
  };
  /** Whether every selected file is in ``c`` already (moving them there would do nothing). */
  const homeOfAll = (c: CollectionRow) => homeOf !== null && ids.every((id) => homeOf(id)?.id === c.id);
  /** The collections a selected file is in (the Remove sheet's choices). */
  const inThem = () => ordinary.filter((c) => c.members.some((m) => ids.includes(m.drive_id)));

  const start = (which: Sheetful) => (which === "remove-tag" ? openRemoveTag() : setSheet(which));
  const entries: MenuEntry[] = [
    { label: "Add tag…", onSelect: () => setSheet("add-tag") },
    { label: "Remove tag…", onSelect: openRemoveTag },
    "separator",
    { label: "Add to collection…", onSelect: () => setSheet("add") },
    { label: "Remove from collection…", onSelect: () => setSheet("remove") },
    ...(scope ? [{ label: "Move to collection…", onSelect: () => setSheet("move") }] : []),
  ];
  const view = (
    <>
      {sheet === "add-tag" && (
        <PickSheet title={`Add a tag to ${what}`} options={(tags.data?.tags ?? []).map((t) => t.name)} allowNew onPick={(n) => void addTag(n)} onClose={close} />
      )}
      {sheet === "remove-tag" && <PickSheet title={`Remove a tag from ${what}`} options={carried} onPick={(n) => void removeTag(n)} onClose={close} />}
      {sheet === "add" && (
        <PickSheet
          title={`Add ${what} to a collection`}
          options={open.map((c) => c.name)}
          allowNew
          refuse={closedName}
          onPick={(n, isNew) => void addTo(n, isNew)}
          onClose={close}
        />
      )}
      {sheet === "remove" &&
        (scope ? (
          <Sheet open title={`Remove ${what} from ${visible(scope.name)}`} onClose={close}>
            <p>Each file leaves the collection it is in within {visible(scope.name)} (the collection itself, or the one inside it). The files stay where they are.</p>
            <div className="sheet-actions">
              <button type="button" onClick={close}>
                Cancel
              </button>
              <button type="button" className="primary" onClick={() => void removeFrom(null)}>
                Remove from {visible(scope.name)}
              </button>
            </div>
          </Sheet>
        ) : (
          <PickSheet
            title={`Remove ${what} from a collection`}
            options={inThem().map((c) => c.name)}
            hint="The files stay where they are; only the membership goes."
            onPick={(n) => void removeFrom(byName(n) ?? null)}
            onClose={close}
          />
        ))}
      {sheet === "move" && scope && (
        <PickSheet
          title={`Move ${what} to another collection`}
          options={open.filter((c) => c.id !== scope.id && !homeOfAll(c)).map((c) => c.name)}
          allowNew
          refuse={closedName}
          hint={`The files leave ${visible(scope.name)} (or the collection inside it they are in) and join the one you pick.`}
          onPick={(n, isNew) => void moveTo(n, isNew)}
          onClose={close}
        />
      )}
    </>
  );
  return { entries, open: start, view };
}
