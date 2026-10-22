/** Convert ##. Ongoing: each existing entry becomes a collection, one at a time. Every
 * conversion is previewed (the exact ops, members and notes), bound to its preview by a
 * fingerprint, applied as its own undoable batch. */
import { CircleCheck, Eye, FileText, Folder, Link2 } from "lucide-react";
import { type ReactNode, type RefObject, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  type CollectionChange,
  type ConvertBody,
  type ConvertPlan,
  type ConvertResult,
  errorText,
  type OngoingEntry,
  useConvert,
  useConvertPreview,
  useOngoingEntries,
} from "../api/client";
import {
  COLLECTION_NAME_MAX,
  CollectionPicker,
} from "../components/CollectionPicker";
import { changeLines } from "../components/collectionText";
import { LaunchButtons, useFileLaunch } from "../components/FileLaunch";
import { type RefusedRoot } from "../components/FolderBrowser";
import { FolderPicker } from "../components/FolderPicker";

/** Destinations the conversion refuses besides ``##. Ongoing`` and the quarantine
 * (the inbox: ``_forbidden_destinations``; ``##. Important``: a protected path). */
const CONVERT_REFUSES: readonly RefusedRoot[] = ["important", "inbox"];
import { LastChange } from "../components/LastChange";
import { MarkIcons } from "../components/MarkIcons";
import { ConfirmPlan, snapshotKey } from "../components/PlanPreview";
import { useBlockToastActions, useToast } from "../components/Toasts";
import { useUndoConfirm } from "../components/UndoConfirm";
import { type QLFile, useQuickLook } from "../components/useQuickLook";
import { EmptyState } from "../components/ui/EmptyState";
import { IconButton } from "../components/ui/IconButton";
import { Tag } from "../components/ui/Tag";
import { Toolbar } from "../components/ui/Toolbar";
import { plural } from "../format";
import { visible } from "../text";

const CONTENTS_SHOWN = 8;
/** Why Preview is disabled (spec §1.3). */
export const NEEDS_NAME = "Name the collection or choose an existing one";
export const NEEDS_FOLDER = "Choose an archive folder";
const ICON = { size: 16, strokeWidth: 1.75 } as const;
const STALE_CODE = "stale_preview";

type View = Pick<CollectionChange, "problems" | "batch" | "ongoing_status">;
type Done = { batchId: string; title: string; view: View };
type Pending = { body: ConvertBody; plan: ConvertPlan };

const KIND_ICON: Record<string, ReactNode> = {
  link: <Link2 size={16} />,
  folder: <Folder size={16} />,
  file: <FileText size={16} />,
};

export type EntryItem = OngoingEntry["items"][number];

/** Quick Look on one file of the page: by its key (``entryKey``/``itemKey``);
 * undefined when the thing cannot be looked at (a folder, or not in the index). */
export type Look = (key: string) => (() => void) | undefined;

/** A row Quick Look can show: focusable, and Space on it (the row itself, not one of
 * its buttons) opens Quick Look on it. */
const lookRow = (key: string, look: Look) =>
  look(key) ? { tabIndex: 0, "data-quicklook": true, "data-look": key } : {};

const extOf = (name: string) => {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : null;
};
const baseName = (path: string) => path.slice(path.lastIndexOf("/") + 1);
const entryKey = (entry: OngoingEntry) => entry.rel;
const itemKey = (entry: OngoingEntry, item: EntryItem) => `${entry.rel}/${item.name}`;

/** What Quick Look can show of the shown entries, in page order: each entry that is (or
 * links to) an indexed file, then the indexed files listed inside a folder entry. */
export function lookables(entries: OngoingEntry[]): { key: string; file: QLFile }[] {
  const out: { key: string; file: QLFile }[] = [];
  for (const e of entries) {
    if (e.drive_id && !e.is_dir) {
      const path = e.target_rel ?? e.rel;
      out.push({ key: entryKey(e), file: { drive_id: e.drive_id, name: baseName(path), path, ext: extOf(path) } });
    }
    for (const i of e.items) {
      if (!i.drive_id || i.is_dir) continue;
      out.push({
        key: itemKey(e, i),
        file: { drive_id: i.drive_id, name: i.name, path: `${e.rel}/${i.name}`, ext: extOf(i.name), is_link: i.is_link },
      });
    }
  }
  return out;
}

/** Quick Look, Open and Show in Finder for one thing on the page (by drive id: a link's
 * is its target's). A folder is shown in Finder only: it is never opened or looked at. */
function OpenButtons({ driveId, label, isDir, onLook }: { driveId: string; label: string; isDir: boolean; onLook?: () => void }) {
  const launch = useFileLaunch(driveId);
  return (
    <span className="ongoing-open" role="group" aria-label={label}>
      {!isDir && onLook && <IconButton icon={<Eye {...ICON} />} label="Quick Look" onClick={onLook} />}
      <LaunchButtons launch={launch} only={isDir ? "reveal" : undefined} />
    </span>
  );
}

/** An entry's name with its kind: an icon, the name (the row's heading), a tag, and
 * the buttons to look at, open or show it. */
export function EntryHeader({ entry, look }: { entry: OngoingEntry; look: Look }) {
  const name = visible(entry.rel);
  return (
    <header className="ongoing-entry-header" {...lookRow(entryKey(entry), look)}>
      <span className="ongoing-entry-icon" aria-hidden="true">
        {KIND_ICON[entry.kind] ?? <FileText size={16} />}
      </span>
      <h3>
        {name}
        <MarkIcons marks={entry.marks} />
      </h3>
      <Tag tone="grey">{entry.kind}</Tag>
      {entry.drive_id && (
        <OpenButtons driveId={entry.drive_id} label={`Open ${name}`} isDir={entry.is_dir} onLook={look(entryKey(entry))} />
      )}
    </header>
  );
}

/** The top-level items of a folder entry, each with its own buttons (up to
 * ``CONTENTS_SHOWN``, then "Show all"). */
export function FolderItems({ entry, look }: { entry: OngoingEntry; look: Look }) {
  const [all, setAll] = useState(false);
  const byName = new Map(entry.items.map((i) => [i.name, i]));
  const items: EntryItem[] = entry.contents.map((n) => byName.get(n) ?? { name: n, drive_id: null, is_dir: false, is_link: false, unreadable: false, marks: [] });
  const shown = all ? items : items.slice(0, CONTENTS_SHOWN);
  const folderName = visible(baseName(entry.rel));
  return (
    <div className="ongoing-entry-what">
      <p className="ongoing-items-title">Contains {plural(items.length, "item")}:</p>
      <ul className="ongoing-items" aria-label={`Contents of ${folderName}`}>
        {shown.map((i) => {
          const name = visible(i.name);
          return (
            <li key={i.name} className="ongoing-item" {...lookRow(itemKey(entry, i), look)}>
              <span className="ongoing-item-name">
                {i.is_dir ? <Folder size={14} aria-hidden="true" /> : i.is_link ? <Link2 size={14} aria-hidden="true" /> : <FileText size={14} aria-hidden="true" />}
                {name}
                <MarkIcons marks={i.marks} />
              </span>
              {i.drive_id ? (
                <OpenButtons driveId={i.drive_id} label={name} isDir={i.is_dir} onLook={look(itemKey(entry, i))} />
              ) : (
                <span className="hint">{i.unreadable ? "can't be read" : "not indexed yet"}</span>
              )}
            </li>
          );
        })}
      </ul>
      {items.length > CONTENTS_SHOWN && (
        <button type="button" className="link-button" onClick={() => setAll((v) => !v)}>
          {all ? "Show fewer" : `Show all ${items.length}`}
        </button>
      )}
    </div>
  );
}

type RowProps = {
  entry: OngoingEntry;
  look: Look;
  inFlight: RefObject<boolean>;
  /** Another entry is being converted: this one cannot start. */
  locked: boolean;
  onActive: (active: boolean) => void;
  onSkip: () => void;
  onConverted: (entry: OngoingEntry, result: ConvertResult) => void;
};

/** One convertible entry: name, destination (not for links), Preview → Apply. */
function EntryRow({ entry, look, inFlight, locked, onActive, onSkip, onConverted }: RowProps) {
  const preview = useConvertPreview();
  const convert = useConvert();
  const [name, setName] = useState(entry.suggested_name);
  // "Star it": a link or a real file becomes a ★ Ongoing file instead (a real folder
  // cannot be starred: it becomes a collection). A single file defaults to Star it, a
  // folder (or a link to one) to a collection: no one-file collections by default.
  const canStar = entry.kind !== "folder";
  const [star, setStar] = useState(canStar && !entry.is_dir);
  const choiceName = useId();
  const [destination, setDestination] = useState("");
  // A real folder (or file) can send its files to the inbox instead, to be filed one by
  // one: they land flat in ##. Organize, and stay members of the collection
  const [toInbox, setToInbox] = useState(false);
  const whereName = useId();
  const [pickText, setPickText] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const generation = useRef(0); // an answer for an earlier state of the fields is dropped
  const nameId = useId();
  const groupId = useId();
  const hasFiles = entry.kind !== "link";
  const canInbox = hasFiles && !star; // a ★ file is linked from its archive folder
  const inbox = canInbox && toInbox;
  const needsDestination = hasFiles && !inbox;

  // Editing any field discards the preview: what was previewed is what is applied.
  const edit = (change: () => void) => {
    change();
    generation.current += 1;
    setPending(null);
    setStale(false);
    setError(null);
  };
  const body = (): ConvertBody => ({
    rel: entry.rel,
    collection: star ? "" : name.trim(),
    destination: needsDestination ? destination.trim() : null,
    star,
    to_inbox: inbox,
  });
  const ready =
    (star || name.trim() !== "") && (!needsDestination || destination.trim() !== "");
  /** Why Preview is disabled, said next to it (a disabled button explains nothing). */
  const notReady =
    !star && name.trim() === "" ? NEEDS_NAME : needsDestination && destination.trim() === "" ? NEEDS_FOLDER : null;
  const reasonId = useId();
  const busy = preview.isPending || convert.isPending || locked;

  const start = async () => {
    if (inFlight.current || !ready) return;
    inFlight.current = true;
    setError(null);
    setStale(false);
    const snapshot = body();
    const mine = generation.current;
    onActive(true);
    try {
      const plan = await preview.mutateAsync(snapshot);
      if (generation.current === mine) setPending({ body: snapshot, plan });
    } catch (e) {
      if (generation.current === mine) setError(errorText(e));
    } finally {
      inFlight.current = false;
      onActive(false);
    }
  };

  const apply = async (p: Pending) => {
    if (inFlight.current) return;
    inFlight.current = true;
    onActive(true);
    try {
      const result = await convert.mutateAsync({
        ...p.body,
        fingerprint: p.plan.fingerprint,
      });
      setPending(null);
      onConverted(entry, result);
    } catch (e) {
      setPending(null);
      setError(errorText(e));
      setStale(e instanceof ApiError && e.code === STALE_CODE);
    } finally {
      inFlight.current = false;
      onActive(false);
    }
  };

  return (
    <li className="ongoing-entry">
      <EntryHeader entry={entry} look={look} />
      {entry.kind === "link" && entry.target_rel && (
        <p className="ongoing-entry-what">
          Links to <code>{visible(entry.target_rel)}</code>
        </p>
      )}
      {entry.kind === "folder" && entry.contents.length > 0 && <FolderItems entry={entry} look={look} />}
      {canStar && (
        <div className="convert-choice" role="radiogroup" aria-label="Convert into">
          <label>
            <input type="radio" name={choiceName} checked={!star} onChange={() => edit(() => setStar(false))} />
            A collection
          </label>
          <label>
            <input type="radio" name={choiceName} checked={star} onChange={() => edit(() => setStar(true))} />
            Star it (★ Ongoing)
          </label>
        </div>
      )}
      <div className="ongoing-entry-form">
        {star ? (
          <p className="hint ongoing-star-hint">
            {entry.kind === "link"
              ? "Its file becomes a ★ Ongoing file; the app's own link takes this one's place."
              : "The file moves to the archive folder below and becomes a ★ Ongoing file, linked from here."}
          </p>
        ) : (
        <div className="ongoing-collection-fields" role="group" aria-labelledby={groupId}>
          <p id={groupId} className="ongoing-fields-title">
            Collection: new name <strong>or</strong> an existing one (one is needed)
          </p>
          <div className="field">
            <label htmlFor={nameId}>Collection name</label>
            <input
              id={nameId}
              value={name}
              maxLength={COLLECTION_NAME_MAX}
              spellCheck={false}
              aria-required="true"
              onChange={(e) => edit(() => setName(e.target.value))}
            />
          </div>
          <CollectionPicker
            single
            label="Or use an existing collection"
            value={[]}
            onChange={(names) => edit(() => setName(names[0] ?? name))}
            text={pickText}
            onTextChange={setPickText}
          />
        </div>
        )}
        {canInbox && (
          <div className="convert-choice" role="radiogroup" aria-label="Where it goes">
            <label>
              <input type="radio" name={whereName} checked={!toInbox} onChange={() => edit(() => setToInbox(false))} />
              {entry.kind === "folder" ? "Move its files to one archive folder" : "Move it to an archive folder"}
            </label>
            <label>
              <input type="radio" name={whereName} checked={toInbox} onChange={() => edit(() => setToInbox(true))} />
              {entry.kind === "folder"
                ? "Send its files to the inbox to file one by one"
                : "Send it to the inbox to file later"}
            </label>
          </div>
        )}
        {needsDestination && (
          <FolderPicker
            label="Archive folder (required)"
            required
            refuse={CONVERT_REFUSES}
            value={destination}
            onChange={(folder) => edit(() => setDestination(folder))}
          />
        )}
      </div>
      <div className="actions">
        {notReady && (
          <p id={reasonId} className="hint ongoing-preview-reason">
            {notReady}
          </p>
        )}
        <button type="button" disabled={busy} onClick={onSkip}>
          Skip
        </button>
        <button
          type="button"
          className="primary"
          disabled={!ready || busy}
          aria-describedby={notReady ? reasonId : undefined}
          onClick={() => void start()}
        >
          Preview
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {visible(error)}{" "}
          {stale && (
            <button type="button" disabled={busy} onClick={() => void start()}>
              Preview again
            </button>
          )}
        </p>
      )}
      {pending && (
        <ConfirmPlan
          planKey={snapshotKey(pending)}
          title={`Convert ${visible(entry.rel)}?`}
          ops={pending.plan.ops}
          busy={convert.isPending}
          confirmLabel={pending.body.star ? "Star" : "Convert"}
          intro={
            <>
              <p>
                {pending.body.star
                  ? "Star it: becomes a ★ Ongoing file"
                  : pending.plan.existing
                  ? `Add to existing collection ‘${visible(pending.plan.collection)}’ (${plural(pending.plan.existing_members, "file")})`
                  : `New collection ‘${visible(pending.plan.collection)}’`}
              </p>
              {pending.plan.notes.map((n) => (
                <p key={n} className="notice">
                  {visible(n)}
                </p>
              ))}
              <p>{plural(pending.plan.members.length, "member")}:</p>
              <ul>
                {pending.plan.members.map((m) => (
                  <li key={m}>
                    <code>{visible(m)}</code>
                  </li>
                ))}
              </ul>
            </>
          }
          onConfirm={() => void apply(pending)}
          onCancel={() => setPending(null)}
        />
      )}
    </li>
  );
}

export function GreyEntry({ entry, look }: { entry: OngoingEntry; look: Look }) {
  return (
    <li className="ongoing-entry greyed">
      <EntryHeader entry={entry} look={look} />
      {entry.problem ? (
        <p className="ongoing-entry-what">{visible(entry.problem)}</p>
      ) : entry.collection_id !== null ? (
        <p className="ongoing-entry-what">
          Managed by collection{" "}
          <Link to={`/collections/${entry.collection_id}`}>{visible(entry.collection_name ?? "")}</Link>
        </p>
      ) : (
        <p className="ongoing-entry-what">Managed by a collection.</p>
      )}
    </li>
  );
}

/** Quick Look over the entries shown (in page order): from a row's button, or Space on
 * a focused lookable row; never while a convert call is in flight. */
export function useEntryQuickLook(shown: OngoingEntry[], inFlight: RefObject<boolean>): { look: Look; view: ReactNode } {
  const [lookAt, setLookAt] = useState(0);
  const looks = lookables(shown);
  const lookIndex = new Map(looks.map((l, i) => [l.key, i]));
  const byButton = useRef(false); // the Quick Look button of a row, not Space
  const quickLook = useQuickLook(
    looks.map((l) => l.file),
    lookAt,
    setLookAt,
    {
      // never over a convert call in flight; Space only on a focused lookable row
      // (anywhere else, Space is the page's or the focused control's own)
      canOpen: () => {
        if (inFlight.current) return false;
        if (byButton.current) return true;
        const el = document.activeElement;
        const key = el instanceof HTMLElement && el.matches("[data-quicklook]") ? el.dataset.look : undefined;
        const i = key === undefined ? undefined : lookIndex.get(key);
        if (i === undefined) return false;
        setLookAt(i);
        return true;
      },
    },
  );
  const look: Look = (key) => {
    const i = lookIndex.get(key);
    if (i === undefined) return undefined;
    return () => {
      setLookAt(i);
      byButton.current = true;
      try {
        quickLook.open();
      } finally {
        byButton.current = false;
      }
    };
  };

  return { look, view: quickLook.view };
}

export default function ConvertOngoing() {
  const entries = useOngoingEntries();
  const toast = useToast();
  const inFlight = useRef(false); // one conversion at a time, even before buttons disable
  const [active, setActive] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [showSkipped, setShowSkipped] = useState(false);
  const [done, setDone] = useState<Done[]>([]);
  const undo = useUndoConfirm((batchId) => setDone((d) => d.filter((x) => x.batchId !== batchId)));
  useBlockToastActions(undo.target !== null || undo.pending);
  const all = entries.data ?? [];
  const ready = all.filter((e) => !e.managed && !e.problem);
  const convertible = ready.filter((e) => showSkipped || !skipped.has(e.rel));
  const skippedCount = ready.filter((e) => skipped.has(e.rel)).length;
  const problems = all.filter((e) => !e.managed && e.problem);
  const managed = all.filter((e) => e.managed);
  const { look, view: quickLookView } = useEntryQuickLook([...convertible, ...problems, ...managed], inFlight);

  if (entries.data === undefined) {
    return (
      <section className="ongoing-convert">
        <Toolbar title="Convert ##. Ongoing" />
        <div className="ongoing-body">
          {entries.isError ? (
            <p className="error" role="alert">
              Could not load ##. Ongoing. {visible(errorText(entries.error))}
            </p>
          ) : (
            <p className="placeholder">Loading…</p>
          )}
        </div>
      </section>
    );
  }

  /** The same guarded undo as the toast's button. */
  const startUndo = (batchId: string) => {
    if (inFlight.current || undo.undoing.current) return;
    undo.open({ batchId });
  };

  const converted = (entry: OngoingEntry, result: ConvertResult) => {
    const view: View = {
      problems: [...result.problems, ...(result.sync?.problems ?? [])],
      batch: result.batch,
      ongoing_status: null,
    };
    const { problems: lines } = changeLines(view);
    const title = `Converted ${entry.rel}`;
    setDone((d) => [{ batchId: result.batch.batch_id, title, view }, ...d]);
    toast({
      kind: lines.length > 0 ? "warning" : "info",
      text: lines.length > 0 ? `${title}, but: ${lines.join("; ")}` : title,
      action:
        result.batch.done.length === 0
          ? undefined
          : {
              label: "Undo",
              run: () => startUndo(result.batch.batch_id),
            },
    });
  };

  return (
    <section className="ongoing-convert">
      <Toolbar
        title="Convert ##. Ongoing"
        subtitle={`${plural(convertible.length, "entry", "entries")} to convert`}
        actions={
          skippedCount > 0 && (
            <button type="button" onClick={() => setShowSkipped((v) => !v)}>
              {showSkipped ? "Hide skipped" : `Show skipped (${skippedCount})`}
            </button>
          )
        }
      />
      <div className="ongoing-body">
        <p className="hint ongoing-intro">
          Turn each entry into a collection. Every conversion is previewed first and can be undone on its own.
        </p>
        {entries.isError && (
          <p className="notice" role="alert">
            The list could not be refreshed: {visible(errorText(entries.error))}
          </p>
        )}
        {done.map((d) => (
          <LastChange
            key={d.batchId}
            title={d.title}
            result={d.view}
            onUndo={d.view.batch && d.view.batch.done.length > 0 ? () => startUndo(d.batchId) : undefined}
          />
        ))}
        {convertible.length === 0 && (
          <EmptyState icon={<CircleCheck size={40} strokeWidth={1.25} />} title="Nothing left to convert." />
        )}
        <ul className="ongoing-list">
          {convertible.map((e) => (
            <EntryRow
              key={e.rel}
              entry={e}
              look={look}
              inFlight={inFlight}
              locked={active !== null && active !== e.rel}
              onActive={(on) => setActive(on ? e.rel : null)}
              onSkip={() => setSkipped((s) => new Set(s).add(e.rel))}
              onConverted={converted}
            />
          ))}
        </ul>
        {problems.length > 0 && (
          <>
            <h3 className="ongoing-section-title">Can't be converted</h3>
            <ul className="ongoing-list ongoing-others" aria-label="Can't be converted">
              {problems.map((e) => (
                <GreyEntry key={e.rel} entry={e} look={look} />
              ))}
            </ul>
          </>
        )}
        {managed.length > 0 && (
          <>
            <h3 className="ongoing-section-title">Already managed</h3>
            <p className="hint ongoing-section-hint">These are the app's own links and folders; nothing to do</p>
            <ul className="ongoing-list ongoing-others" aria-label="Already managed">
              {managed.map((e) => (
                <GreyEntry key={e.rel} entry={e} look={look} />
              ))}
            </ul>
          </>
        )}
      </div>
      {quickLookView}
    </section>
  );
}
