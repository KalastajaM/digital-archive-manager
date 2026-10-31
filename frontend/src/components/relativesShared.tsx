/** What the Relatives block and the Relatives dialog share: the labels for the kinds of
 * link, the actions on the ticked files (each previews first and can be undone, through
 * the flows the rest of the app uses), Not related with its way back, and the Quick Look
 * that compares a relative with this file. */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  errorText,
  type Relative,
  type RelativeKind,
  type ResolvedOp,
  useCollectionMembers,
  useCollections,
  useFileLinks,
  useLinkThere,
  useRelativeMark,
  useRelativesDismissed,
  useStatus,
  useTagActions,
} from "../api/client";
import { plural } from "../format";
import { baseName, parentOf } from "../paths";
import { visible } from "../text";
import { CollectionPicker } from "./CollectionPicker";
import { browseHref } from "./GroupTree";
import { folderLabel, MoveToSheet, useMoveFlow } from "./MoveTo";
import { ConfirmPlan, snapshotKey } from "./PlanPreview";
import { QuickLook, type QLFile } from "./QuickLook";
import { isAIPick } from "./relativesAI";
import { TagInput } from "./TagInput";
import { undoAction, useToast } from "./Toasts";
import { useUndoConfirm } from "./UndoConfirm";
import type { MenuEntry } from "./ui/Menu";
import { Sheet } from "./ui/Sheet";

export const KIND_LABEL: Record<RelativeKind, string> = {
  folder: "folder",
  sender: "sender",
  business_id: "business ID",
  tag: "tag",
  collection: "collection",
  iban: "IBAN",
  reference: "reference",
  person: "person",
};
export const KIND_NAME: Record<RelativeKind, string> = {
  folder: "Folder",
  sender: "Sender",
  business_id: "Business ID",
  tag: "Tag",
  collection: "Collection",
  iban: "IBAN",
  reference: "Reference",
  person: "Person",
};
export const KIND_PHRASE: Record<RelativeKind, string> = {
  folder: "Same folder",
  sender: "Same sender",
  business_id: "Same business ID",
  tag: "Same tag",
  collection: "Same collection",
  iban: "Same IBAN",
  reference: "Same reference number",
  person: "Same person",
};
export const KIND_CLASS: Record<RelativeKind, string> = {
  folder: "tag-blue",
  sender: "tag-orange",
  business_id: "tag-orange",
  tag: "tag-green",
  collection: "tag-grey",
  iban: "tag-grey",
  reference: "tag-blue",
  person: "tag-grey",
};

export const EMPTY_TEXT =
  "No relatives yet. Files share a folder, tag, collection, sender, person, IBAN or reference to show here.";

export const fold = (s: string) => s.normalize("NFC").toLowerCase();

/** The kinds of link a relative has, strongest first, each once. */
export const kindsOf = (r: Relative): RelativeKind[] => {
  const best = new Map<RelativeKind, number>();
  for (const l of r.links) best.set(l.kind, Math.max(best.get(l.kind) ?? 0, l.weight));
  return [...best].sort((a, b) => b[1] - a[1]).map(([kind]) => kind);
};
export const linkTip = (r: Relative) => r.links.map((l) => `${KIND_LABEL[l.kind]}: ${l.value}`).join("\n");

export type BlockFile = { drive_id: string; path: string; name: string | null; ext?: string | null };

/** "Not related": marks the pair, takes the file out of the list and offers Undo.
 * ``.many(rs)``: the same for several at once, with one toast and one Undo for all. */
export function useNotRelated(file: BlockFile, onMarked?: (r: Relative) => void) {
  const toast = useToast();
  const marks = useRelativeMark();
  const one = (r: Relative) =>
    marks.mutate(
      { driveId: file.drive_id, other: r.drive_id, mark: "dismiss" },
      {
        onSuccess: () => {
          onMarked?.(r);
          toast({
            kind: "info",
            text: `${visible(r.name)} marked not related`,
            action: undoAction(() => marks.mutate({ driveId: file.drive_id, other: r.drive_id, mark: "restore" })),
          });
        },
        onError: (e) => toast({ kind: "error", text: `Could not mark it: ${visible(errorText(e))}` }),
      },
    );
  const many = async (rs: Relative[]) => {
    const results = await Promise.allSettled(rs.map((r) => marks.mutateAsync({ driveId: file.drive_id, other: r.drive_id, mark: "dismiss" })));
    const done = rs.filter((_, i) => results[i].status === "fulfilled");
    done.forEach((r) => onMarked?.(r));
    if (done.length > 0)
      toast({
        kind: "info",
        text: `${done.length === 1 ? visible(done[0].name) : `${done.length} files`} marked not related`,
        action: undoAction(() => done.forEach((r) => marks.mutate({ driveId: file.drive_id, other: r.drive_id, mark: "restore" }))),
      });
    const failed = results.find((x): x is PromiseRejectedResult => x.status === "rejected");
    if (failed) toast({ kind: "error", text: `Could not mark ${rs.length - done.length} of them: ${visible(errorText(failed.reason))}` });
  };
  return Object.assign(one, { many });
}

/** Quick Look in compare mode over a list of relatives: this file beside the shown one,
 * what they share, and the verdict keys. ``open(i)`` shows the i-th of ``list``; Not
 * related takes the file out of the stepping at once and moves on. Show in folder closes
 * it (and runs ``onLeave``: the Relatives dialog closes too) and opens Browse there. */
export function useRelativeLook(file: BlockFile, list: Relative[], notRelated: (r: Relative) => void, onLeave?: () => void) {
  const navigate = useNavigate();
  const [at, setAt] = useState<number | null>(null);
  const [gone, setGone] = useState<ReadonlySet<string>>(new Set());
  const rows = useMemo(() => list.filter((r) => !gone.has(r.drive_id)), [list, gone]);
  const close = () => {
    setAt(null);
    setGone(new Set());
  };
  const index = at === null ? null : Math.min(at, rows.length - 1);
  const byId = new Map(rows.map((r) => [r.drive_id, r]));
  const subject: QLFile = {
    drive_id: file.drive_id,
    name: file.name,
    path: file.path,
    ext: file.ext ?? (file.path.includes(".") ? file.path.slice(file.path.lastIndexOf(".") + 1) : null),
  };
  const view =
    index !== null && index >= 0 ? (
      <QuickLook
        files={rows.map((r) => ({ drive_id: r.drive_id, name: r.name, path: r.path, ext: r.ext }))}
        index={index}
        onIndex={setAt}
        onClose={close}
        compare={{
          subject,
          shared: (f) => {
            const r = byId.get(f.drive_id);
            return r ? sharedLabels(r) : [];
          },
          reason: (f) => {
            const r = byId.get(f.drive_id);
            return r && isAIPick(r) ? visible(r.reason) : null;
          },
          onNotRelated: (f) => {
            const r = byId.get(f.drive_id);
            if (!r) return;
            notRelated(r);
            setGone((prev) => new Set(prev).add(r.drive_id));
            if (rows.length <= 1) close();
            else setAt(Math.min(index, rows.length - 2));
          },
          showInFolder: (f) => {
            close();
            onLeave?.();
            navigate(browseHref(f.path, f.drive_id));
          },
        }}
      />
    ) : null;
  return {
    open: (id: string) => {
      const i = list.findIndex((r) => r.drive_id === id);
      if (i >= 0) setAt(i);
    },
    view,
  };
}

/** What a relative shares with the file, as short lines: "Tag: Taxes", "+ same month".
 * An AI pick's reason is a sentence, not a label: Quick Look shows it on a line of its own. */
export const sharedLabels = (r: Relative): string[] => [
  ...r.links.map((l) => `${KIND_NAME[l.kind]}: ${visible(l.value)}`),
  ...(r.same_month ? ["+ same month"] : []),
];


export function DismissedList({ driveId }: { driveId: string }) {
  const list = useRelativesDismissed(driveId);
  const marks = useRelativeMark();
  if (list.isError) return <p className="hint">Could not load them: {visible(errorText(list.error))}</p>;
  return (
    <ul className="relatives-dismissed">
      {(list.data?.dismissed ?? []).map((d) => (
        <li key={d.drive_id}>
          <span className="trunc" title={visible(d.path)}>
            {visible(d.name)}
          </span>
          <button
            type="button"
            className="link-button"
            aria-label={`Show ${visible(d.name)} again`}
            onClick={() => marks.mutate({ driveId, other: d.drive_id, mark: "restore" })}
          >
            Show again
          </button>
        </li>
      ))}
    </ul>
  );
}

/** A button that is off, with the reason as its tooltip (as elsewhere in the app). */
function Off({ label, reason }: { label: string; reason: string }) {
  return (
    <span className="button-wrap" data-tip={reason}>
      <button type="button" disabled title={reason}>
        {label}
      </button>
    </span>
  );
}

type Sheets = "tag" | "collection" | "move" | null;

/** The ticked files' actions with this file (the bar under the list). */
export function ActionBar(props: { file: BlockFile; ticked: Relative[]; onClear: () => void }) {
  const actions = useRelativeActions(props);
  return (
    <>
      {actions.bar}
      {actions.view}
    </>
  );
}

/** What the ticked files and this file can have done together: ``bar`` (the buttons),
 * ``view`` (their sheets and confirms, always rendered) and ``entries`` (the same as a
 * right-click menu, named for what they act on: "Tag it and this file…"). */
export function useRelativeActions({ file, ticked, onClear }: { file: BlockFile; ticked: Relative[]; onClear: () => void }) {
  const toast = useToast();
  const status = useStatus();
  const linkThere = useLinkThere();
  const undo = useUndoConfirm();
  const [sheet, setSheet] = useState<Sheets>(null);
  const [pending, setPending] = useState<{ folders: string[]; ops: ResolvedOp[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const move = useMoveFlow(() => onClear());

  const here = parentOf(file.path);
  const canLink = status.data?.can_link !== false;
  const everyone = [file.drive_id, ...ticked.map((r) => r.drive_id)];
  const names = [file.name ?? baseName(file.path), ...ticked.map((r) => r.name)];

  // "Link them here": a relative already in this file's folder needs no link
  const needLink = ticked.filter((r) => fold(r.folder) !== fold(here));
  // "Link this file there": a link in each distinct folder of the ticked files, not here and not the inbox
  const folders = [
    ...new Map(ticked.filter((r) => !r.in_inbox && fold(r.folder) !== fold(here)).map((r) => [fold(r.folder), r.folder])).values(),
  ];

  const linkThemHere = () => {
    if (needLink.length === 0) return;
    move.start({ ids: needLink.map((r) => r.drive_id), folder: here, mode: "link" });
  };

  const previewLinkThere = async () => {
    setBusy(true);
    try {
      const ops = await linkThere.preview({ drive_id: file.drive_id, folders });
      if (ops.length === 0) toast({ kind: "info", text: "Nothing to link: the file is already in those folders" });
      else setPending({ folders, ops });
    } catch (e) {
      toast({ kind: "error", text: `Cannot link: ${visible(errorText(e))}` });
    } finally {
      setBusy(false);
    }
  };

  const applyLinkThere = async (plan: { folders: string[]; ops: ResolvedOp[] }) => {
    setPending(null);
    setBusy(true);
    try {
      const result = await linkThere.apply({ drive_id: file.drive_id, folders: plan.folders });
      const complete = !result.error && !result.failed;
      if (result.done.length === 0 && complete) {
        toast({ kind: "info", text: "Nothing to link" });
        return;
      }
      if (!complete) {
        toast({
          kind: "error",
          text: `Stopped after ${plural(result.done.length, "link")}: ${visible(result.error ?? "an operation failed")}`,
        });
      }
      if (result.done.length > 0) {
        toast({
          kind: complete ? "info" : "warning",
          text: `${complete ? "" : "Partly applied: "}Linked ${visible(file.name ?? baseName(file.path))} in ${plural(result.done.length, "folder")}`,
          action: undoAction(() => undo.open({ batchId: result.batch_id })),
        });
      }
    } catch (e) {
      toast({ kind: "error", text: `Could not link: ${visible(errorText(e))}` });
    } finally {
      setBusy(false);
    }
  };

  const bar = (
    <div className="relatives-actions" role="group" aria-label="Actions for the ticked files">
      <div className="relatives-actions-head">
        <strong>This file and {ticked.length} related</strong>
        <button type="button" className="link-button" onClick={onClear}>
          Clear
        </button>
      </div>
      <div className="relatives-actions-row">
        <button type="button" onClick={() => setSheet("tag")}>
          Tag…
        </button>
        <button type="button" onClick={() => setSheet("collection")}>
          Add to collection…
        </button>
        <button type="button" onClick={() => setSheet("move")} disabled={busy || move.busy}>
          Move to folder…
        </button>
      </div>
      {canLink && (
        <div className="relatives-actions-row">
          {needLink.length > 0 ? (
            <button type="button" onClick={linkThemHere} disabled={busy || move.busy}>
              Link {needLink.length === 1 ? "it" : `${needLink.length} of them`} here
            </button>
          ) : (
            <Off label="Link them here" reason={`No links needed: all ${ticked.length} are already in ${folderLabel(here)}`} />
          )}
          {folders.length > 0 ? (
            <button type="button" onClick={() => void previewLinkThere()} disabled={busy || move.busy}>
              Link this file there
            </button>
          ) : (
            <Off
              label="Link this file there"
              reason="No links needed: the ticked files are in this file's folder or in the inbox"
            />
          )}
        </div>
      )}
    </div>
  );
  const view = (
    <>
      {sheet === "tag" && (
        <TagSheet
          ids={everyone}
          names={names}
          onClose={() => setSheet(null)}
          onDone={() => {
            setSheet(null);
          }}
        />
      )}
      {sheet === "collection" && (
        <CollectionSheet
          file={file}
          ticked={ticked}
          names={names}
          onClose={() => setSheet(null)}
          onDone={() => setSheet(null)}
        />
      )}
      {sheet === "move" && (
        <MoveToSheet
          names={names}
          initial=""
          onCancel={() => setSheet(null)}
          onChoose={(dest) => {
            setSheet(null);
            move.start({ ids: everyone, folder: dest });
          }}
        />
      )}
      {move.view}
      {pending && (
        <ConfirmPlan
          planKey={snapshotKey({ id: file.drive_id, folders: pending.folders, ops: pending.ops })}
          title={`Link ${visible(file.name ?? baseName(file.path))} in ${plural(pending.folders.length, "folder")}?`}
          confirmLabel="Make links"
          intro={
            <p>
              Each link is a shortcut that opens the file; the file itself stays where it is. A name already taken there
              gets a suffix such as <code>_2</code>. One Undo removes all the links.
            </p>
          }
          ops={pending.ops}
          busy={busy}
          onConfirm={() => void applyLinkThere(pending)}
          onCancel={() => setPending(null)}
        />
      )}
    </>
  );
  // the menu's entries: the bar's actions, named for the files they take
  const them = ticked.length === 1 ? "it" : "them";
  const busyWhy = busy || move.busy ? "Another change is under way" : null;
  const entries: MenuEntry[] = [
    { label: `Tag ${them} and this file…`, onSelect: () => setSheet("tag") },
    { label: `Add ${them} and this file to a collection…`, onSelect: () => setSheet("collection") },
    { label: `Move ${them} and this file to a folder…`, onSelect: () => setSheet("move"), disabled: !!busyWhy, reason: busyWhy ?? undefined },
    ...(canLink
      ? [
          needLink.length > 0
            ? { label: `Link ${needLink.length === ticked.length ? them : `${needLink.length} of them`} here`, onSelect: linkThemHere, disabled: !!busyWhy, reason: busyWhy ?? undefined }
            : { label: `Link ${them} here`, onSelect: () => {}, disabled: true, reason: `Already in ${folderLabel(here)}` },
          folders.length > 0
            ? { label: "Link this file there", onSelect: () => void previewLinkThere(), disabled: !!busyWhy, reason: busyWhy ?? undefined }
            : { label: "Link this file there", onSelect: () => {}, disabled: true, reason: "No links needed: the ticked files are in this file's folder or in the inbox" },
        ]
      : []),
  ];
  return { bar, view, entries };
}

const NAMES_SHOWN = 5;
function NameList({ names }: { names: string[] }) {
  const more = names.length > NAMES_SHOWN ? ` +${names.length - NAMES_SHOWN} more` : "";
  return (
    <p className="move-to-files">
      {names.slice(0, NAMES_SHOWN).map(visible).join(", ")}
      {more}
    </p>
  );
}

function TagSheet({
  ids,
  names,
  onClose,
  onDone,
}: {
  ids: string[];
  names: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const actions = useTagActions();
  const toast = useToast();
  const [tags, setTags] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    const undos: Awaited<ReturnType<typeof actions.apply>>["undo"][] = [];
    try {
      for (const tag of tags) undos.push((await actions.apply(tag, ids)).undo);
    } catch (e) {
      toast({ kind: "error", text: `Could not tag: ${visible(errorText(e))}` });
      // what was done before the failure is one step to undo as well
    } finally {
      setBusy(false);
    }
    if (undos.length === 0) return;
    onDone();
    const said = tags.slice(0, undos.length).map((t) => `‘${visible(t)}’`).join(", ");
    toast({
      kind: "info",
      text: `Tagged ${plural(ids.length, "file")} ${said}`,
      action: undoAction(() => {
        void (async () => {
          try {
            for (const undo of [...undos].reverse()) await actions.undo(undo);
          } catch (e) {
            toast({ kind: "error", text: `Could not undo: ${visible(errorText(e))}` });
          }
        })();
      }),
    });
  };

  return (
    <Sheet
      open
      className="move-to"
      title={`Tag ${plural(ids.length, "file")}`}
      onClose={onClose}
      onKeyDown={(e) => e.stopPropagation()}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={tags.length === 0 || busy} onClick={() => void submit()}>
            Tag {plural(ids.length, "file")}
          </button>
        </>
      }
    >
      <NameList names={names} />
      <TagInput value={tags} onChange={setTags} label="Tags to add" />
      <p className="hint">Press Enter to add a tag. The tags go on all of these files; Undo takes them off again.</p>
    </Sheet>
  );
}

function CollectionSheet({
  file,
  ticked,
  names,
  onClose,
  onDone,
}: {
  file: BlockFile;
  ticked: Relative[];
  names: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const collections = useCollections("open");
  const own = useFileLinks(file.drive_id);
  const members = useCollectionMembers();
  const toast = useToast();
  const [chosen, setChosen] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const name = chosen[0];
  const collection = collections.data?.find((c) => c.name === name);
  // the files that are not in it yet: the relatives show their collections as links
  const already = new Set<string>();
  if (own.data?.collections.some((c) => c.name === name)) already.add(file.drive_id);
  for (const r of ticked) if (r.links.some((l) => l.kind === "collection" && l.value === name)) already.add(r.drive_id);
  const everyone = [file.drive_id, ...ticked.map((r) => r.drive_id)];
  const adding = everyone.filter((id) => !already.has(id));

  const submit = async () => {
    if (!collection || adding.length === 0) return;
    setBusy(true);
    try {
      await members.mutateAsync({ id: collection.id, add: adding });
    } catch (e) {
      toast({ kind: "error", text: `Could not add: ${visible(errorText(e))}` });
      setBusy(false);
      return;
    }
    setBusy(false);
    onDone();
    toast({
      kind: "info",
      text: `Added ${plural(adding.length, "file")} to ${visible(collection.name)}`,
      action: undoAction(() => {
        void (async () => {
          try {
            for (const id of adding) await members.mutateAsync({ id: collection.id, remove: id });
          } catch (e) {
            toast({ kind: "error", text: `Could not undo: ${visible(errorText(e))}` });
          }
        })();
      }),
    });
  };

  return (
    <Sheet
      open
      className="move-to"
      title={`Add ${plural(everyone.length, "file")} to a collection`}
      onClose={onClose}
      onKeyDown={(e) => e.stopPropagation()}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="primary"
            disabled={!collection || adding.length === 0 || busy}
            onClick={() => void submit()}
          >
            Add {adding.length > 0 ? plural(adding.length, "file") : ""}
          </button>
        </>
      }
    >
      <NameList names={names} />
      <CollectionPicker value={chosen} onChange={setChosen} text={text} onTextChange={setText} label="Collection" single autoFocus />
      {collection && (
        <p>
          Collection: <strong>{visible(collection.name)}</strong>
        </p>
      )}
      {collection && adding.length === 0 && <p className="hint">All of them are in {visible(collection.name)} already.</p>}
      {collection && adding.length > 0 && adding.length < everyone.length && (
        <p className="hint">
          {plural(everyone.length - adding.length, "file")} already in {visible(collection.name)}; the other{" "}
          {adding.length} are added.
        </p>
      )}
      <p className="hint">Undo takes them out of the collection again; the files stay where they are.</p>
    </Sheet>
  );
}
