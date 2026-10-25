/** The small checks: each a button that starts a check, a list, and the existing flow that
 * acts on it (Move to To Delete, the previewed rename, a previewed link removal). Nothing
 * runs until its button is clicked. */
import { Folder, Link2Off, ListX, Trash2, Type } from "lucide-react";
import { type ReactNode, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  type BatchResult,
  errorText,
  type MaintenanceKind,
  useRemoveBrokenLinks,
  useStatus,
} from "../../api/client";
import { inFileManager } from "../../fileManager";
import { dialogOpen } from "../../keyboard";
import { formatSize, groupDigits, plural, shortDate } from "../../format";
import { visible } from "../../text";
import { useMoveFlow } from "../MoveTo";
import { ConfirmPlan } from "../PlanPreview";
import { undoAction, useBlockToastActions, useToast } from "../Toasts";
import { useTrash } from "../Trash";
import { useUndoConfirm } from "../UndoConfirm";
import { Card } from "../ui/Card";
import { Tag } from "../ui/Tag";
import { JobProgress } from "./JobProgress";
import { type Check, useMaintenanceJob } from "./useMaintenanceJob";
import { useFold } from "./view";

const refusal = (e: unknown) => (e instanceof ApiError && e.detail ? e.detail : errorText(e));
const folderOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
const browseTo = (path: string, driveId: string) =>
  `/browse?${new URLSearchParams({ path: folderOf(path), select: driveId })}`;

/** What a folded check card shows in place of its body. */
export function foldedLine(check: Check, found: string | null) {
  if (check.running) return "Checking…";
  if (check.error || check.job?.state === "error") return "The check failed.";
  if (check.job === null) return "Not checked yet.";
  return found ?? "Nothing found.";
}

/** Forgets the check's result; nothing in the archive changes. */
export function ResetButton({ check, busy = false }: { check: Check; busy?: boolean }) {
  return (
    <button
      type="button"
      onClick={check.reset}
      disabled={busy || check.starting || (check.job === null && !check.error)}
      title="Forget this result, as if the check had not run. Nothing in the archive changes."
    >
      Reset
    </button>
  );
}

/** A check's card: what it looks for, its button, progress with Stop, and the result.
 * Folded, it shows one line: what the check found, or that it has not run. */
function CheckCard({
  title,
  icon,
  kind,
  intro,
  buttonLabel = "Check",
  check,
  extra,
  empty,
  found,
  summary,
  children,
}: {
  title: string;
  icon: ReactNode;
  kind: MaintenanceKind;
  intro: ReactNode;
  buttonLabel?: string;
  check: Check;
  /** Beside the button (a field of the check). */
  extra?: ReactNode;
  /** Shown when the check ended with nothing to list. */
  empty: string;
  /** The check ended and has something to show (else ``empty`` is). */
  found: boolean;
  /** The headline of what was found, for the folded card. */
  summary: string;
  children: ReactNode;
}) {
  const ended = check.job !== null && !check.running;
  const fold = useFold(kind);
  if (fold?.folded)
    return (
      <Card title={title} icon={icon} className={`check-card check-${kind}`} fold={fold}>
        <p className="hint">{foldedLine(check, found ? summary : empty || null)}</p>
      </Card>
    );
  return (
    <Card title={title} icon={icon} className={`check-card check-${kind}`} fold={fold}>
      <p>{intro}</p>
      <div className="check-actions">
        {check.running ? (
          <button type="button" onClick={check.stop}>
            Stop
          </button>
        ) : (
          <button type="button" className="primary" onClick={() => check.start()} disabled={check.starting}>
            {ended ? `${buttonLabel} again` : buttonLabel}
          </button>
        )}
        {extra}
        {!check.running && <ResetButton check={check} />}
      </div>
      {check.running && check.job && <JobProgress job={check.job} noun="items" />}
      {check.error && (
        <p className="error" role="alert">
          {visible(check.error)}
        </p>
      )}
      {check.job?.state === "error" && (
        <p className="error" role="alert">
          {visible(check.job.error ?? "The check failed")}
        </p>
      )}
      {ended && check.job?.state !== "error" && (found ? children : <p className="hint">{empty}</p>)}
    </Card>
  );
}

/** Ticks on a list of ids (all ticked at first). */
function useTicks(ids: string[]) {
  const [off, setOff] = useState<Set<string>>(new Set());
  const ticked = ids.filter((id) => !off.has(id));
  return {
    ticked,
    has: (id: string) => !off.has(id),
    toggle: (id: string) =>
      setOff((s) => {
        const next = new Set(s);
        if (!next.delete(id)) next.add(id);
        return next;
      }),
    all: ticked.length === ids.length,
    setAll: (on: boolean) => setOff(on ? new Set() : new Set(ids)),
  };
}

function Capped({ shown, total }: { shown: number; total: number }) {
  return total > shown ? (
    <p className="hint">
      Showing {groupDigits(shown)} of {groupDigits(total)}.
    </p>
  ) : null;
}

// -- empty folders -------------------------------------------------------------------------

export function EmptyFolders() {
  const check = useMaintenanceJob("empty_folders");
  const trash = useTrash({ onTrashed: () => check.reload() });
  const items = check.job?.empty_folders?.items ?? [];
  const ticks = useTicks(items.map((i) => i.drive_id));
  return (
    <CheckCard
      title="Empty folders"
      icon={<Folder />}
      kind="empty_folders"
      intro="Folders with nothing in them (a Finder cache file does not count). The top level, the app's own folders and the folders the archive is set up with (such as the filing code folders in the Inbox) are left out."
      check={check}
      empty="No empty folders."
      found={items.length > 0}
      summary={plural(check.job?.empty_folders?.total ?? 0, "empty folder")}
    >
      {items.length > 0 && (
        <>
          <ListHead
            count={`${plural(check.job?.empty_folders?.total ?? 0, "empty folder")}`}
            all={ticks.all}
            onAll={ticks.setAll}
            what="folders"
          />
          <ul className="check-list">
            {items.map((f) => (
              <li key={f.drive_id}>
                <label className="check">
                  <input type="checkbox" checked={ticks.has(f.drive_id)} onChange={() => ticks.toggle(f.drive_id)} />
                  <code>{visible(f.path)}</code>
                </label>
                <Link to={`/browse?${new URLSearchParams({ path: f.path })}`} className="card-link">
                  Show in Browse
                </Link>
              </li>
            ))}
          </ul>
          <Capped shown={items.length} total={check.job?.empty_folders?.total ?? 0} />
          <div className="check-actions">
            <button type="button" disabled={ticks.ticked.length === 0 || trash.busy} onClick={() => trash.start(ticks.ticked)}>
              <Trash2 size={14} aria-hidden="true" /> Mark {plural(ticks.ticked.length, "folder")} for deletion…
            </button>
          </div>
        </>
      )}
      {trash.view}
    </CheckCard>
  );
}

function ListHead({ count, all, onAll, what }: { count: string; all: boolean; onAll: (on: boolean) => void; what: string }) {
  return (
    <div className="check-head">
      <label className="check">
        <input type="checkbox" checked={all} onChange={(e) => onAll(e.target.checked)} aria-label={`Select all ${what}`} />
        <strong>{count}</strong>
      </label>
    </div>
  );
}

// -- broken links --------------------------------------------------------------------------------

export function BrokenLinks() {
  const check = useMaintenanceJob("broken_links");
  const toast = useToast();
  const remove = useRemoveBrokenLinks();
  const undo = useUndoConfirm(() => check.reload());
  const trash = useTrash({ onTrashed: () => check.reload(), onUndone: () => check.reload() });
  const [plan, setPlan] = useState<{ ids: string[]; batchId: string; result: BatchResult } | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  useBlockToastActions(busy || plan !== null);
  const items = check.job?.broken_links?.items ?? [];
  const ticks = useTicks(items.map((i) => i.drive_id));
  const outside = items.filter((i) => !i.inside && ticks.has(i.drive_id)).map((i) => i.drive_id);
  const inside = items.filter((i) => i.inside && ticks.has(i.drive_id)).map((i) => i.drive_id);

  const guarded = async (work: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      await work();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  const previewRemoval = () =>
    guarded(async () => {
      try {
        const dry = await remove.mutateAsync({ drive_ids: inside, dry_run: true });
        if (dry.error || dry.failed) throw new Error(dry.error ?? "an operation failed");
        setPlan({ ids: inside, batchId: dry.batch_id, result: dry });
      } catch (e) {
        toast({ kind: "error", text: `Not removed: ${visible(refusal(e))}` });
      }
    });
  const applyRemoval = (p: NonNullable<typeof plan>) => {
    setPlan(null);
    void guarded(async () => {
      try {
        const result = await remove.mutateAsync({ drive_ids: p.ids, dry_run: false });
        const complete = !result.error && !result.failed;
        if (!complete) toast({ kind: "error", text: `Stopped: ${visible(result.error ?? "an operation failed")}` });
        if (result.done.length > 0) {
          const target = { batchId: result.batch_id };
          toast({
            kind: complete ? "info" : "warning",
            text: `Removed ${plural(result.done.length, "broken link")}`,
            action: undoAction(() => {
              if (inFlight.current || undo.undoing.current || dialogOpen()) return;
              undo.open(target);
            }),
          });
        }
        check.reload();
      } catch (e) {
        toast({ kind: "error", text: `Not removed: ${visible(refusal(e))}` });
      }
    });
  };

  return (
    <CheckCard
      title="Broken links"
      icon={<Link2Off />}
      kind="broken_links"
      intro="Links whose target is gone. In Ongoing and Important the app may remove a broken link; anywhere else a link is moved to To Delete like a file, and you decide."
      check={check}
      empty="No broken links."
      found={items.length > 0}
      summary={plural(check.job?.broken_links?.total ?? 0, "broken link")}
    >
      {items.length > 0 && (
        <>
          <ListHead
            count={plural(check.job?.broken_links?.total ?? 0, "broken link")}
            all={ticks.all}
            onAll={ticks.setAll}
            what="links"
          />
          <ul className="check-list">
            {items.map((l) => (
              <li key={l.drive_id}>
                <label className="check">
                  <input type="checkbox" checked={ticks.has(l.drive_id)} onChange={() => ticks.toggle(l.drive_id)} />
                  <span>
                    <code>{visible(l.path)}</code> <span className="hint">points to</span>{" "}
                    <code>{visible(l.target ?? "nothing")}</code>
                  </span>
                </label>
                {l.inside && <Tag tone="grey">kept by the app</Tag>}
              </li>
            ))}
          </ul>
          <Capped shown={items.length} total={check.job?.broken_links?.total ?? 0} />
          <div className="check-actions">
            <button type="button" disabled={outside.length === 0 || trash.busy} onClick={() => trash.start(outside, { links: true })}>
              <Trash2 size={14} aria-hidden="true" /> Mark {plural(outside.length, "link")} for deletion…
            </button>
            {inside.length > 0 && (
              <button type="button" disabled={busy} onClick={() => void previewRemoval()}>
                Remove {plural(inside.length, "link")} in Ongoing or Important…
              </button>
            )}
          </div>
        </>
      )}
      {trash.view}
      {plan && (
        <ConfirmPlan
          planKey={plan.batchId}
          title="Remove broken links?"
          danger
          confirmLabel="Remove links"
          busy={busy}
          ops={plan.result.done}
          intro={
            <p>
              Only the links go; the app never removes a file. Undo makes a link again only while the file it pointed to
              exists, which these no longer do, so this one stays removed.
            </p>
          }
          onConfirm={() => applyRemoval(plan)}
          onCancel={() => setPlan(null)}
        />
      )}
    </CheckCard>
  );
}

// -- collection members and tray items without a file -----------------------------------------------

const ownerLink = (kind: string, id: string, name: string) => {
  if (kind === "tray") return `/trays/${encodeURIComponent(id)}`;
  if (name === "Starred") return "/starred";
  if (name === "Important") return "/important";
  return `/collections/${encodeURIComponent(id)}`;
};

export function Missing() {
  const check = useMaintenanceJob("references");
  const rows = check.job?.references?.items ?? [];
  return (
    <CheckCard
      title="Collections and trays"
      icon={<ListX />}
      kind="references"
      intro="Collection members and files of open tray items that are gone or are in To Delete. Open the collection or tray to take them out."
      check={check}
      empty="Every collection member and tray file is where it should be."
      found={rows.length > 0}
      summary={plural(check.job?.references?.total ?? 0, "entry", "entries")}
    >
      {rows.length > 0 && (
        <>
          <p>
            <strong>{plural(check.job?.references?.total ?? 0, "entry", "entries")}</strong>
          </p>
          <ul className="check-list">
            {rows.map((r) => (
              <li key={`${r.kind}-${r.owner_id}-${r.item_id ?? ""}-${r.drive_id}`}>
                <span>
                  <Link to={ownerLink(r.kind, r.owner_id, r.owner_name)} className="card-link">
                    {visible(r.owner_name)}
                  </Link>{" "}
                  <span className="hint">{r.kind === "tray" ? "tray item" : "collection"}:</span>{" "}
                  <code>{visible(r.path ?? r.drive_id)}</code>
                </span>
                <Tag tone={r.reason === "missing" ? "red" : "orange"}>{r.reason === "missing" ? "Missing" : "In To Delete"}</Tag>
              </li>
            ))}
          </ul>
          <Capped shown={rows.length} total={check.job?.references?.total ?? 0} />
        </>
      )}
    </CheckCard>
  );
}

// -- names ----------------------------------------------------------------------------------------------

export function Names() {
  const check = useMaintenanceJob("names");
  const flow = useMoveFlow(
    () => check.reload(),
    () => check.reload(),
  );
  const rows = check.job?.names?.items ?? [];
  return (
    <CheckCard
      title="File names"
      icon={<Type />}
      kind="names"
      intro="Files in the numbered folders whose name does not start with the date as YYYYMMDD_. The suggestion uses the date in the name, else the document date, else the day the file was last changed."
      check={check}
      empty="Every file in the numbered folders follows the naming convention."
      found={rows.length > 0}
      summary={`${plural(check.job?.names?.total ?? 0, "file")} to rename`}
    >
      {rows.length > 0 && (
        <>
          <p>
            <strong>{plural(check.job?.names?.total ?? 0, "file")}</strong>
          </p>
          <ul className="check-list">
            {rows.map((r) => (
              <li key={r.drive_id}>
                <span className="name-change">
                  <code>{visible(r.path)}</code>
                  {r.suggestion ? (
                    <span>
                      <span className="hint">suggested</span> <code>{visible(r.suggestion)}</code>
                    </span>
                  ) : (
                    <span className="hint">No date known</span>
                  )}
                </span>
                <span className="dup-actions">
                  <button
                    type="button"
                    disabled={!r.suggestion || flow.busy}
                    onClick={() => r.suggestion && flow.start({ ids: [r.drive_id], folder: r.folder, name: r.suggestion })}
                  >
                    Rename…
                  </button>
                  <Link to={browseTo(r.path, r.drive_id)} className="card-link">
                    Show in Browse
                  </Link>
                </span>
              </li>
            ))}
          </ul>
          <Capped shown={rows.length} total={check.job?.names?.total ?? 0} />
        </>
      )}
      {flow.view}
    </CheckCard>
  );
}

// -- waiting in To Delete ----------------------------------------------------------------------------------

export function Waiting() {
  const check = useMaintenanceJob("waiting");
  const status = useStatus();
  const [days, setDays] = useState("30");
  const n = Number(days);
  const valid = days.trim() !== "" && Number.isInteger(n) && n >= 0 && n <= 36500;
  const result = check.job?.waiting ?? null;
  const quarantine = status.data?.special_folders?.quarantine ?? "##. To Delete";
  return (
    <CheckCard
      title="Waiting in To Delete"
      icon={<Trash2 />}
      kind="waiting"
      intro={
        <>
          A reminder of what has been in To Delete for a long time. The app never empties To Delete: when you are sure,
          empty it yourself {inFileManager()}.
        </>
      }
      check={{
        ...check,
        start: () => {
          if (valid) check.start(n);
        },
      }}
      extra={
        <label className="inline-field">
          Longer than{" "}
          <input
            type="number"
            min={0}
            max={36500}
            value={days}
            aria-label="Days waiting"
            onChange={(e) => setDays(e.target.value)}
            aria-invalid={!valid}
          />{" "}
          days
        </label>
      }
      empty=""
      found={result !== null}
      summary={
        result ? `${plural(result.total, "file")} waiting longer than ${plural(result.days, "day")}` : ""
      }
    >
      {result && (
        <>
          <p role="status">
            {result.total === 0 ? (
              <>Nothing has waited longer than {plural(result.days, "day")}.</>
            ) : (
              <>
                <strong>{plural(result.total, "file")}</strong> ({formatSize(result.total_size)}) {result.total === 1 ? "has" : "have"} waited
                longer than {plural(result.days, "day")}.
              </>
            )}{" "}
            <span className="hint">
              In all, To Delete holds {plural(result.in_to_delete, "file")} ({formatSize(result.in_to_delete_size)}).
            </span>
          </p>
          {result.items.length > 0 && (
            <ul className="check-list">
              {result.items.map((f) => (
                <li key={f.drive_id}>
                  <span>
                    <code>{visible(f.path)}</code>{" "}
                    <span className="hint">
                      {formatSize(f.size)}, {f.approximate ? "about " : ""}
                      {plural(f.days, "day")} ({shortDate(f.since)})
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <Capped shown={result.items.length} total={result.total} />
          <p>
            <Link to={`/browse?${new URLSearchParams({ path: quarantine })}`} className="card-link">
              Open To Delete in Browse
            </Link>
          </p>
        </>
      )}
    </CheckCard>
  );
}
