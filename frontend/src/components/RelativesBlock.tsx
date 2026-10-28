/** Relatives: the files a document belongs with, in the details panel (New look only).
 *
 * The server ranks them (``GET /api/files/{id}/relatives``) and says why: each shares a
 * folder, sender, tag, collection, IBAN, reference or person with this file. Tick some to
 * act on them together with this file: tag, add to a collection, move, or link. Every
 * change shows what it will do first and can be undone, through the flows the rest of the
 * app uses. "Not related" takes a file out of the list for good (Show again brings it back). */
import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
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
  useRelatives,
  useRelativesDismissed,
  useStatus,
  useTagActions,
} from "../api/client";
import { plural } from "../format";
import { baseName, parentOf } from "../paths";
import { visible } from "../text";
import { CollectionPicker } from "./CollectionPicker";
import { Collapsible } from "./Collapsible";
import { browseTo, ShowInBrowse } from "./maintenance/ShowInBrowse";
import { folderLabel, MoveToSheet, useMoveFlow } from "./MoveTo";
import { ConfirmPlan, snapshotKey } from "./PlanPreview";
import { QuickLook, type QLFile } from "./QuickLook";
import { TagInput } from "./TagInput";
import { undoAction, useToast } from "./Toasts";
import { useUndoConfirm } from "./UndoConfirm";
import { IconButton } from "./ui/IconButton";
import { Sheet } from "./ui/Sheet";

/** How many relatives show before "N more". */
export const SHOWN = 4;

const KIND_LABEL: Record<RelativeKind, string> = {
  folder: "folder",
  sender: "sender",
  tag: "tag",
  collection: "collection",
  iban: "IBAN",
  reference: "reference",
  person: "person",
};
const KIND_PHRASE: Record<RelativeKind, string> = {
  folder: "Same folder",
  sender: "Same sender",
  tag: "Same tag",
  collection: "Same collection",
  iban: "Same IBAN",
  reference: "Same reference number",
  person: "Same person",
};
const KIND_CLASS: Record<RelativeKind, string> = {
  folder: "tag-blue",
  sender: "tag-orange",
  tag: "tag-green",
  collection: "tag-grey",
  iban: "tag-grey",
  reference: "tag-blue",
  person: "tag-grey",
};

export const EMPTY_TEXT =
  "No relatives yet. Files share a folder, tag, collection, sender, person, IBAN or reference to show here.";

const fold = (s: string) => s.normalize("NFC").toLowerCase();

/** The kinds of link a relative has, strongest first, each once. */
const kindsOf = (r: Relative): RelativeKind[] => {
  const best = new Map<RelativeKind, number>();
  for (const l of r.links) best.set(l.kind, Math.max(best.get(l.kind) ?? 0, l.weight));
  return [...best].sort((a, b) => b[1] - a[1]).map(([kind]) => kind);
};
const linkTip = (r: Relative) => r.links.map((l) => `${KIND_LABEL[l.kind]}: ${l.value}`).join("\n");

type BlockFile = { drive_id: string; path: string; name: string | null };

export function RelativesBlock({ file }: { file: BlockFile }) {
  const query = useRelatives(file.drive_id);
  const data = query.data;
  return (
    <Collapsible
      name="relatives"
      title="Relatives"
      className="relatives"
      aside={data && data.total > 0 ? <span className="relatives-count">{data.total}</span> : undefined}
    >
      {query.isError ? (
        <p className="hint">Relatives could not be loaded: {visible(errorText(query.error))}</p>
      ) : !data ? (
        <p className="hint">Looking for relatives…</p>
      ) : (
        <RelativesList key={file.drive_id} file={file} relatives={data.relatives} hidden={data.hidden} />
      )}
    </Collapsible>
  );
}

function RelativesList({ file, relatives, hidden }: { file: BlockFile; relatives: Relative[]; hidden: number }) {
  const toast = useToast();
  const marks = useRelativeMark();
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [showAll, setShowAll] = useState(false);
  const [lookAt, setLookAt] = useState<number | null>(null);
  const [showHidden, setShowHidden] = useState(false);

  // files still in the Inbox come first: they are the ones that may need filing
  const ordered = [...relatives.filter((r) => r.in_inbox), ...relatives.filter((r) => !r.in_inbox)];
  const shown = showAll ? ordered : ordered.slice(0, SHOWN);
  const more = ordered.length - shown.length;
  const moreAllSingle = ordered.slice(SHOWN).every((r) => r.links.length === 1);
  const ticked = ordered.filter((r) => selected.has(r.drive_id));

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const notRelated = (r: Relative) =>
    marks.mutate(
      { driveId: file.drive_id, other: r.drive_id, mark: "dismiss" },
      {
        onSuccess: () => {
          setSelected((prev) => {
            const next = new Set(prev);
            next.delete(r.drive_id);
            return next;
          });
          toast({
            kind: "info",
            text: `${visible(r.name)} marked not related`,
            action: undoAction(() => marks.mutate({ driveId: file.drive_id, other: r.drive_id, mark: "restore" })),
          });
        },
        onError: (e) => toast({ kind: "error", text: `Could not mark it: ${visible(errorText(e))}` }),
      },
    );

  const quickLook: QLFile[] = ordered.map((r) => ({ drive_id: r.drive_id, name: r.name, path: r.path, ext: r.ext }));

  if (relatives.length === 0 && hidden === 0) return <p className="hint">{EMPTY_TEXT}</p>;
  return (
    <div className="relatives-body">
      {relatives.length === 0 && <p className="hint">{EMPTY_TEXT}</p>}
      <ul className="relatives-list">
        {shown.map((r) => (
          <RelativeRow
            key={r.drive_id}
            relative={r}
            checked={selected.has(r.drive_id)}
            onToggle={() => toggle(r.drive_id)}
            onLook={() => setLookAt(ordered.indexOf(r))}
            onNotRelated={() => notRelated(r)}
          />
        ))}
      </ul>
      {more > 0 && (
        <button type="button" className="link-button relatives-more" onClick={() => setShowAll(true)}>
          {more} more{moreAllSingle ? " with one link in common" : ""}
        </button>
      )}
      {ticked.length > 0 && <ActionBar file={file} ticked={ticked} onClear={() => setSelected(new Set())} />}
      {hidden > 0 && (
        <div className="relatives-hidden">
          <button
            type="button"
            className="link-button"
            aria-expanded={showHidden}
            onClick={() => setShowHidden((v) => !v)}
          >
            {hidden} marked not related
          </button>
          {showHidden && <DismissedList driveId={file.drive_id} />}
        </div>
      )}
      {lookAt !== null && (
        <div
          onKeyDown={(e) => {
            // Quick Look's keys: Space closes, the arrows (and j / k) page through the relatives
            if (e.target instanceof Element && e.target.closest("button") && e.key === " ") return;
            if (e.key === " ") setLookAt(null);
            else if (e.key === "ArrowRight" || e.key === "j") setLookAt((i) => Math.min(quickLook.length - 1, (i ?? 0) + 1));
            else if (e.key === "ArrowLeft" || e.key === "k") setLookAt((i) => Math.max(0, (i ?? 0) - 1));
            else return;
            e.preventDefault();
          }}
        >
          <QuickLook files={quickLook} index={lookAt} onIndex={setLookAt} onClose={() => setLookAt(null)} />
        </div>
      )}
    </div>
  );
}

function RelativeRow({
  relative: r,
  checked,
  onToggle,
  onLook,
  onNotRelated,
}: {
  relative: Relative;
  checked: boolean;
  onToggle: () => void;
  onLook: () => void;
  onNotRelated: () => void;
}) {
  const name = visible(r.name);
  const kinds = kindsOf(r);
  const unfiled = r.in_inbox;
  return (
    <li className={`relative-row${checked ? " checked" : ""}${unfiled ? " unfiled" : ""}`} data-drive-id={r.drive_id}>
      <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`Select ${name}`} />
      <div className="relative-main">
        <div className="relative-line">
          <button type="button" className="relative-name trunc" title={`Quick Look: ${name}`} onClick={onLook}>
            {name}
          </button>
          <span className="relative-folder trunc" title={visible(r.folder)}>
            {unfiled ? "Inbox" : visible(baseName(r.folder)) || "Archive"}
          </span>
        </div>
        {unfiled && (
          <div className="relative-unfiled">
            <span>{KIND_PHRASE[kinds[0]]}, not filed yet</span>
            <Link to="/inbox" className="link-button">
              Go to the inbox
            </Link>
          </div>
        )}
        <div className="relative-kinds" title={linkTip(r)}>
          {kinds.map((kind) => (
            <span key={kind} className={`tag ${KIND_CLASS[kind]}`}>
              {KIND_LABEL[kind]}
            </span>
          ))}
          {r.same_month && <span className="tag tag-grey">+ same month</span>}
        </div>
      </div>
      <div className="relative-tools">
        <IconButton icon={<Eye size={14} />} label={`Quick Look ${name}`} tip="Quick Look" onClick={onLook} />
        <ShowInBrowse to={browseTo(r.path, r.drive_id)} label={`Show ${name} in Browse`} />
        <IconButton
          icon={<EyeOff size={14} />}
          label={`Not related: ${name}`}
          tip="Not related: leave this file out of the list"
          onClick={onNotRelated}
        />
      </div>
    </li>
  );
}

function DismissedList({ driveId }: { driveId: string }) {
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

function ActionBar({ file, ticked, onClear }: { file: BlockFile; ticked: Relative[]; onClear: () => void }) {
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

  return (
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
    </div>
  );
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
