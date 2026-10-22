/** Activity: every journaled batch as a timeline, newest first, under day headers
 * ("Today", "Yesterday", then the date), each with its own Undo. Search and filters
 * (kept in the URL) narrow it on the server, a page at a time. Recovery sits on top
 * when something was interrupted. */
import { History, MousePointerClick, RefreshCw, Terminal, Undo2 } from "lucide-react";
import { Link, useInRouterContext, useSearchParams } from "react-router-dom";
import { Fragment, type ReactNode, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  type ActivityFilter,
  type AILogRow,
  type AITask,
  type BatchSummary,
  type CollectionRow,
  errorText,
  type JournalEntry,
  useActivity,
  useCollections,
  useStatus,
  useAILog,
  useAISwitch,
  usePendingRecovery,
} from "../api/client";
import { Budget, euro } from "../components/ai/SendSheet";
import { TASK_LABEL, useAIState } from "../components/ai/useAI";
import { JournalList } from "../components/JournalList";
import { RecoveryPanel } from "../components/Recovery";
import { useBlockToastActions } from "../components/Toasts";
import { useUndoConfirm } from "../components/UndoConfirm";
import { EmptyState } from "../components/ui/EmptyState";
import { Segmented } from "../components/ui/Segmented";
import { Tag, type TagTone } from "../components/ui/Tag";
import { Toolbar } from "../components/ui/Toolbar";
import { plural } from "../format";
import { visible } from "../text";

/** Rows whose act happened (what undo reverts). */
const acted = (rows: JournalEntry[]) => rows.filter((r) => r.state === "done" || r.state === "unverified");

function batchState(b: BatchSummary): [string, TagTone] {
  if (b.undone) return ["Undone", "grey"];
  if (b.ops.some((r) => r.state === "planned")) return ["Interrupted", "red"];
  if (b.ops.some((r) => r.state === "failed")) return ["Failed", "red"];
  if (b.ops.some((r) => r.state === "undone")) return ["Partly undone", "orange"];
  return ["Done", "green"];
}

/** Each op kind as a noun, one and many. */
const KIND_NOUN: Record<string, [string, string]> = {
  rename: ["rename", "renames"],
  move: ["move", "moves"],
  mkdir: ["new folder", "new folders"],
  symlink: ["link", "links"],
  unlink_symlink: ["link removed", "links removed"],
  quarantine: ["marked for deletion", "marked for deletion"],
  remove_empty_dir: ["empty folder removed", "empty folders removed"],
};

/** "1 new folder, 2 moves": the ops counted by kind, in the order they first appear. */
export function opsSummary(kinds: string[]): string {
  if (kinds.length === 0) return "No operations";
  const counts = new Map<string, number>();
  for (const k of kinds) counts.set(k, (counts.get(k) ?? 0) + 1);
  return [...counts]
    .map(([k, n]) => {
      const [one, many] = KIND_NOUN[k] ?? [k, k];
      return plural(n, one, many);
    })
    .join(", ");
}

const baseName = (path: string | null) => (path ?? "").slice((path ?? "").lastIndexOf("/") + 1);
const folderOf = (path: string | null) => (path ?? "").split("/").slice(0, -1).join("/");

/** "X", or "N files" for several. */
const files = (names: string[]) => (names.length === 1 ? names[0] : `${names.length} files`);

/** A title for a batch that carries no label (older batches, command-line batches
 * made before labels existed): derived from what its ops did, naming the files. Falls
 * back to the counted ops ("2 moves, 1 new folder") when nothing reads better. */
export function derivedTitle(ops: JournalEntry[], toDelete = "##. To Delete"): string {
  const done = acted(ops);
  const rows = done.length > 0 ? done : ops;
  // the folders a move or a link needed never lead the title
  const kinds = new Set(rows.map((r) => r.kind).filter((k) => k !== "mkdir"));
  const quarantined = rows.filter((r) => r.kind === "quarantine");
  if (quarantined.length > 0 && kinds.size === 1) {
    return `Moved ${files(quarantined.map((r) => baseName(r.src ?? r.dst)))} to ${toDelete.replace(/^##\.\s*/, "")}`;
  }
  const linked = rows.filter((r) => r.kind === "symlink");
  const unlinked = rows.filter((r) => r.kind === "unlink_symlink");
  if (linked.length > 0 && [...kinds].every((k) => k === "symlink" || k === "unlink_symlink")) {
    const names = linked.map((r) => baseName(r.src ?? r.dst));
    if (unlinked.length === 0) return `Linked ${files(names)}`;
    const gone = new Set(unlinked.map((r) => r.src ?? r.dst));
    if (unlinked.length === linked.length && linked.every((r) => gone.has(r.dst))) {
      return names.length === 1 ? `Updated the link to ${names[0]}` : `Updated the links to ${names.length} files`;
    }
  }
  const moved = rows.filter((r) => r.kind === "move" || r.kind === "rename");
  const others = [...kinds].filter((k) => k !== "move" && k !== "rename" && k !== "mkdir" && k !== "symlink");
  if (moved.length > 0 && others.length === 0) {
    if (moved.length === 1 && moved[0].kind === "rename") {
      return `Renamed ${baseName(moved[0].src)} to ${baseName(moved[0].dst)}`;
    }
    const folders = new Set(moved.map((r) => folderOf(r.dst)));
    const where = folders.size === 1 ? ` to ${[...folders][0] || "the top folder"}` : "";
    return `Moved ${files(moved.map((r) => baseName(r.dst)))}${where}`;
  }
  return opsSummary(ops.map((r) => r.kind));
}

/** The batch title as a sentence of what the user did: the label the workflow stored,
 * else (older batches) one derived from the ops. An undo batch reads "Undo of <title
 * of the batch it reverted>"; an automatic sync reads "Automatic ##. Ongoing update". */
export function batchTitle(
  b: BatchSummary,
  all: BatchSummary[] = [],
  roots?: PublishRoots,
  toDelete?: string,
): string {
  if (b.is_undo) {
    const original = all.find((o) => o.batch_id === b.undo_of);
    const title = b.undoes_label ?? (original ? batchTitle(original, all, roots, toDelete) : null);
    return title ? `Undo of ${title}` : "Undo of an earlier change";
  }
  if (b.label) return b.label;
  if (b.origin === "workflow") return syncLabel(b.ops, roots, "update");
  return derivedTitle(b.ops, toDelete);
}

/** The text with every occurrence of the search words marked, ignoring case and accents.
 * Folding keeps each character one character long (else it is left as it is), so the
 * positions in the folded text are the positions in the original. */
export function Highlight({ text, words }: { text: string; words: string[] }) {
  const shown = visible(text);
  if (words.length === 0) return <>{shown}</>;
  const fold = (s: string) =>
    Array.from(s, (c) => {
      const base = c.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
      return base.length === c.length ? base : c;
    }).join("");
  const folded = fold(shown);
  const hit = new Array<boolean>(shown.length).fill(false);
  for (const w of words.map(fold).filter(Boolean)) {
    for (let at = folded.indexOf(w); at >= 0; at = folded.indexOf(w, at + 1)) hit.fill(true, at, at + w.length);
  }
  const parts: ReactNode[] = [];
  for (let i = 0; i < shown.length; ) {
    let j = i;
    while (j < shown.length && hit[j] === hit[i]) j++;
    parts.push(hit[i] ? <mark key={i}>{shown.slice(i, j)}</mark> : <Fragment key={i}>{shown.slice(i, j)}</Fragment>);
    i = j;
  }
  return <>{parts}</>;
}

const DAY = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" });
const DAY_YEAR = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });

const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;

/** A day header in local time: "Today", "Yesterday", "Sunday 18 October" (this year)
 * or "Saturday 18 October 2025". */
export function dayLabel(seconds: number, now = new Date()): string {
  const when = new Date(seconds * 1000);
  if (dayKey(when) === dayKey(now)) return "Today";
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (dayKey(when) === dayKey(yesterday)) return "Yesterday";
  return (when.getFullYear() === now.getFullYear() ? DAY : DAY_YEAR).format(when).replace(",", "");
}

/** The two folders the app publishes into (the server's names; these defaults until
 * the status says). */
export type PublishRoots = { ongoing: string; important: string };
const DEFAULT_ROOTS: PublishRoots = { ongoing: "##. Ongoing", important: "##. Important" };

const under = (path: string | null, root: string) => path !== null && (path === root || path.startsWith(`${root}/`));

/** The path an op made or changed: its dst, except where the journal keeps a removed
 * link or folder in src (and a removed link's old target in dst). */
const touchedPath = (op: Pick<JournalEntry, "kind" | "src" | "dst">) =>
  op.kind === "unlink_symlink" || op.kind === "remove_empty_dir" ? (op.src ?? op.dst) : (op.dst ?? op.src);

/** What an automatic sync batch says it is, by the publish folder its ops' paths are in:
 * "Automatic ##. Important sync" or "Automatic ##. Ongoing sync" (``noun`` "update" in
 * titles); a batch that touches both, or neither, is just an "Automatic sync". */
export function syncLabel(
  ops: Pick<JournalEntry, "kind" | "src" | "dst">[],
  roots: PublishRoots = DEFAULT_ROOTS,
  noun: "sync" | "update" = "sync",
): string {
  const touched = new Set<keyof PublishRoots>();
  for (const op of ops) {
    const path = touchedPath(op);
    for (const key of ["ongoing", "important"] as const) if (under(path, roots[key])) touched.add(key);
  }
  if (touched.size !== 1) return `Automatic ${noun}`;
  return `Automatic ${roots[[...touched][0]]} ${noun}`;
}

/** The collection an automatic publish batch belongs to: the folder under the publish
 * root its ops are in, matched to a collection by name. */
export function syncCollection(
  ops: Pick<JournalEntry, "kind" | "src" | "dst">[],
  collections: CollectionRow[],
  roots: PublishRoots = DEFAULT_ROOTS,
): CollectionRow | undefined {
  const names = new Set<string>();
  for (const op of ops) {
    const path = touchedPath(op);
    for (const root of [roots.ongoing, roots.important]) {
      if (path !== null && path.startsWith(`${root}/`)) {
        const folder = path.slice(root.length + 1).split("/")[0];
        if (folder) names.add(folder.toLocaleLowerCase());
      }
    }
  }
  if (names.size !== 1) return undefined;
  const [folder] = [...names];
  return collections.find((c) => c.name.toLocaleLowerCase() === folder);
}

/** A link to a collection page (a plain anchor outside a router). */
function CollectionLink({ id, children }: { id: number; children: ReactNode }) {
  const inRouter = useInRouterContext();
  return inRouter ? <Link to={`/collections/${id}`}>{children}</Link> : <a href={`/collections/${id}`}>{children}</a>;
}

/** Where a batch came from, in words; the app is the default and says nothing. */
const ORIGIN_WORD: Record<string, string> = { cli: "command line" };

/** Batches with more ops than this show them behind a "Show details" fold. */
export const OPS_OPEN_MAX = 3;

const ORIGIN_ICON: Record<string, ReactNode> = {
  ui: <MousePointerClick size={14} />,
  cli: <Terminal size={14} />,
  workflow: <RefreshCw size={14} />,
  undo: <Undo2 size={14} />,
};

type BatchProps = {
  b: BatchSummary;
  title: string;
  collections: CollectionRow[];
  roots?: PublishRoots;
  /** Search words to mark in the title. */
  words: string[];
  undoBusy: boolean;
  onUndo: () => void;
};

function Batch({ b, title, collections, roots, words, undoBusy, onUndo }: BatchProps) {
  const ops = acted(b.ops);
  const interrupted = b.ops.some((r) => r.state === "planned");
  // The server decides what can be undone; automatic Ongoing syncs never can.
  const blocked = !b.undoable || ops.length === 0;
  const sync = b.origin === "workflow";
  const [state, tone] = batchState(b);
  const collection = sync ? syncCollection(b.ops, collections, roots) : undefined;
  const origin = ORIGIN_WORD[b.origin];
  const at = new Date(b.created * 1000);
  return (
    <article className="batch" aria-label={`Batch ${b.batch_id}`}>
      <span className={`batch-dot batch-dot-${tone}`} aria-hidden="true">
        {ORIGIN_ICON[b.origin] ?? <History size={14} />}
      </span>
      <div className="batch-main">
        <header className="batch-header">
          <span className="batch-title">
            <Highlight text={title} words={words} />
          </span>
          <Tag tone={tone} className="batch-state">
            {state}
          </Tag>
          {origin && <span className="batch-origin">{origin}</span>}
          <time dateTime={at.toISOString()} title={at.toLocaleString()}>
            {TIME.format(at)}
          </time>
          <span className="batch-actions">
            {sync ? (
              <span className="batch-note">
                Made automatically after a collection change —{" "}
                {collection ? (
                  <>
                    change <CollectionLink id={collection.id}>{visible(collection.name)}</CollectionLink> to undo it
                  </>
                ) : (
                  "change the collection to undo it"
                )}
              </span>
            ) : (
              <button
                type="button"
                disabled={blocked || undoBusy}
                title={b.is_undo ? "An undo cannot be undone" : b.undone ? "Already undone" : undefined}
                aria-describedby={interrupted ? `${b.batch_id}-interrupted` : undefined}
                onClick={onUndo}
              >
                Undo
              </button>
            )}
            {interrupted && (
              <span id={`${b.batch_id}-interrupted`} className="batch-note">
                Run recovery first
              </span>
            )}
          </span>
        </header>
        {b.ops.length > OPS_OPEN_MAX ? (
          <details className="batch-ops">
            <summary>{opsSummary(b.ops.map((r) => r.kind))}</summary>
            <JournalList entries={b.ops} />
          </details>
        ) : (
          <JournalList entries={b.ops} />
        )}
      </div>
    </article>
  );
}

type DayProps = {
  label: string;
  roots?: PublishRoots;
  /** Every loaded batch (an undo names the batch it reverted) and the collections. */
  all: BatchSummary[];
  collections: CollectionRow[];
  toDelete?: string;
  batches: BatchSummary[];
  words: string[];
  undoBusy: boolean;
  onUndo: (b: BatchSummary) => void;
};

function Day({ label, roots, all, collections, toDelete, batches, words, undoBusy, onUndo }: DayProps) {
  const id = useId();
  return (
    <section className="timeline-day" aria-labelledby={id}>
      <h3 id={id} className="timeline-day-title">
        {label}
      </h3>
      <ol className="timeline">
        {batches.map((b) => (
          <li key={b.batch_id}>
            <Batch
              b={b}
              title={batchTitle(b, all, roots, toDelete)}
              collections={collections}
              roots={roots}
              words={words}
              undoBusy={undoBusy}
              onUndo={() => onUndo(b)}
            />
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Batches (already newest first) grouped by local day, in order. */
function byDay(batches: BatchSummary[], now: Date): [string, BatchSummary[]][] {
  const days: [string, BatchSummary[]][] = [];
  for (const b of batches) {
    const label = dayLabel(b.created, now);
    const last = days[days.length - 1];
    if (last && last[0] === label) last[1].push(b);
    else days.push([label, [b]]);
  }
  return days;
}

const WHEN = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

const OUTCOME: Record<AILogRow["outcome"], [string, TagTone]> = {
  ok: ["sent", "green"],
  cached: ["from earlier", "blue"],
  fake: ["demo (not sent)", "grey"],
  error: ["error", "red"],
};

/** How long a call took: "850 ms" under a second, else seconds with one decimal. */
function duration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  return `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
}

/** The on/off switch (ai-state.json, as ``dam ai --on/--off``): one change at a time. */
function AISwitch() {
  const { status } = useAIState();
  const change = useAISwitch();
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  if (!status) return null;
  const flip = async (on: boolean) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null);
    try {
      await change.mutateAsync(on);
    } catch (e) {
      setError(errorText(e));
    } finally {
      inFlight.current = false;
    }
  };
  return (
    <div className="ai-switch">
      <label>
        <input
          type="checkbox"
          role="switch"
          checked={status.switched_on}
          disabled={change.isPending}
          onChange={(e) => void flip(e.target.checked)}
        />{" "}
        Use AI
      </label>
      <p className="hint">
        {status.state_error ? (
          <>Off: {visible(status.state_error)}. Switching it on rewrites the file.</>
        ) : !status.has_key ? (
          <>
            No key yet: add one with <code>dam ai --set-key</code>.
          </>
        ) : status.switched_on && !status.enabled ? (
          <>
            Off in the settings: <code>ai.enabled</code> in settings.yaml.
          </>
        ) : status.enabled ? (
          "On: nothing is sent until you click Send in the “What will be sent” sheet."
        ) : (
          "Off: the AI buttons are hidden and nothing can be sent."
        )}
      </p>
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </div>
  );
}

/** Activity → AI: the month's spend against the budget, the switch, and every call. */
function AIActivity() {
  const { status } = useAIState();
  const log = useAILog();
  let body: ReactNode;
  if (log.isPending) body = <p className="placeholder">Loading the AI log…</p>;
  else if (log.isError) {
    body = (
      <p className="error" role="alert">
        Could not load the AI log. {visible(errorText(log.error))}
      </p>
    );
  } else if (log.data.length === 0) {
    body = <EmptyState icon={<History size={40} strokeWidth={1.25} />} title="No AI calls yet." hint="Each call is listed here with what it cost." />;
  } else {
    body = (
      <table className="ai-log" aria-label="AI calls">
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Task</th>
            <th scope="col">Model</th>
            <th scope="col">Files</th>
            <th scope="col">Tokens</th>
            <th scope="col">Cost</th>
            <th scope="col">Duration</th>
            <th scope="col">Outcome</th>
          </tr>
        </thead>
        <tbody>
          {log.data.map((r) => {
            const [label, tone] = OUTCOME[r.outcome] ?? [r.outcome, "grey"];
            const at = new Date(r.at * 1000);
            return (
              <tr key={r.id}>
                <td>
                  <time dateTime={at.toISOString()}>{WHEN.format(at)}</time>
                </td>
                <td>{TASK_LABEL[r.task as AITask] ?? visible(r.task)}</td>
                <td>
                  <code>{visible(r.model)}</code>
                </td>
                <td title={r.files.map(visible).join("\n") || undefined}>{r.files.length}</td>
                <td className="num">
                  {r.input_tokens} in · {r.output_tokens} out
                </td>
                <td className="num">{euro(r.cost_eur)}</td>
                <td className="num">{duration(r.duration_ms)}</td>
                <td>
                  <Tag tone={tone}>{label}</Tag>
                  {r.error && <span className="ai-log-error">{visible(r.error)}</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  }
  return (
    <div className="activity-ai">
      <section className="ai-month" aria-label="This month">
        <h3>This month</h3>
        {status ? <Budget status={status} estimate={0} /> : null}
        <AISwitch />
      </section>
      {body}
    </div>
  );
}

type View = "changes" | "ai";

/** The filter menus: URL value, label. The first option of each is "no filter". */
const KIND_OPTIONS: [string, string][] = [
  ["", "All changes"],
  ["filed", "Filing and moves"],
  ["rename", "Renames"],
  ["collections", "Collections"],
  ["marks", "Stars and Important"],
  ["trash", "Moved to To Delete"],
  ["convert", "Conversions"],
  ["undo", "Undos"],
];
const STATUS_OPTIONS: [string, string][] = [
  ["", "Any status"],
  ["undoable", "Can be undone"],
  ["undone", "Undone"],
  ["done", "Done"],
  ["attention", "Needs attention"],
];
const ORIGIN_OPTIONS: [string, string][] = [
  ["", "Made by anyone"],
  ["ui", "Made in the app"],
  ["cli", "Made on the command line"],
  ["auto", "Made automatically"],
];
const WHEN_OPTIONS: [string, string][] = [
  ["", "Any time"],
  ["today", "Today"],
  ["7d", "Last 7 days"],
  ["30d", "Last 30 days"],
  ["year", "This year"],
];

/** The start of a "when" preset in epoch seconds (undefined: any time). */
export function whenSince(when: string, now = new Date()): number | undefined {
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const back = { today: 0, "7d": 6, "30d": 29 }[when];
  if (back !== undefined) return midnight.setDate(midnight.getDate() - back) / 1000;
  if (when === "year") return new Date(now.getFullYear(), 0, 1).getTime() / 1000;
  return undefined;
}

export const ACTIVITY_SEARCH_DEBOUNCE_MS = 250;

type FilterMenuProps = { label: string; value: string; options: [string, string][]; onChange: (v: string) => void };

function FilterMenu({ label, value, options, onChange }: FilterMenuProps) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map(([v, text]) => (
        <option key={v} value={v}>
          {text}
        </option>
      ))}
    </select>
  );
}

/** Journaled batches, newest first, each with Undo; recovery when something is pending.
 * The AI view lists the AI calls instead. The search and filters live in the URL
 * (?q=&kind=&status=&origin=&when=; ?file= opens it searched for a file). */
export default function Activity() {
  const [view, setView] = useState<View>("changes");
  const [params, setParams] = useSearchParams();
  const urlQ = params.get("q") ?? params.get("file") ?? "";
  const filters = {
    kind: params.get("kind") ?? "",
    status: params.get("status") ?? "",
    origin: params.get("origin") ?? "",
    when: params.get("when") ?? "",
  };
  const setParam = (patch: Record<string, string>, replace = false) => {
    const next = new URLSearchParams(params);
    next.delete("file"); // ?file= only seeds the search
    for (const [k, v] of Object.entries({ q: urlQ, ...patch })) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setParams(next, { replace });
  };

  // The search box types ahead of the URL; the URL (and the query) follow after a pause.
  const [text, setText] = useState(urlQ);
  useEffect(() => setText(urlQ), [urlQ]);
  useEffect(() => {
    if (text.trim() === urlQ) return;
    const timer = setTimeout(() => setParam({ q: text.trim() }, true), ACTIVITY_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // setParam reads the current params; the pause restarts only when the text changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const since = useMemo(() => whenSince(filters.when), [filters.when]);
  const filter: ActivityFilter = { q: urlQ, kind: filters.kind, status: filters.status, origin: filters.origin, since };
  const filtered = Boolean(urlQ || filters.kind || filters.status || filters.origin || filters.when);
  const words = urlQ.split(/\s+/).filter(Boolean);

  const activity = useActivity(filter);
  const folders = useStatus().data?.special_folders;
  const roots = folders ? { ongoing: folders.ongoing, important: folders.important } : undefined;
  const collections = useCollections("all").data ?? [];
  const pending = usePendingRecovery();
  const undo = useUndoConfirm();
  useBlockToastActions(undo.target !== null || undo.pending);

  const clearFilters = () => {
    setText("");
    setParams(new URLSearchParams());
  };

  const recovery = pending.data ?? [];
  let body: ReactNode;
  if (activity.isPending) body = <p className="placeholder">Loading activity…</p>;
  else if (activity.isError) {
    body = (
      <p className="error" role="alert">
        Could not load the activity. {visible(errorText(activity.error))}
      </p>
    );
  } else if (activity.data.length === 0) {
    body = filtered ? (
      <EmptyState
        icon={<History size={40} strokeWidth={1.25} />}
        title="No matching changes."
        hint="Try other words, or widen the filters."
      />
    ) : (
      <EmptyState
        icon={<History size={40} strokeWidth={1.25} />}
        title="Nothing has been done yet."
        hint="Every change the app makes to the archive is listed here, with Undo."
      />
    );
  } else {
    const now = new Date();
    body = (
      <>
        {byDay(activity.data, now).map(([label, batches]) => (
          <Day
            key={label}
            label={label}
            roots={roots}
            all={activity.data}
            collections={collections}
            toDelete={folders?.quarantine}
            batches={batches}
            words={words}
            undoBusy={undo.pending}
            onUndo={(b) => undo.open({ batchId: b.batch_id })}
          />
        ))}
        {activity.hasNextPage && (
          <div className="activity-more">
            <button type="button" disabled={activity.isFetchingNextPage} onClick={() => void activity.fetchNextPage()}>
              {activity.isFetchingNextPage ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </>
    );
  }
  const count = activity.data?.length ?? 0;
  const searchBox = (
    <div className="search">
      <label htmlFor="activity-q" className="visually-hidden">
        Search the changes
      </label>
      <input
        id="activity-q"
        type="search"
        placeholder="Search changes and files"
        value={text}
        spellCheck={false}
        onChange={(e) => setText(e.target.value)}
      />
    </div>
  );
  return (
    <div className="activity">
      <Toolbar
        title="Activity"
        subtitle={
          view === "changes" && count > 0
            ? `${plural(count, "change", "changes")}${activity.hasNextPage ? " so far" : ""}`
            : undefined
        }
        actions={
          <Segmented<View>
            ariaLabel="Show"
            value={view}
            onChange={setView}
            options={[
              { value: "changes", label: "Changes" },
              { value: "ai", label: "AI" },
            ]}
          />
        }
        search={view === "changes" ? searchBox : undefined}
      />
      {view === "changes" && (
        <div className="activity-filters" role="group" aria-label="Filters">
          <FilterMenu label="Kind of change" value={filters.kind} options={KIND_OPTIONS} onChange={(v) => setParam({ kind: v })} />
          <FilterMenu label="Status" value={filters.status} options={STATUS_OPTIONS} onChange={(v) => setParam({ status: v })} />
          <FilterMenu label="Made by" value={filters.origin} options={ORIGIN_OPTIONS} onChange={(v) => setParam({ origin: v })} />
          <FilterMenu label="When" value={filters.when} options={WHEN_OPTIONS} onChange={(v) => setParam({ when: v })} />
          {filtered && (
            <button type="button" className="activity-clear" onClick={clearFilters}>
              Clear filters
            </button>
          )}
        </div>
      )}
      <div className="activity-body">
        <RecoveryPanel count={recovery.length} entries={recovery} />
        {view === "ai" ? <AIActivity /> : body}
      </div>
    </div>
  );
}
