/** One collection, as a Mac window's content: a toolbar (+ Group, Show in Finder,
 * Export, ⋯ with rename, "Show in ##. Ongoing" and close/reopen), the summary, a
 * "Needs attention" strip, the members as a tree of groups, the note and checklist,
 * and the selected file in a side panel (Space opens Quick Look).
 *
 * Rename, publish and close/reopen are previewed first (the exact ops in a
 * ConfirmPlan) and then applied; the apply re-plans and syncs, so what is shown
 * afterwards is the batch the API returns, never the preview. Member and group changes
 * (add, remove, move between groups, create, rename, move or remove a group) only
 * change the database and the app-owned links in ##. Ongoing (journaled), so they run
 * at once, as member changes always did; removing a group asks first, because its
 * files and subgroups move up. Members are referenced, never moved.
 *
 * A collection can sit inside another: the page shows where (a path of links) and its
 * own collections above its members. "Move to…" (the keyboard way of a sidebar drag)
 * and "New collection inside…" are in the ⋯ menu; a move runs at once, as group
 * changes do, and shows the batch that ran. */
import { Ellipsis, Eye, FolderOpen, FolderPlus, Layers, Share, Sparkles } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useStyle } from "../appearance";
import {
  archiveKey,
  type CollectionAction,
  type CollectionChange,
  type CollectionRow,
  type CollectionSummaryAnswer,
  type DirEntry,
  errorText,
  type ExportFormat,
  type ExportResult,
  exportUrl,
  type Group,
  type GroupChange,
  type Member,
  type ResolvedOp,
  useCollection,
  useCollectionAttention,
  useCollectionChange,
  useCollectionMembers,
  useCollectionPreview,
  useCollections,
  useCreateCollection,
  useExport,
  useGroupChange,
  useSetCollectionParent,
  LOCKED_REASON,
  useIsBlocked,
  useStatus,
} from "../api/client";
import { AIProposal } from "../components/ai/AIProposal";
import { AIHint, useAISend, useAIState } from "../components/ai/useAI";
import { AddFile } from "../components/AddFile";
import { Banner } from "../components/Banner";
import { Checklist } from "../components/Checklist";
import { Collapsible, firstLine } from "../components/Collapsible";
import { COLLECTION_NAME_MAX } from "../components/CollectionPicker";
import { changeToast, CLOSE_CHILDREN_FIRST, NOT_SHOWN } from "../components/collectionText";
import {
  childrenOf,
  endCollectionMove,
  holdsText,
  inTreeOrder,
  movedText,
  recreatedLinks,
  recreatedNote,
  PATH_SEP,
  pathLabel,
  pathOf,
  startCollectionMove,
  subtreeOf,
} from "../components/collectionTree";
import { CopyButton } from "../components/CopyButton";
import { FileDetails } from "../components/FileDetails";
import { useCollectionOrder } from "../components/useCollectionOrder";
import {
  attentionTags,
  type FoldKey,
  freeName,
  type GroupProposals,
  GroupTree,
  groupPaths,
  browseHref,
  memberName,
  treeOf,
  visibleMembers,
} from "../components/GroupTree";
import { LastChange } from "../components/LastChange";
import { BUILTIN_LABEL } from "../components/MarkIcons";
import { FileActionBar, type FileActionBarProps, useAskAction } from "../components/FileActionBar";
import { FileActionIcons } from "../components/FileActionIcons";
import { type FilingAI, useFilingAI } from "../components/ai/useFilingAI";
import { allMarked, useBatchMark } from "../components/useBatchMark";
import { toDeleteReason } from "../toDelete";
import { usePutInTrayEntries } from "./FileActions";
import { ConfirmPlan, snapshotKey } from "../components/PlanPreview";
import { RelativeDate, useLocalToday } from "../components/RelativeDate";
import { SavedNote, SaveState } from "../components/SavedNote";
import { type ToastAction, useToast } from "../components/Toasts";
import {
  backToInbox,
  deletionRefusal,
  inboxRefusal,
  MOVE_BUSY,
  MoveToSheet,
  sourceRefusal,
  useInboxFolder,
  useMoveFlow,
  anyMoveRunning,
} from "../components/MoveTo";
import { type RestoreTo, restoreEntries, useRestoreFlow } from "../components/Restore";
import { type AssignKind, AssignSheet } from "../components/zones/FromFor";
import { isTrashKey, useTrash } from "../components/Trash";
import { EmptyState } from "../components/ui/EmptyState";
import { IconButton } from "../components/ui/IconButton";
import { Menu, type MenuEntry } from "../components/ui/Menu";
import { Sheet } from "../components/ui/Sheet";
import { ClickToEdit } from "../components/ui/ClickToEdit";
import { Tag } from "../components/ui/Tag";
import { Toolbar } from "../components/ui/Toolbar";
import { useAutoGrow } from "../components/useAutoGrow";
import { useAutoSave } from "../components/useAutoSave";
import { type QLFile, useQuickLook } from "../components/useQuickLook";
import { FileMeta } from "../components/FileMeta";
import { FilePanel } from "./FilePanel";
import { Splitter, useSplitWidth } from "../components/ui/SplitPane";
import { dayOf, formatDate, formatSize, plural } from "../format";
import { isShortcut, useKeydown } from "../keyboard";
import { publishSelection } from "../selection";
import { inFileManager, showInLabel } from "../fileManager";
import { visible } from "../text";
import { baseName, extOf } from "../paths";

type Pending = { action: CollectionAction; ops: ResolvedOp[]; title: string; label: string; done: string };

const ICON = { size: 18, strokeWidth: 1.75 } as const;
const STILL_RUNNING = "Another change is still running. Try again when it is done.";


type ExportState =
  | { kind: "idle" }
  | { kind: "confirm"; format: ExportFormat; result: ExportResult }
  | { kind: "done"; format: ExportFormat; result: ExportResult }
  | { kind: "error"; text: string };

const FORMAT_LABEL: Record<ExportFormat, string> = { zip: "zip", pdf: "PDF" };

/** Export as a zip or one PDF; a large one asks first; then a download link. */
function Export({ id, onBusy }: { id: number; onBusy?: (busy: boolean) => void }) {
  const ids = useId();
  const exporting = useExport();
  const [format, setFormat] = useState<ExportFormat>("zip");
  const [state, setState] = useState<ExportState>({ kind: "idle" });
  const inFlight = useRef(false); // one export at a time, even before the button disables
  const run = async (fmt: ExportFormat, confirmLarge: boolean) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setState({ kind: "idle" });
    try {
      const result = await exporting.mutateAsync({ id, format: fmt, confirm_large: confirmLarge });
      setState({ kind: result.needs_confirm ? "confirm" : "done", format: fmt, result });
    } catch (e) {
      setState({ kind: "error", text: errorText(e) });
    } finally {
      inFlight.current = false;
    }
  };
  const busy = exporting.isPending;
  useEffect(() => onBusy?.(busy), [busy, onBusy]);
  return (
    <section className="export" aria-labelledby={`${ids}-h`}>
      <h3 id={`${ids}-h`}>Export</h3>
      <div className="tray-filter" role="radiogroup" aria-label="Format">
        {(["zip", "pdf"] as const).map((f) => (
          <label key={f}>
            <input
              type="radio"
              name={`${ids}-format`}
              value={f}
              checked={format === f}
              disabled={busy}
              onChange={() => {
                setFormat(f);
                setState({ kind: "idle" }); // an estimate or a link is for the other format
              }}
            />{" "}
            {f === "zip" ? "Zip of the files" : "One combined PDF"}
          </label>
        ))}
      </div>
      <div className="actions">
        <button type="button" disabled={busy} onClick={() => void run(format, false)}>
          Export
        </button>
      </div>
      {busy && (
        <p className="busy" role="status">
          Building the export… this can take a while.
        </p>
      )}
      {state.kind === "confirm" && (
        <div className="notice">
          <p>
            This {FORMAT_LABEL[state.format]} would be about {formatSize(state.result.size)}. Export it anyway?
          </p>
          <div className="actions">
            <button type="button" onClick={() => setState({ kind: "idle" })}>
              Cancel
            </button>
            <button type="button" className="primary" disabled={busy} onClick={() => void run(state.format, true)}>
              Export anyway
            </button>
          </div>
        </div>
      )}
      {state.kind === "done" && state.result.token && (
        <p>
          <a href={exportUrl(state.result.token)} download>
            Download the {FORMAT_LABEL[state.format]}
          </a>{" "}
          ({formatSize(state.result.size)})
        </p>
      )}
      {state.kind === "done" && state.result.not_included.length > 0 && (
        <>
          <p>Not included:</p>
          <ul className="file-list" aria-label="Not included">
            {state.result.not_included.map((n, i) => (
              <li key={i}>
                <code>{visible(n.path)}</code> — {visible(n.reason)}
              </li>
            ))}
          </ul>
        </>
      )}
      {state.kind === "error" && (
        <p className="error" role="alert">
          Export failed. {visible(state.text)}
        </p>
      )}
    </section>
  );
}

/** The collection's name, renamed in place in the toolbar (as in Finder): Enter
 * previews the rename (it can rename its ##. Ongoing folder), Esc cancels, and leaving
 * the field keeps what was typed there (an unchanged name just closes it). */
function RenameField({ name, busy, onSave, onCancel }: { name: string; busy: boolean; onSave: (name: string) => void; onCancel: () => void }) {
  const [text, setText] = useState(name);
  const input = useRef<HTMLInputElement>(null);
  // opens with the whole name selected: typing replaces it
  useEffect(() => input.current?.select(), []);
  return (
    <input
      ref={input}
      className="toolbar-rename"
      aria-label="Collection name"
      value={text}
      autoFocus
      disabled={busy}
      maxLength={COLLECTION_NAME_MAX}
      spellCheck={false}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        if (text.trim() === name) onCancel();
      }}
      onKeyDown={(e) => {
        e.stopPropagation(); // page shortcuts never see keys typed here
        if (e.key === "Enter") {
          e.preventDefault();
          onSave(text);
        } else if (e.key === "Escape") {
          e.preventDefault();
          onCancel();
        }
      }}
    />
  );
}

/** The collection's summary: a text field saved on blur. "Summarize with AI" (``ai``)
 * proposes one (``proposal``, with Use or Discard) and a line per group. */
function Summary({
  id,
  value,
  save,
  ai,
  proposal,
}: {
  id: number;
  value: string;
  save: (change: GroupChange) => Promise<CollectionChange>;
  ai?: ReactNode;
  proposal?: ReactNode;
}) {
  const fieldId = useId();
  const ref = useRef<HTMLTextAreaElement>(null);
  const auto = useAutoSave(value, async (summary: string) => (await save({ op: "summary", id, summary })).collection.summary);
  useAutoGrow(ref, auto.shown);
  const [look] = useStyle();
  const [editing, setEditing] = useState(false);
  if (look === "new") {
    // As drawn: a heading with Summarize with AI… and Edit, then the text as a paragraph; Edit opens the field.
    const showField = editing || auto.status?.kind === "error";
    return (
      <section className="collection-summary-new" aria-labelledby={`${fieldId}-h`}>
        <div className="section-head">
          <h2 id={`${fieldId}-h`}>Summary</h2>
          {ai && <div className="collection-summary-tools">{ai}</div>}
          <button type="button" className="link-button" aria-expanded={showField} onClick={() => setEditing((e) => !e)}>
            {showField ? "Done" : "Edit"}
          </button>
        </div>
        {showField ? (
          <>
            <label htmlFor={fieldId} className="visually-hidden">
              Summary
            </label>
            <textarea
              id={fieldId}
              ref={ref}
              className="collection-summary-text"
              rows={3}
              maxLength={4000}
              autoFocus={editing}
              placeholder="What is this collection about? Where does it stand?"
              value={auto.shown}
              onChange={(e) => auto.change(e.target.value)}
              onBlur={() => void auto.commit()}
            />
          </>
        ) : (
          <p className={auto.shown.trim() ? "summary-text" : "summary-text is-empty"}>{auto.shown.trim() ? visible(auto.shown) : "No summary yet."}</p>
        )}
        <SaveState status={auto.status} />
        {proposal}
        <AIHint what="to summarize" />
      </section>
    );
  }
  return (
    <Collapsible name="summary" title="Summary" className="collection-summary" hint={firstLine(auto.shown) || "No summary yet"}>
      <div className="collection-summary-head">
        <label htmlFor={fieldId} className="visually-hidden">
          Summary
        </label>
        {ai && <div className="collection-summary-tools">{ai}</div>}
      </div>
      <textarea
        id={fieldId}
        ref={ref}
        className="collection-summary-text"
        rows={2}
        maxLength={4000}
        placeholder="What is this collection about? Where does it stand?"
        value={auto.shown}
        onChange={(e) => auto.change(e.target.value)}
        onBlur={() => void auto.commit()}
      />
      <SaveState status={auto.status} />
      {proposal}
      <AIHint what="to summarize" />
    </Collapsible>
  );
}

/** summarize-collection's answer, not saved yet: the collection's line and one per
 * group (by group id), each dropped on Use or Discard. */
type Proposal = { id: number; summary: string | null; groups: Record<string, string> };
/** A Use that would overwrite a summary already there: asked first. */
type Replacing = { target: "collection" | Group; text: string };

/** The "Needs attention" strip: a tag per open tray item of a member, and one per
 * member still in the inbox; a click selects that member. Hidden when nothing needs it. */
function Attention({
  members,
  attention,
  onSelect,
}: {
  members: Member[];
  attention: ReturnType<typeof useCollectionAttention>["data"];
  onSelect: (driveId: string) => void;
}) {
  const [look] = useStyle();
  if (!attention || attention.length === 0) return null;
  const byId = new Map(members.map((m) => [m.drive_id, m]));
  if (look === "new") {
    // As drawn: a list, a pill (the tray and its date, or "In inbox") and the item or file as a link
    return (
      <section className="attention-list" aria-label="Needs attention">
        <h2>Needs attention</h2>
        <ul>
          {attention.flatMap((a) => {
            const m = byId.get(a.drive_id);
            const name = m ? memberName(m) : visible(a.drive_id);
            return attentionTags(a, { long: true }).map((t) => {
              const item = a.items.find(({ item: i }) => `i${i.id}` === t.key)?.item;
              return (
                <li key={`${a.drive_id}-${t.key}`}>
                  <Tag tone={t.tone}>{item ? visible(`${item.tray_name}${item.date ? ` · ${formatDate(item.date)}` : ""}`) : "In inbox"}</Tag>
                  <button type="button" className="link-button" onClick={() => onSelect(a.drive_id)} title={name}>
                    {item ? visible(item.title) : name}
                  </button>
                </li>
              );
            });
          })}
        </ul>
      </section>
    );
  }
  return (
    <section className="attention-strip" aria-label="Needs attention">
      <span className="collection-caption">Needs attention</span>
      <ul>
        {attention.flatMap((a) => {
          const m = byId.get(a.drive_id);
          const name = m ? memberName(m) : visible(a.drive_id);
          return attentionTags(a, { long: true }).map((t) => (
            <li key={`${a.drive_id}-${t.key}`}>
              <button type="button" className="attention-chip" onClick={() => onSelect(a.drive_id)} title={name}>
                <Tag tone={t.tone}>{t.key === "inbox" ? `In inbox: ${name}` : t.text}</Tag>
              </button>
            </li>
          ));
        })}
      </ul>
    </section>
  );
}

/** Close to the server's ``casefold`` (enough to filter a list here). */
const fold = (text: string) => text.trim().normalize("NFC").toLowerCase();

/** Where the collection sits: its parents as links, top first. A name the list does
 * not know (still loading) is plain text. */
function Where({ c, all }: { c: { id: number; path: string[]; name: string }; all: CollectionRow[] }) {
  const parents = pathOf(c).slice(0, -1);
  if (parents.length === 0) return null;
  return (
    <nav className="collection-where" aria-label="Inside">
      In{" "}
      {parents.map((name, i) => {
        const at = all.find((x) => x.name === name);
        return (
          <span key={i}>
            {i > 0 && PATH_SEP}
            {at ? <Link to={`/collections/${at.id}`}>{visible(name)}</Link> : visible(name)}
          </span>
        );
      })}
    </nav>
  );
}

/** The collection's own collections (open and closed), each with its counts. */
/** A child collection's counts on its parent's page, typed as on the child's own page
 * ("1 file, 1 folder"), then its collections, groups and open checks. */
function childCounts(c: CollectionRow, collections = 0): string {
  const parts = [holdsText(c, c.files)];
  if (collections > 0) parts.push(plural(collections, "collection"));
  if (c.groups.length > 0) parts.push(plural(c.groups.length, "group"));
  if (c.open_checks > 0) parts.push(plural(c.open_checks, "open check"));
  return parts.join(" · ");
}

function ChildCollections({ id, all }: { id: number; all: CollectionRow[] }) {
  const headingId = useId();
  const kids = childrenOf(all);
  const children = kids.get(id) ?? [];
  if (children.length === 0) return null;
  return (
    <section className="collection-children" aria-labelledby={headingId}>
      <h3 id={headingId} className="collection-caption">
        Collections
      </h3>
      <ul className="collection-list">
        {children.map((child) => (
          <li key={child.id}>
            <article className="collection-row" aria-label={visible(child.name)}>
              <Layers className="collection-row-icon" size={16} strokeWidth={1.75} aria-hidden="true" />
              <div className="collection-row-main">
                <p className="collection-row-title">
                  <Link to={`/collections/${child.id}`}>{visible(child.name)}</Link>
                </p>
                <p className="collection-row-meta">{childCounts(child, (kids.get(child.id) ?? []).length)}</p>
              </div>
              {child.state === "closed" && <Tag tone="grey">Closed</Tag>}
            </article>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** "Move to…": the top level or an open collection, never the collection itself or
 * one inside it (the server refuses those too). The keyboard way of a sidebar drag. */
function MoveSheet({
  c,
  open,
  busy,
  onMove,
  onCancel,
}: {
  c: { id: number; name: string; parent_id: number | null };
  open: CollectionRow[];
  busy: boolean;
  /** The new parent and its name (null: the top level). */
  onMove: (parentId: number | null, name: string | null) => void;
  onCancel: () => void;
}) {
  const ids = useId();
  const [needle, setNeedle] = useState("");
  const [choice, setChoice] = useState<number | null>(c.parent_id);
  const own = useMemo(() => subtreeOf(open, c.id), [open, c.id]); // itself and everything under it
  const candidates = inTreeOrder(open)
    .filter((x) => !own.has(x.id))
    .filter((x) => !fold(needle) || fold(pathLabel(x)).includes(fold(needle)));
  const name = visible(c.name);
  return (
    <Sheet
      open
      className="move-collection"
      title={`Move ${name} to…`}
      onClose={onCancel}
      onKeyDown={(e) => e.stopPropagation()} // page shortcuts never see keys typed here
      footer={
        <>
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" form={`${ids}-form`} className="primary" disabled={busy || choice === c.parent_id}>
            Move
          </button>
        </>
      }
    >
      <form
        id={`${ids}-form`}
        onSubmit={(e) => {
          e.preventDefault();
          if (!busy && choice !== c.parent_id) onMove(choice, open.find((x) => x.id === choice)?.name ?? null);
        }}
      >
        <div className="field">
          <label htmlFor={`${ids}-find`}>Find a collection</label>
          <input
            id={`${ids}-find`}
            type="search"
            autoFocus
            spellCheck={false}
            autoComplete="off"
            value={needle}
            onChange={(e) => setNeedle(e.target.value)}
          />
        </div>
        <fieldset className="move-collection-choices">
          <legend className="visually-hidden">Move inside</legend>
          <label>
            <input type="radio" name={`${ids}-parent`} checked={choice === null} onChange={() => setChoice(null)} />
            Top level
          </label>
          {candidates.map((x) => (
            <label key={x.id}>
              <input type="radio" name={`${ids}-parent`} checked={choice === x.id} onChange={() => setChoice(x.id)} />
              {visible(pathLabel(x))}
            </label>
          ))}
        </fieldset>
        {candidates.length === 0 && needle.trim() && <p className="hint">No open collection matches.</p>}
      </form>
      <p className="hint">Its collections, groups and members go with it. Moving it back reverses it.</p>
    </Sheet>
  );
}

/** "New collection inside…": a name; Enter or Create makes it and opens it. */
function NewChildSheet({
  parent,
  onCreated,
  onCancel,
}: {
  parent: { id: number; name: string };
  onCreated: (child: { id: number; name: string }) => void;
  onCancel: () => void;
}) {
  const ids = useId();
  const create = useCreateCollection();
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const inFlight = useRef(false); // Enter and a click (or two clicks) create one collection
  const submit = async () => {
    const name = text.trim();
    if (!name || inFlight.current) return;
    inFlight.current = true;
    setProblem(null);
    try {
      onCreated(await create.mutateAsync({ name, parent_id: parent.id }));
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      inFlight.current = false;
    }
  };
  return (
    <Sheet
      open
      title={`New collection inside ${visible(parent.name)}`}
      onClose={onCancel}
      onKeyDown={(e) => e.stopPropagation()}
      footer={
        <>
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" form={`${ids}-form`} className="primary" disabled={!text.trim() || create.isPending}>
            Create
          </button>
        </>
      }
    >
      <form
        id={`${ids}-form`}
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="field">
          <label htmlFor={`${ids}-name`}>Name</label>
          <input
            id={`${ids}-name`}
            value={text}
            autoFocus
            maxLength={COLLECTION_NAME_MAX}
            spellCheck={false}
            placeholder="e.g. Stove"
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        {problem && (
          <p className="error" role="alert">
            {visible(problem)}
          </p>
        )}
      </form>
    </Sheet>
  );
}

/** The New look's block under the collections box: the member's Group (the keyboard way to move
 * it), and two links for what only a collection's panel has: the file's own folder in Browse and
 * a jump to its note. */
function CollectionSection({
  group,
  showButton,
  noteLink,
}: {
  group: ReactNode;
  showButton: ReactNode;
  noteLink: boolean;
}) {
  const toNote = () => {
    const box = document.querySelector<HTMLElement>(".collection-inspector .item-note");
    const toggle = box?.querySelector<HTMLButtonElement>(".collapsible-toggle[aria-expanded='false']");
    toggle?.click(); // a folded note opens first
    requestAnimationFrame(() => box?.querySelector<HTMLTextAreaElement>("textarea")?.focus());
  };
  if (!group && !showButton && !noteLink) return null;
  return (
    <section className="inspector-collection" aria-label="In this collection">
      {group}
      {(showButton || noteLink) && (
        <div className="inspector-links">
          {showButton}
          {noteLink && (
            <button type="button" className="link-button" onClick={toNote}>
              Note on this file
            </button>
          )}
        </div>
      )}
    </section>
  );
}

/** The selected member. A file in the index gets the shared file panel (as in Browse),
 * with Quick Look in its preview's toolbar and, in its own block, its group (the keyboard
 * way to move it). What acts on the file (Put in tray, Remove from collection, Ask AI, ★,
 * !, the bin) is in the page's header (``FileActionBar``). A folder, a missing file, one in
 * To Delete or one not in the index has nothing to preview or edit: its details and the
 * same collection controls. */
function Inspector({
  member,
  groups,
  busy,
  onGroup,
  onQuickLook,
  ai,
  icons,
}: {
  /** The page's Ask AI, whose answer shows in the file's details. */
  ai: FilingAI;
  /** The New look: the file's two icon rows (``FileActionIcons``; in Classic they are in the page's header). */
  icons?: ReactNode;
  member: Member | null;
  groups: { group: Group; path: string }[];
  busy: boolean;
  onGroup: (gid: number | null) => void;
  onQuickLook?: () => void;
}) {
  const selectId = useId();
  const navigate = useNavigate();
  if (!member) {
    return (
      <aside className="collection-inspector" aria-label="Selected file">
        <EmptyState title="No file selected" hint="Select a file to see its details." />
      </aside>
    );
  }
  const name = memberName(member);
  const quickLookButton = onQuickLook && <IconButton icon={<Eye {...ICON} />} label="Quick Look" shortcut="Space" onClick={onQuickLook} />;
  // the file's own folder in Browse, with the file selected (a click on a member keeps the
  // collection's page; Today's Starred card opens Browse on a click)
  const showButton = !member.is_dir && member.path && (
    <button type="button" className={icons !== undefined ? "link-button" : undefined} onClick={() => navigate(browseHref(member.path!, member.drive_id))}>
      Show in folder
    </button>
  );
  // without groups there is nothing to choose (and no "Ungrouped" to show)
  const group = groups.length > 0 && (
    <div className="field inspector-group">
      <label htmlFor={selectId}>Group</label>
      <select
        id={selectId}
        value={member.group_id === null ? "" : String(member.group_id)}
        disabled={busy}
        onChange={(e) => onGroup(e.target.value === "" ? null : Number(e.target.value))}
      >
        <option value="">Ungrouped</option>
        {groups.map(({ group, path }) => (
          <option key={group.id} value={group.id}>
            {visible(path)}
          </option>
        ))}
      </select>
    </div>
  );

  if (member.path && !member.is_dir && !member.missing && !member.quarantined) {
    return (
      <aside className="collection-inspector" aria-label="Selected file">
        <FilePanel
          file={{ ...member, name }}
          preview={{ drive_id: member.drive_id, path: member.path, ext: extOf(member.path), is_link: member.is_link }}
          disabled={busy}
          view={quickLookButton}
          headerActions={{ ai }}
          compactRelatives
          actions={icons}
          extras={
            icons !== undefined ? (
              <CollectionSection group={group} showButton={showButton} noteLink />
            ) : (
              (group || showButton) && (
                <section className="inspector-collection" aria-label="In this collection">
                  {group}
                  {showButton && <div className="inspector-actions">{showButton}</div>}
                </section>
              )
            )
          }
        />
      </aside>
    );
  }

  /** Quick Look, with Show in Browse for a folder (the file actions are in the header). */
  const actions = () => (
    <div className="inspector-actions">
      {quickLookButton}
      {member.is_dir && member.path && !member.missing && (
        <button type="button" onClick={() => navigate(`/browse?path=${encodeURIComponent(member.path!)}`)}>
          Show in Browse
        </button>
      )}
      {showButton}
    </div>
  );
  const notice = (member.missing || member.quarantined) && (
    <p className="notice">{member.missing ? "The file is missing." : "The file is in ##. To Delete."}</p>
  );
  return (
    <aside className="collection-inspector" aria-label="Selected file">
      {icons}
      {member.path && (member.missing || member.quarantined) ? (
        <>
          <FileDetails file={{ drive_id: member.drive_id, name: null, path: member.path }} />
          {notice}
          {group}
          {actions()}
        </>
      ) : member.path ? (
        // a folder: its name and path (its Rename and Move to… say why they are off)
        <FileMeta key={member.drive_id} file={{ ...member, name }} disabled={busy} ai={ai}>
          {(meta) => (
            <>
              {meta.header}
              <FileDetails file={{ drive_id: member.drive_id, name: null, path: member.path ?? "" }} identity={false} />
              {group}
              {actions()}
            </>
          )}
        </FileMeta>
      ) : (
        <>
          <p className="hint">{name} is not in the index.</p>
          {group}
          {actions()}
        </>
      )}
    </aside>
  );
}

/** A file inside a folder member, selected in the list: it is not a member itself, so
 * there is no group or removing; otherwise the shared file panel, as for a member. */
function EntryInspector({
  entry,
  busy,
  onQuickLook,
  ai,
  icons,
}: {
  entry: DirEntry;
  busy: boolean;
  onQuickLook: () => void;
  ai: FilingAI;
  /** The New look: the file's two icon rows. */
  icons?: ReactNode;
}) {
  const folder = entry.path.includes("/") ? entry.path.slice(0, entry.path.lastIndexOf("/")) : "";
  return (
    <aside className="collection-inspector" aria-label="Selected file">
      <FilePanel
        file={entry}
        preview={{ drive_id: entry.drive_id, path: entry.path, ext: extOf(entry.path), is_link: entry.is_link }}
        disabled={busy}
        intro={<p className="hint">In the folder {visible(folder)}, which is in this collection. The file itself is not a member.</p>}
        view={<IconButton icon={<Eye {...ICON} />} label="Quick Look" shortcut="Space" onClick={onQuickLook} />}
        headerActions={{ ai }}
        actions={icons}
      />
    </aside>
  );
}

/** Why Trash refuses this member (null: it does not): the bin's disabled reason, and
 * what ⌘⌫ says. */
function trashRefusal(m: Member): string | null {
  if (!m.path) return "The file is not in the index";
  if (m.missing) return "The file is missing";
  if (m.quarantined) return "Already in ##. To Delete";
  if (m.is_dir) return "Folders are moved to To Delete from Browse";
  return deletionRefusal(m.path, m.marks);
}

export default function CollectionDetail({
  id,
  today: fixed,
  banner,
  subtitleExtra,
}: {
  id: number;
  today?: string;
  /** A banner at the top of the page's content column (Important: entries to convert). */
  banner?: ReactNode;
  /** More for the toolbar subtitle, after the count. */
  subtitleExtra?: string;
}) {
  const local = useLocalToday();
  const today = fixed ?? local;
  const split = useSplitWidth(archiveKey("dam.collection.inspectorwidth"), { min: 230, max: Infinity, initial: 380, unit: "px", edge: "end" });
  // The New look: under ~900px of page the side panel leaves the row and opens over the list
  // from the "File details" button; under ~760px Show folder and Export fold into the ⋯ menu.
  const [look] = useStyle();
  const isNew = look === "new";
  const [detailsOpen, setDetailsOpen] = useState(false);
  const query = useCollection(id);
  // where a change of this collection shows: ! Important publishes to its own folder
  const rootName = query.data?.kind === "important" ? "##. Important" : "##. Ongoing";
  const attention = useCollectionAttention(id);
  const preview = useCollectionPreview();
  const change = useCollectionChange();
  const members = useCollectionMembers();
  const groupChange = useGroupChange();
  const setParent = useSetCollectionParent();
  // one list for the path, the child collections and Move to… (the open ones)
  const allCollections = useCollections("all");
  const openCollections = useMemo(() => (allCollections.data ?? []).filter((x) => x.state === "open"), [allCollections.data]);
  const reorder = useCollectionOrder(allCollections.data ?? []);
  const navigate = useNavigate();
  const status = useStatus();
  const [movingTo, setMovingTo] = useState(false);
  const [newChild, setNewChild] = useState(false);
  // Summaries auto-save on their own (one in flight each): a separate mutation, so a
  // summary save never makes the page look busy or blocks a move.
  const summaryChange = useGroupChange();
  const toast = useToast();
  // Trash (the inspector's bin, ⌫ on the list, Quick Look): the selected member's file.
  const trash = useTrash();
  // The header's Back to inbox, Move to…, From…, For… and Restore: Browse's own flows
  // (preview, confirm, Undo), on the file the side panel shows.
  const moveFlow = useMoveFlow();
  const restoring = useRestoreFlow();
  const inbox = useInboxFolder();
  const isBlocked = useIsBlocked();
  const [moveSheet, setMoveSheet] = useState<{ id: string; name: string } | null>(null);
  const [assigning, setAssigning] = useState<{ kind: AssignKind; ids: string[] } | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [removing, setRemoving] = useState<Group | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renamingGroup, setRenamingGroup] = useState<number | null>(null);
  const [finder, setFinder] = useState(false);
  const finderRef = useRef<HTMLSpanElement>(null);
  // The popover closes on Esc or a click outside it, as a Mac popover does.
  useEffect(() => {
    if (!finder) return;
    const away = (e: MouseEvent) => {
      if (!finderRef.current?.contains(e.target as Node)) setFinder(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFinder(false);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [finder]);
  const [exporting, setExporting] = useState(false);
  const [addingFiles, setAddingFiles] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [folded, setFolded] = useState<Set<FoldKey>>(() => new Set());
  const [chosen, setChosen] = useState<string | null>(null);
  // A file inside a folder member that is selected (shown in the side panel instead of a member).
  const [browsed, setBrowsed] = useState<DirEntry | null>(null);
  const [result, setResult] = useState<{ title: string; change: CollectionChange } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false); // a disabled button can lag a click
  const groupWork = useRef<Promise<unknown> | null>(null); // the running group change, for New group to wait on
  const creatingGroup = useRef(false); // New group twice at once adds one
  const latestGroups = useRef<{ all: Group[]; top: Group[] }>({ all: [], top: [] }); // as last rendered
  const busy =
    preview.isPending || change.isPending || members.isPending || groupChange.isPending || setParent.isPending || trash.busy || moveFlow.busy;

  const report = (title: string, done: string, r: CollectionChange, action?: ToastAction) => {
    setResult({ title, change: r });
    toast({ ...changeToast(done, r), action });
  };

  // Undo of a rename goes through the same previewed rename (the toast outlives the
  // page: only a page that is still open can show the preview).
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const renameBack = useRef<(from: string, to: string) => void>(() => {});
  const undoRename = (from: string, to: string) => {
    if (mounted.current) renameBack.current(from, to);
    else {
      navigate(`/collections/${id}`);
      toast({ kind: "info", text: `Use ⋯ › Rename to rename it back to ${to}` });
    }
  };

  const apply = async (p: Omit<Pending, "ops">) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null);
    try {
      const was = query.data?.name ?? "";
      const r = await change.mutateAsync(p.action);
      setPending(null);
      const renamed = p.action.action === "rename" ? p.action.name : null;
      if (renamed !== null) setRenaming(false);
      report(
        `${p.label}: what happened in ##. Ongoing`,
        p.done,
        r,
        renamed !== null && was && was !== renamed ? { label: "Undo", run: () => undoRename(renamed, was) } : undefined,
      );
    } catch (e) {
      setPending(null);
      setError(errorText(e));
    } finally {
      inFlight.current = false;
    }
  };

  /** Preview ``action``; a rename with nothing to change in ##. Ongoing applies at once. */
  const start = async (p: Omit<Pending, "ops">) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null);
    let ops: ResolvedOp[];
    try {
      ops = await preview.mutateAsync(p.action);
    } catch (e) {
      setError(errorText(e));
      return;
    } finally {
      inFlight.current = false;
    }
    if (p.action.action === "rename" && ops.length === 0) void apply(p);
    else setPending({ ...p, ops });
  };

  renameBack.current = (from, to) =>
    void start({
      action: { id, action: "rename", name: to },
      title: `Rename ${from} back to ${to}?`,
      label: "Rename",
      done: `Renamed back to ${to}`,
    });

  /** A group or member change: at once (no preview), one at a time; shows what ran.
   * Null when it did not happen: the reason is shown (an error, or another change
   * still running). */
  const run = async (g: GroupChange, done: string): Promise<CollectionChange | null> => {
    if (inFlight.current) {
      setError(STILL_RUNNING);
      return null;
    }
    inFlight.current = true;
    setError(null);
    try {
      const work = groupChange.mutateAsync(g);
      groupWork.current = work.then(
        () => undefined,
        () => undefined,
      );
      const r = await work;
      report(`${done}: what happened in ${rootName}`, done, r);
      return r;
    } catch (e) {
      setError(errorText(e));
      return null;
    } finally {
      inFlight.current = false;
    }
  };

  /** A summary save (auto-save queues its own requests): a toast only for a problem. */
  const save = useCallback(
    async (g: GroupChange) => {
      const r = await summaryChange.mutateAsync(g);
      const t = changeToast("Summary saved", r);
      if (t.kind === "warning") toast(t);
      return r;
    },
    [summaryChange, toast],
  );

  // -- AI summaries (summarize-collection): proposals only, saved on Use -----------
  const ai = useAIState();
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [replacing, setReplacing] = useState<Replacing | null>(null);
  const [usingBusy, setUsingBusy] = useState(false);
  const using = useRef(false); // one Use at a time, even before the buttons disable
  const summarize = useAISend<CollectionSummaryAnswer>("summarize-collection", (data) =>
    setProposal({ id, summary: data.summary.trim() || null, groups: data.per_group }),
  );
  // AI switched off: no proposal (or its Use / Discard) is shown
  const shownProposal = ai.on && proposal?.id === id ? proposal : null;
  const dropProposal = (target: "collection" | Group) =>
    setProposal((p) => {
      if (!p) return p;
      if (target === "collection") return { ...p, summary: null };
      const { [String(target.id)]: _gone, ...groups } = p.groups;
      return { ...p, groups };
    });
  /** Save a proposal; a summary already there is only replaced after the confirm. */
  const applyProposal = async (target: "collection" | Group, text: string, confirmed = false) => {
    const current = target === "collection" ? (query.data?.summary ?? "") : target.summary;
    if (!confirmed && current.trim()) {
      setReplacing({ target, text });
      return;
    }
    if (using.current) return;
    using.current = true;
    setUsingBusy(true);
    setError(null);
    try {
      await save(target === "collection" ? { op: "summary", id, summary: text } : { op: "update", gid: target.id, summary: text });
      dropProposal(target);
      setReplacing(null);
    } catch (e) {
      setReplacing(null);
      setError(errorText(e));
    } finally {
      using.current = false;
      setUsingBusy(false);
    }
  };

  /** Move the collection inside ``parentId`` (null: the top); the sheet closes either
   * way, and a refusal (a closed parent, a cycle) shows on the page. */
  const moveTo = async (parentId: number | null, chosenName: string | null) => {
    if (inFlight.current) return;
    if (!startCollectionMove()) {
      setError(STILL_RUNNING); // a sidebar drag of a collection is still moving
      return;
    }
    inFlight.current = true;
    setError(null);
    const current = query.data?.name ?? "";
    try {
      const r = await setParent.mutateAsync({ id, parent_id: parentId });
      setMovingTo(false);
      // where it went: the sheet's choice, else the answer's path; never "into "
      const parentName = chosenName || pathOf(r.collection).at(-2) || "the chosen collection";
      const links = recreatedLinks(r);
      report(
        `Move: what happened in ##. Ongoing${recreatedNote(links)}`,
        movedText(current, parentId === null ? null : parentName, links),
        r,
      );
    } catch (e) {
      setMovingTo(false);
      setError(errorText(e));
    } finally {
      inFlight.current = false;
      endCollectionMove();
    }
  };

  const removeMember = async (m: Member) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null);
    try {
      report(`Member removed: what happened in ${rootName}`, query.data?.kind ? "Removed" : "Removed from the collection", await members.mutateAsync({ id, remove: m.drive_id }));
    } catch (e) {
      setError(errorText(e));
    } finally {
      inFlight.current = false;
    }
  };

  const c = query.data;
  const order = useMemo(() => (c ? visibleMembers(c, folded) : []), [c, folded]);
  const selected = order.find((m) => m.drive_id === chosen) ?? c?.members.find((m) => m.drive_id === chosen) ?? order[0] ?? null;
  const index = selected ? order.indexOf(selected) : -1;

  useEffect(() => {
    const shown = browsed ?? selected;
    if (shown) publishSelection(shown.drive_id);
  }, [selected, browsed]);

  // Quick Look: the shown file members that are in the index.
  const looks = useMemo(() => order.filter((m) => m.path && !m.is_dir && !m.missing), [order]);
  const qlFiles = useMemo<QLFile[]>(
    () =>
      looks.map((m) => ({
        drive_id: m.drive_id,
        name: null,
        path: m.path!,
        ext: extOf(m.path!),
        is_link: m.is_link,
        marks: m.marks,
      })),
    [looks],
  );
  // A file inside a folder member is previewed alone.
  const browsedQL = useMemo<QLFile[]>(
    () =>
      browsed
        ? [{ drive_id: browsed.drive_id, name: null, path: browsed.path, ext: extOf(browsed.path), is_link: browsed.is_link, marks: browsed.marks }]
        : [],
    [browsed],
  );
  const quickLook = useQuickLook(
    browsed ? browsedQL : qlFiles,
    browsed ? 0 : Math.max(0, looks.findIndex((m) => m.drive_id === selected?.drive_id)),
    (k) => {
      const target = looks[k];
      if (target && !browsed) setChosen(target.drive_id);
    },
    {
      canOpen: () => !!browsed || (!!selected && looks.includes(selected)),
      trashRefusal: (file) => deletionRefusal(file.path, file.marks),
      trashBusy: trash.busy,
      onTrash: (file, ui) => {
        if (inFlight.current) return;
        trash.start([file.drive_id], {
          current: () => (selectedRef.current ? [selectedRef.current] : null),
          links: !!file.is_link,
          onConfirming: ui.close,
          onRefused: ui.report,
          onCancelled: ui.reopen,
        });
      },
    },
  );
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = (browsed ?? selected)?.drive_id ?? null;
  /** Trash for the selected member: its refusal (one check, for the bin and ⌘⌫) is
   * said, never silent. */
  const trashSelected = () => {
    const shown = browsed ?? selected;
    if (!shown || inFlight.current || busy) return;
    const refusal = browsed ? deletionRefusal(browsed.path, browsed.marks) : trashRefusal(selected!);
    if (refusal) {
      toast({ kind: "info", text: refusal });
      return;
    }
    trash.start([shown.drive_id], {
      current: () => (selectedRef.current ? [selectedRef.current] : null),
      links: shown.is_link,
    });
  };

  // The header's file actions (``FileActionBar``) act on the file the side panel shows: the
  // selected member, or a file inside a folder member.
  const filingAI = useFilingAI();
  const batchMarks = useBatchMark();
  const shownFile = browsed ?? selected;
  const shownPath = shownFile?.path ?? null;
  // a file in the index (not a folder, a missing file or one in To Delete) has the full set
  const shownIsFile = !!shownFile && !!shownPath && !shownFile.is_dir && !("missing" in shownFile && (shownFile.missing || shownFile.quarantined));
  const trayEntries = usePutInTrayEntries(shownIsFile ? [shownFile.drive_id] : [], null);
  const askBar = useAskAction(
    filingAI,
    shownFile && shownPath && !("missing" in shownFile && (shownFile.missing || shownFile.quarantined))
      ? { drive_id: shownFile.drive_id, path: shownPath, is_dir: shownFile.is_dir, is_link: shownFile.is_link }
      : null,
    "Select a file to ask AI",
    busy,
  );
  const select = (driveId: string) => {
    setChosen(driveId);
    setBrowsed(null);
    // The row shows the selection; folded groups of a picked member open.
    const m = c?.members.find((x) => x.drive_id === driveId);
    if (c && m && m.group_id !== null) {
      const parents = new Map(c.groups.map((g) => [g.id, g.parent_id]));
      const open = new Set(folded);
      let changed = false;
      for (let gid: number | null = m.group_id; gid !== null; gid = parents.get(gid) ?? null) {
        if (open.delete(gid)) changed = true;
      }
      if (changed) setFolded(open);
    }
  };
  const move = (delta: number) => {
    if (order.length === 0) return;
    const next = order[Math.max(0, Math.min(order.length - 1, (index < 0 ? 0 : index) + delta))];
    setChosen(next.drive_id);
    setBrowsed(null);
    requestAnimationFrame(() => {
      const row = document.querySelector<HTMLElement>(".group-tree li[aria-current] .member-row");
      row?.focus();
      row?.scrollIntoView?.({ block: "nearest" }); // the list scrolls on its own
    });
  };
  useKeydown((e) => {
    if (isTrashKey(e)) {
      // the focused member list (or nothing focused)
      const target = e.target instanceof Element ? e.target : null;
      if (target && target !== document.body && !target.closest(".group-tree")) return;
      e.preventDefault();
      trashSelected();
      return;
    }
    if (!isShortcut(e)) return;
    if (e.target instanceof Element && e.target.closest(".collection-inspector, .menu, .collection-notes")) return;
    if (e.key === "j" || e.key === "ArrowDown") move(1);
    else if (e.key === "k" || e.key === "ArrowUp") move(-1);
    else return;
    e.preventDefault();
  });

  if (query.isPending) return <p className="placeholder">Loading…</p>;
  if (query.isError || !c) {
    return (
      <p className="error" role="alert">
        Could not load this collection. {visible(errorText(query.error))}
      </p>
    );
  }
  // The built-in ★ Starred / ! Important: no rename, close, publish or parent actions
  // (the server refuses them too); ★ has no groups either.
  const builtin = c.kind ?? null;
  const name = builtin ? BUILTIN_LABEL[builtin] : visible(c.name);
  const builtinRoot =
    builtin === "important" ? status.data?.special_folders.important : builtin === "starred" ? status.data?.special_folders.ongoing : undefined;
  const published = c.publish.ongoing === true;
  const isOpen = c.state === "open";
  const paths = groupPaths(c);
  const tree = treeOf(c);
  latestGroups.current = { all: c.groups, top: tree.children.get(null) ?? [] };
  const attentionBy = new Map((attention.data ?? []).map((a) => [a.drive_id, a]));

  const rename = (text: string) => {
    const next = text.trim();
    if (!next || next === c.name) {
      setRenaming(false);
      return;
    }
    void start({
      action: { id, action: "rename", name: next },
      title: `Rename ${c.name} to ${next}?`,
      label: "Rename",
      done: `Renamed to ${next}`,
    });
  };
  const newGroup = async () => {
    if (creatingGroup.current) return;
    creatingGroup.current = true;
    try {
      // The click that leaves a group's name field also saves that name: this one
      // waits for it (the button stays enabled meanwhile, or the click would be lost).
      while (inFlight.current && groupWork.current) {
        await groupWork.current;
        await new Promise((resolve) => setTimeout(resolve, 0)); // the page shows the saved name
      }
      const before = new Set(latestGroups.current.all.map((g) => g.id));
      const nameFor = freeName(latestGroups.current.top);
      const r = await run({ op: "create", id, name: nameFor, parent_id: null }, `Added the group ${nameFor}`);
      const made = r?.collection.groups.find((g) => !before.has(g.id));
      if (made) setRenamingGroup(made.id);
    } finally {
      creatingGroup.current = false;
    }
  };
  // New group stays clickable while a group change (the name just typed) is saving:
  // it waits for it, and a disabled button would swallow the click that blurred the field.
  const addBusy = busy && !groupChange.isPending;
  const toggle = (key: FoldKey) =>
    setFolded((f) => {
      const next = new Set(f);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  const ownRow = builtin ? undefined : allCollections.data?.find((x) => x.id === id);
  const openChildren = (allCollections.data ?? []).some((x) => x.parent_id === id && x.state === "open");
  const more: MenuEntry[] = [
    { label: "Rename", disabled: busy, onSelect: () => setRenaming(true) },
    { label: "Move to…", disabled: busy, onSelect: () => setMovingTo(true) },
    ...(ownRow
      ? [
          { label: "Move up", disabled: busy || !reorder.canStep(ownRow, -1), onSelect: () => reorder.step(ownRow, -1) },
          { label: "Move down", disabled: busy || !reorder.canStep(ownRow, 1), onSelect: () => reorder.step(ownRow, 1) },
          ...(reorder.canOut(ownRow) ? [{ label: "Move out one level", disabled: busy, onSelect: () => reorder.out(ownRow) }] : []),
        ]
      : []),
    // a closed collection takes no new collection (the server refuses a closed parent)
    { label: "New collection inside…", disabled: busy || !isOpen, onSelect: () => setNewChild(true) },
    {
      label: "Show in ##. Ongoing",
      checked: published,
      disabled: busy,
      onSelect: () => {
        const on = !published;
        void start({
          action: { id, action: "publish", on },
          title: on ? `Show ${c.name} in ##. Ongoing?` : `Remove ${c.name} from ##. Ongoing?`,
          label: on ? "Show" : "Remove",
          done: on ? `${c.name} is shown in ##. Ongoing` : `${c.name} is no longer in ##. Ongoing`,
        });
      },
    },
    "separator",
    isOpen
      ? {
          label: "Close collection…",
          // the server refuses the same (before the preview too): no dead-end dialog
          disabled: busy || openChildren,
          reason: openChildren ? CLOSE_CHILDREN_FIRST : undefined,
          onSelect: () => void start({ action: { id, action: "close" }, title: `Close ${c.name}?`, label: "Close", done: `Closed ${c.name}` }),
        }
      : {
          label: "Reopen collection…",
          disabled: busy,
          onSelect: () => void start({ action: { id, action: "reopen" }, title: `Reopen ${c.name}?`, label: "Reopen", done: `Reopened ${c.name}` }),
        },
  ];

  // What the file actions that move or edit a file need: a file in the index, not locked.
  const gone = !!shownFile && "missing" in shownFile && shownFile.missing;
  const inTrash = !!shownFile && "quarantined" in shownFile && shownFile.quarantined;
  const fileWhy = !shownFile
    ? null
    : !shownPath
      ? "The file is not in the index"
      : gone
        ? "The file is missing"
        : (toDeleteReason(shownPath) ?? (inTrash ? "Marked for deletion: restore it first" : null)) ??
          (shownFile.is_dir ? "Folders are moved from Browse" : null);
  const lockedWhy = shownFile && shownPath && !shownFile.is_dir && isBlocked(shownFile.drive_id, shownFile.marks, shownPath) ? LOCKED_REASON : null;
  const moveWhy = fileWhy ?? (shownPath ? sourceRefusal(shownPath) : null) ?? lockedWhy ?? (busy ? MOVE_BUSY : null);
  const inboxWhy = fileWhy ?? (shownPath ? inboxRefusal([shownPath], inbox) : null) ?? lockedWhy ?? (busy ? MOVE_BUSY : null);
  const startMove = (req: { ids: string[]; folder: string }) => {
    if (anyMoveRunning()) toast({ kind: "info", text: MOVE_BUSY });
    else moveFlow.start(req);
  };
  const startRestore = (to: RestoreTo) => {
    if (!shownFile) return;
    if (restoring.running()) toast({ kind: "info", text: "Already restoring…" });
    else if (anyMoveRunning()) toast({ kind: "info", text: MOVE_BUSY });
    else restoring.start([shownFile.drive_id], to);
  };
  const markReason = toDeleteReason(shownPath);
  const markable = shownFile && shownPath ? [{ drive_id: shownFile.drive_id, name: baseName(shownPath), marks: shownFile.marks }] : [];
  const trashWhy = browsed ? deletionRefusal(browsed.path, browsed.marks) : selected ? trashRefusal(selected) : null;
  const barProps: FileActionBarProps | null = shownFile
    ? {
        tray: shownIsFile ? { label: "Put in tray", entries: trayEntries, disabled: busy, reason: markReason } : undefined,
        removeFromCollection:
          !browsed && selected && !builtin ? { name: memberName(selected), run: () => void removeMember(selected), disabled: busy } : undefined,
        backToInbox: {
          run: () => {
            if (inbox && shownPath && !inboxWhy) startMove(backToInbox([shownFile.drive_id], inbox, [shownPath]));
          },
          disabled: busy,
          reason: inboxWhy,
        },
        moveTo: {
          run: () => {
            if (!moveWhy) setMoveSheet({ id: shownFile.drive_id, name: baseName(shownPath!) });
          },
          shortcut: "⇧⌘M",
          disabled: busy,
          reason: moveWhy,
        },
        sender: { run: () => setAssigning({ kind: "sender", ids: [shownFile.drive_id] }), disabled: busy, reason: fileWhy },
        person: { run: () => setAssigning({ kind: "person", ids: [shownFile.drive_id] }), disabled: busy, reason: fileWhy },
        ask: shownPath && !("missing" in shownFile && (shownFile.missing || shownFile.quarantined)) ? askBar : undefined,
        star: shownPath
          ? { on: allMarked(markable, "star"), run: () => void batchMarks.run("star", markable), disabled: busy || batchMarks.busy, reason: markReason }
          : undefined,
        important: shownPath
          ? { on: allMarked(markable, "important"), run: () => void batchMarks.run("important", markable), disabled: busy || batchMarks.busy, reason: markReason }
          : undefined,
        restore: inTrash ? { entries: restoreEntries(startRestore, null) } : undefined,
        trash: { run: trashSelected, disabled: busy || trashWhy !== null, reason: trashWhy },
      }
    : null;
  // Classic: one bar in the page's header. New: the file's two icon rows in its side panel,
  // without Move to… (the folder in the panel's header does it).
  const fileBar = barProps ? <FileActionBar {...barProps} /> : <FileActionBar />;
  const fileIcons =
    barProps && shownFile ? (
      <FileActionIcons
        {...barProps}
        moveTo={undefined}
        file={
          shownIsFile
            ? { drive_id: shownFile.drive_id, path: shownPath, name: browsed ? browsed.name : selected ? memberName(selected) : null, is_link: shownFile.is_link, connected: "connected" in shownFile ? shownFile.connected : undefined }
            : null
        }
        onQuickLook={shownIsFile && (browsed || (selected && looks.includes(selected))) ? quickLook.open : undefined}
      />
    ) : undefined;

  const subtitle = (
    <>
      {builtin ? "Built in" : isOpen ? "Open" : "Closed"}
      {!builtin && !isOpen && c.closed_at !== null && (
        <>
          {" "}
          <RelativeDate date={dayOf(c.closed_at)} today={today} />
        </>
      )}
      {" · "}
      {holdsText(c, allCollections.data?.find((x) => x.id === id)?.files)}
      {c.groups.length > 0 && ` · ${plural(c.groups.length, "group")}`}
      {subtitleExtra && ` · ${subtitleExtra}`}
    </>
  );

  const groupProposals: GroupProposals | undefined = shownProposal
    ? {
        text: (gid) => shownProposal.groups[String(gid)]?.trim() || undefined,
        use: (g) => void applyProposal(g, shownProposal.groups[String(g.id)].trim()),
        discard: (g) => dropProposal(g),
        busy: usingBusy,
      }
    : undefined;

  // New, under ~760px: what the header lets go of is in the ⋯ menu (a built-in collection has no menu and keeps its buttons)
  const moreEntries: MenuEntry[] = isNew
    ? [{ label: "Show folder", onSelect: () => setFinder(true) }, { label: "Export…", onSelect: () => setExporting(true) }, "separator", ...more]
    : more;
  const foldable = isNew && !builtin ? "hdr-wide" : undefined;

  const finderPopover = finder && (
    <div className="popover finder-popover" role="group" aria-label={showInLabel()}>
      {builtin ? (
        <>
          <p>
            {builtin === "important" ? (
              <>
                Open <code>{visible(builtinRoot ?? "##. Important")}</code> {inFileManager()} to see its links
                {c.groups.length > 0 && ", a folder per group"}.
              </>
            ) : (
              <>
                Its links are at the top of <code>{visible(builtinRoot ?? "##. Ongoing")}</code>, next to the
                collection folders.
              </>
            )}
          </p>
          {builtinRoot && <CopyButton value={builtinRoot} label="path" />}
        </>
      ) : c.ongoing_rel ? (
        <>
          <p>
            Open <code>{visible(c.ongoing_rel)}</code> {inFileManager()} to see its links{c.groups.length > 0 && ", a folder per group"}.
          </p>
          <CopyButton value={c.ongoing_rel} label="path" />
        </>
      ) : (
        <p>
          {c.ongoing_status?.startsWith(NOT_SHOWN)
            ? visible(c.ongoing_status) // hidden with its parent: the status says so
            : published && !isOpen
              ? "A closed collection is not shown in ##. Ongoing until reopened."
              : "Not shown in ##. Ongoing. Turn on “Show in ##. Ongoing” in the ⋯ menu to get a folder of links."}
        </p>
      )}
    </div>
  );

  const parentLinks = pathOf(c).slice(0, -1);
  const counts = (
    <>
      {!builtin && !isOpen && c.closed_at !== null && (
        <>
          <RelativeDate date={dayOf(c.closed_at)} today={today} />
          {" · "}
        </>
      )}
      {holdsText(c, allCollections.data?.find((x) => x.id === id)?.files)}
      {c.groups.length > 0 && ` · ${plural(c.groups.length, "group")}`}
      {subtitleExtra && ` · ${subtitleExtra}`}
    </>
  );

  const parentName = (g: Group) => (g.parent_id === null ? null : c.groups.find((x) => x.id === g.parent_id)?.name ?? null);

  return (
    <div className="collection">
        {isNew ? (
          <header className="collection-head">
            <div className="collection-head-main">
              <span className="collection-head-parent">
                {builtin ? (
                  "Built in collection"
                ) : (
                  <>
                    Collection ·{" "}
                    {parentLinks.length === 0 ? (
                      "no parent"
                    ) : (
                      <>
                        inside{" "}
                        {parentLinks.map((n, i) => {
                          const at = (allCollections.data ?? []).find((x) => x.name === n);
                          return (
                            <span key={i}>
                              {i > 0 && PATH_SEP}
                              {at ? <Link to={`/collections/${at.id}`}>{visible(n)}</Link> : visible(n)}
                            </span>
                          );
                        })}
                      </>
                    )}{" "}
                    ·{" "}
                    <button type="button" className="link-button" disabled={busy} onClick={() => setMovingTo(true)}>
                      {parentLinks.length === 0 ? "Put inside another collection…" : "Move to another collection…"}
                    </button>
                  </>
                )}
              </span>
              <div className="collection-head-line">
                {renaming ? (
                  <RenameField name={c.name} busy={busy} onSave={rename} onCancel={() => setRenaming(false)} />
                ) : (
                  <h2 aria-label={builtin ? undefined : name}>
                    {builtin ? (
                      name
                    ) : (
                      <ClickToEdit label={`Rename ${name}`} tip="Click to rename" onClick={() => !busy && setRenaming(true)}>
                        {name}
                      </ClickToEdit>
                    )}
                  </h2>
                )}
                <span className={`collection-state is-${builtin ? "built" : isOpen ? "open" : "closed"}`}>
                  {builtin ? "Built in" : isOpen ? "Open" : "Closed"}
                </span>
                <span className="collection-head-count">{counts}</span>
              </div>
            </div>
            <div className="toolbar-actions" role="toolbar" aria-label={`${name} actions`}>
              <button type="button" className="details-button" aria-expanded={detailsOpen} title="Show the selected file" onClick={() => setDetailsOpen((o) => !o)}>
                File details
              </button>
              {!builtin && (
                <button type="button" disabled={busy || !isOpen} title={isOpen ? "Put more files of the archive in this collection" : "A closed collection takes no new files"} onClick={() => setAddingFiles(true)}>
                  Add files
                </button>
              )}
              <span className="menu-wrap" ref={finderRef}>
                <button type="button" className={foldable} aria-expanded={finder} title={showInLabel()} onClick={() => setFinder((f) => !f)}>
                  Show folder
                </button>
                {finderPopover}
              </span>
              <button type="button" className={foldable} onClick={() => setExporting(true)}>
                Export…
              </button>
              {!builtin && <Menu label="More actions" icon={<Ellipsis {...ICON} />} entries={moreEntries} align="end" />}
            </div>
          </header>
        ) : (
        <Toolbar
          className="collection-toolbar"
          style={split.hostStyle}
          trailing={fileBar}
          title={name}
          titleEditor={renaming ? <RenameField name={c.name} busy={busy} onSave={rename} onCancel={() => setRenaming(false)} /> : undefined}
          subtitle={subtitle}
          onEditTitle={builtin ? undefined : () => !busy && setRenaming(true)}
          actions={
            <>
              {builtin !== "starred" && !isNew && (
                <IconButton icon={<FolderPlus {...ICON} />} label="New group" tip="New group: sort files into groups" disabled={addBusy} onClick={() => void newGroup()} />
              )}
              <span className="menu-wrap" ref={finderRef}>
                <IconButton icon={<FolderOpen {...ICON} />} label={showInLabel()} pressed={finder} className={foldable} onClick={() => setFinder((f) => !f)} />
                {finderPopover}
              </span>
              <IconButton icon={<Share {...ICON} />} label="Export…" className={foldable} onClick={() => setExporting(true)} />
              {!builtin && <Menu label="More actions" icon={<Ellipsis {...ICON} />} entries={moreEntries} align="end" />}
            </>
          }
        />
        )}
      <div className="collection-cols" ref={split.hostRef} style={split.hostStyle} data-details={isNew && detailsOpen ? "open" : undefined}>
      <div className="collection-main">
        <div className="collection-body">
          {banner}
          {!isNew && !builtin && <Where c={c} all={allCollections.data ?? []} />}
          {c.ongoing_status && <Banner message={visible(c.ongoing_status)} />}
          {error && (
            <p className="error" role="alert">
              {visible(error)}
            </p>
          )}
          <Summary
            key={id}
            id={id}
            value={c.summary}
            save={save}
            ai={
              ai.on && (
                <button type="button" className="ai-action" disabled={summarize.busy} onClick={() => summarize.ask({ collection_id: id })}>
                  <Sparkles size={14} aria-hidden="true" />
                  Summarize with AI…
                </button>
              )
            }
            proposal={
              shownProposal?.summary && (
                <AIProposal
                  label="AI summary of the collection"
                  text={shownProposal.summary}
                  busy={usingBusy}
                  onUse={() => void applyProposal("collection", shownProposal.summary!)}
                  onDiscard={() => dropProposal("collection")}
                />
              )
            }
          />
          <Attention members={c.members} attention={attention.data} onSelect={select} />
          {!builtin && <ChildCollections id={id} all={allCollections.data ?? []} />}
          {!isNew && builtin !== "starred" && c.groups.length === 0 && c.members.length >= 2 && (
            <p className="hint group-hint">
              Group files:{" "}
              <button type="button" className="link-button" disabled={addBusy} onClick={() => void newGroup()}>
                New group
              </button>
            </p>
          )}
          {isNew && (
            <div className="section-head">
              <h2>Files by group</h2>
              {builtin !== "starred" && (
                <button type="button" className="link-button" disabled={addBusy} title="Sort the files into groups" onClick={() => void newGroup()}>
                  New group
                </button>
              )}
            </div>
          )}
          <div className="collection-members">
          <GroupTree
            collection={c}
            attention={attentionBy}
            selected={browsed ? null : (selected?.drive_id ?? null)}
            onSelect={select}
            entry={browsed?.drive_id ?? null}
            onSelectEntry={setBrowsed}
            folded={folded}
            onToggle={toggle}
            busy={busy}
            renaming={renamingGroup}
            setRenaming={setRenamingGroup}
            actions={{ run, save, remove: setRemoving }}
            proposals={groupProposals}
          />
          </div>
          {result && <LastChange title={result.title} result={result.change} onDismiss={() => setResult(null)} />}
          <div className="collection-notes">
            <SavedNote kind="collection" target={String(id)} label="Note" />
            <Checklist kind="collection" target={String(id)} />
          </div>
        </div>
      </div>
      <Splitter split={split} label="Resize the inspector" />
      {isNew && detailsOpen && (
        // narrow page: the panel opens over the list
        <>
          <div className="details-scrim" aria-hidden="true" onClick={() => setDetailsOpen(false)} />
        </>
      )}
      {browsed ? (
        <EntryInspector entry={browsed} busy={busy} onQuickLook={quickLook.open} ai={filingAI} icons={isNew ? fileIcons : undefined} />
      ) : (
      <Inspector
        member={selected}
        groups={paths}
        busy={busy}
        onGroup={(gid) => {
          if (!selected || gid === selected.group_id) return;
          const where = gid === null ? "Ungrouped" : (c.groups.find((g) => g.id === gid)?.name ?? "");
          void run({ op: "members", id, drive_ids: [selected.drive_id], group_id: gid }, `Moved to ${where}`);
        }}
        onQuickLook={selected && looks.includes(selected) ? quickLook.open : undefined}
        ai={filingAI}
        icons={isNew ? fileIcons : undefined}
      />
      )}
      </div>
      {quickLook.view}
      {trash.view}
      {filingAI.sheet}
      {moveFlow.view}
      {restoring.view}
      {moveSheet && (
        <MoveToSheet
          names={[moveSheet.name]}
          initial=""
          onCancel={() => setMoveSheet(null)}
          onChoose={(dest) => {
            const chosen = moveSheet;
            setMoveSheet(null);
            startMove({ ids: [chosen.id], folder: dest });
          }}
        />
      )}
      {assigning && <AssignSheet kind={assigning.kind} driveIds={assigning.ids} onClose={() => setAssigning(null)} />}
      {addingFiles && (
        <Sheet
          open
          title={`Add files to ${name}`}
          onClose={() => setAddingFiles(false)}
          onKeyDown={(e) => e.stopPropagation()}
          footer={
            <button type="button" className="primary" onClick={() => setAddingFiles(false)}>
              Done
            </button>
          }
        >
          <AddFile
            taken={c.members.map((m) => m.drive_id)}
            takenMode="mark"
            takenLabel="already in this collection"
            choose={async (hit) => {
              setError(null);
              report(`File added: what happened in ${rootName}`, `Added ${visible(hit.name)} to the collection`, await members.mutateAsync({ id, add: [hit.drive_id] }));
            }}
            onDone={() => setAddingFiles(false)}
          />
        </Sheet>
      )}
      <Sheet
        open={exporting}
        title={`Export ${name}`}
        onClose={() => {
          if (!exportBusy) setExporting(false);
        }}
        footer={
          <button type="button" className="primary" disabled={exportBusy} onClick={() => setExporting(false)}>
            Done
          </button>
        }
      >
        <Export id={id} onBusy={setExportBusy} />
      </Sheet>
      {pending && (
        <ConfirmPlan
          planKey={snapshotKey({ action: pending.action, ops: pending.ops })}
          title={visible(pending.title)}
          intro={<p>These changes are made in ##. Ongoing (links only: your files stay where they are).</p>}
          ops={pending.ops}
          busy={change.isPending}
          confirmLabel={pending.label}
          onConfirm={() => void apply(pending)}
          onCancel={() => setPending(null)}
        />
      )}
      {movingTo && (
        <MoveSheet
          c={c}
          open={openCollections}
          busy={setParent.isPending}
          onMove={(parentId, name) => void moveTo(parentId, name)}
          onCancel={() => setMovingTo(false)}
        />
      )}
      {newChild && (
        <NewChildSheet
          parent={c}
          onCancel={() => setNewChild(false)}
          onCreated={(child) => {
            setNewChild(false);
            toast({ kind: "info", text: `Created ${child.name} inside ${c.name}` });
            navigate(`/collections/${child.id}`);
          }}
        />
      )}
      {summarize.sheet}
      {replacing && shownProposal && (
        <ConfirmPlan
          planKey={`replace-${replacing.target === "collection" ? "collection" : replacing.target.id}`}
          title={replacing.target === "collection" ? "Replace the summary?" : `Replace the summary of ${visible(replacing.target.name)}?`}
          ops={[]}
          busy={usingBusy}
          confirmLabel="Replace"
          onConfirm={() => void applyProposal(replacing.target, replacing.text, true)}
          onCancel={() => setReplacing(null)}
        >
          <p>Replace the current summary with the AI one? The current text is not kept.</p>
        </ConfirmPlan>
      )}
      {removing && (
        <ConfirmPlan
          planKey={`remove-group-${removing.id}`}
          title={`Remove the group ${visible(removing.name)}?`}
          ops={[]}
          busy={groupChange.isPending}
          confirmLabel="Remove group"
          danger
          onConfirm={async () => {
            // Closed either way, as ``apply`` does: a refusal or an error shows on the page.
            const g = removing;
            await run({ op: "remove", gid: g.id }, `Removed the group ${g.name}`);
            setRemoving(null);
          }}
          onCancel={() => setRemoving(null)}
        >
          <p>
            {parentName(removing) ? (
              <>
                Its files{(tree.children.get(removing.id) ?? []).length > 0 && " and subgroups"} move to{" "}
                <b>{visible(parentName(removing)!)}</b>.
              </>
            ) : (
              <>
                Its files move to Ungrouped
                {(tree.children.get(removing.id) ?? []).length > 0 && ", and its subgroups to the top level"}.
              </>
            )}{" "}
            The files stay in the collection: no membership is removed, and no file is moved or deleted.
          </p>
        </ConfirmPlan>
      )}
    </div>
  );
}
