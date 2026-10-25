/** Duplicates: the check for files with the same content (hashing only files that share a
 * size with another, saying first how much will be read), the groups with a copy to keep
 * and a choice of what to do with the others, and the same-name files with other content,
 * listed for review only. Moving copies to To Delete or replacing them with a link to the
 * kept copy is one previewed batch with one Undo. */
import { Copy, FileSearch } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  type CarryOver,
  type DupFile,
  type DupGroup,
  type DuplicateResolveBody,
  type DuplicateResolveResult,
  errorText,
  useDuplicateEstimate,
  useResolveDuplicates,
} from "../../api/client";
import { formatSize, groupDigits, plural, shortDate } from "../../format";
import { dialogOpen } from "../../keyboard";
import { inFileManager } from "../../fileManager";
import { visible } from "../../text";
import { ConfirmPlan, PlanList, snapshotKey } from "../PlanPreview";
import { undoAction, useBlockToastActions, useToast } from "../Toasts";
import { useUndoConfirm } from "../UndoConfirm";
import { Card } from "../ui/Card";
import { Tag } from "../ui/Tag";
import { JobProgress } from "./JobProgress";
import { foldedLine, ResetButton } from "./ListChecks";
import { useMaintenanceJob } from "./useMaintenanceJob";
import { useFold } from "./view";

type Action = DuplicateResolveBody["action"];

const PLACE_LABEL: Record<DupFile["place"], string | null> = { numbered: null, inbox: "Inbox", other: null };
const baseName = (path: string) => path.slice(path.lastIndexOf("/") + 1);
const folderOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
const browseTo = (file: DupFile) =>
  `/browse?${new URLSearchParams({ path: folderOf(file.path), select: file.drive_id })}`;

const refusal = (e: unknown) => (e instanceof ApiError && e.detail ? e.detail : errorText(e));

type Pending = { body: DuplicateResolveBody; dry: DuplicateResolveResult; copies: number };

/** What the dry run says will be added to a kept copy, one line per kind. */
export function carryLines(c: CarryOver): string[] {
  const lines: string[] = [];
  if (c.tags.length) lines.push(`Tags: ${c.tags.join(", ")}`);
  if (c.collections.length) lines.push(`Collections: ${c.collections.join(", ")}`);
  if (c.notes.length) lines.push(`Note added: ${c.notes.map((n) => `"${n}"`).join(" / ")}`);
  if (c.checklist.length) lines.push(`Checklist: ${c.checklist.join(", ")}`);
  if (c.items.length) lines.push(`Tray items: ${c.items.join(", ")}`);
  if (c.sender) lines.push(`From: ${c.sender}`);
  if (c.person) lines.push(`For: ${c.person}`);
  return lines;
}

function CarryOverList({ items, asked }: { items: CarryOver[]; asked: boolean }) {
  if (!asked) return <p>Nothing is carried over to the kept copies.</p>;
  if (items.length === 0) {
    return <p>The copies to remove have no tags, collections, notes, tray items or From/For that the kept copies lack.</p>;
  }
  return (
    <>
      <p>Added to the kept copy (nothing is overwritten):</p>
      <ul className="carry-list">
        {items.map((c) => (
          <li key={c.drive_id}>
            <strong>{visible(c.name)}</strong>
            <ul>
              {carryLines(c).map((line) => (
                <li key={line}>{visible(line)}</li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </>
  );
}

/** A copy in a group: its folder (the group's head already names the file), and its own
 * name only where it differs from that. */
function FileRow({
  file,
  groupName,
  groupKey,
  keep,
  removing,
  onKeep,
  onToggle,
}: {
  file: DupFile;
  groupName: string;
  groupKey: string;
  keep: boolean;
  removing: boolean;
  onKeep: () => void;
  onToggle: () => void;
}) {
  const place = PLACE_LABEL[file.place];
  return (
    <li className="dup-file" data-keep={keep ? "" : undefined}>
      <label className="dup-keep">
        <input type="radio" name={`keep-${groupKey}`} checked={keep} onChange={onKeep} />
        <span>Keep</span>
      </label>
      <span className="dup-path">
        <code title={visible(file.path)}>{visible(folderOf(file.path) || "Top level")}</code>
        {baseName(file.path) !== groupName && (
          <span>
            <span className="hint">named</span> <code>{visible(baseName(file.path))}</code>
          </span>
        )}
        <span className="hint">
          {formatSize(file.size)}
          {file.mtime !== null && `, ${shortDate(file.mtime)}`}
        </span>
        {place && <Tag tone="grey">{place}</Tag>}
        {file.locked && (
          <Tag tone="orange" title={file.why ?? undefined}>
            {file.locked === "important" ? "Important" : "Locked"}
          </Tag>
        )}
      </span>
      <span className="dup-actions">
        {!keep && (
          <label className="check" title={file.why ?? undefined}>
            <input
              type="checkbox"
              checked={removing}
              disabled={file.locked !== null}
              onChange={onToggle}
              aria-label={`Remove ${visible(file.path)}`}
            />
            <span>{file.locked ? "Stays" : "Remove"}</span>
          </label>
        )}
        <Link to={browseTo(file)} className="card-link">
          Show in Browse
        </Link>
      </span>
      {file.why && !keep && <span className="hint dup-why">{visible(file.why)}</span>}
    </li>
  );
}

function Group({
  group,
  keep,
  skipped,
  included,
  busy,
  onKeep,
  onToggle,
  onInclude,
  onAct,
}: {
  group: DupGroup;
  keep: string;
  skipped: Set<string>;
  included: boolean;
  busy: boolean;
  onKeep: (id: string) => void;
  onToggle: (id: string) => void;
  onInclude: () => void;
  onAct: (action: Action) => void;
}) {
  const removable = group.files.filter((f) => f.drive_id !== keep && !f.locked && !skipped.has(f.drive_id));
  const why = removable.length === 0 ? "Choose at least one copy to remove" : undefined;
  const name = baseName(group.files[0].path);
  return (
    <li className="dup-group">
      <header className="dup-group-head">
        <label className="check">
          <input type="checkbox" checked={included} onChange={onInclude} aria-label={`Include ${visible(name)} in the bulk action`} />
          <strong>{visible(name)}</strong>
        </label>
        <span className="hint">
          {plural(group.files.length, "copy", "copies")} of {formatSize(group.size)}
        </span>
      </header>
      <ul className="dup-files">
        {group.files.map((f) => (
          <FileRow
            key={f.drive_id}
            file={f}
            groupName={name}
            groupKey={group.sha256}
            keep={f.drive_id === keep}
            removing={!skipped.has(f.drive_id)}
            onKeep={() => onKeep(f.drive_id)}
            onToggle={() => onToggle(f.drive_id)}
          />
        ))}
      </ul>
      <div className="dup-group-actions">
        <button type="button" disabled={busy || !!why} title={why} onClick={() => onAct("quarantine")}>
          Move {removable.length === 1 ? "the other" : "the others"} to To Delete…
        </button>
        <button type="button" disabled={busy || !!why} title={why} onClick={() => onAct("link")}>
          Replace {removable.length === 1 ? "it" : "them"} with a link…
        </button>
      </div>
    </li>
  );
}

export function Duplicates() {
  const check = useMaintenanceJob("duplicates");
  const estimate = useDuplicateEstimate();
  const resolve = useResolveDuplicates();
  const toast = useToast();
  const undo = useUndoConfirm(() => check.reload());
  const result = check.job?.duplicates ?? null;
  const [keeps, setKeeps] = useState<Record<string, string>>({});
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [carry, setCarry] = useState(true);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false); // synchronous: a second click sees it at once
  useBlockToastActions(busy || pending !== null);

  // what the next run would read changes once a run has ended (hashes are stored)
  const ranBefore = useRef(false);
  const { refetch } = estimate;
  useEffect(() => {
    if (check.running) ranBefore.current = true;
    else if (ranBefore.current) {
      ranBefore.current = false;
      void refetch();
    }
  }, [check.running, refetch]);

  const keepOf = (g: DupGroup) => {
    const chosen = keeps[g.sha256];
    return chosen && g.files.some((f) => f.drive_id === chosen) ? chosen : g.keep;
  };
  const removalsOf = (g: DupGroup) => {
    const keep = keepOf(g);
    return g.files.filter((f) => f.drive_id !== keep && !f.locked && !skipped.has(f.drive_id));
  };
  const bodyFor = (groups: DupGroup[], action: Action, dry_run: boolean): DuplicateResolveBody => ({
    groups: groups.map((g) => ({ keep: keepOf(g), others: removalsOf(g).map((f) => f.drive_id) })),
    action,
    carry_over: carry,
    dry_run,
  });

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

  const begin = (groups: DupGroup[], action: Action) => {
    const usable = groups.filter((g) => removalsOf(g).length > 0);
    if (usable.length === 0 || pending !== null) return;
    void guarded(async () => {
      const body = bodyFor(usable, action, true);
      let dry: DuplicateResolveResult;
      try {
        dry = await resolve.mutateAsync(body);
      } catch (e) {
        toast({ kind: "error", text: `Nothing was changed: ${visible(refusal(e))}` });
        return;
      }
      if (dry.error || dry.failed) {
        toast({ kind: "error", text: `Cannot do this: ${visible(dry.error ?? "an operation failed")}` });
        return;
      }
      setPending({ body, dry, copies: body.groups.reduce((n, g) => n + g.others.length, 0) });
    });
  };

  const apply = (p: Pending) => {
    setPending(null);
    void guarded(async () => {
      let result: DuplicateResolveResult;
      try {
        result = await resolve.mutateAsync({ ...p.body, dry_run: false });
      } catch (e) {
        toast({ kind: "error", text: `Not changed: ${visible(refusal(e))}` });
        return;
      }
      const complete = !result.error && !result.failed;
      if (!complete) {
        toast({ kind: "error", text: `Stopped after ${plural(result.done.length, "change")}: ${visible(result.error ?? "an operation failed")}` });
      }
      for (const e of result.carry_errors) toast({ kind: "warning", text: visible(e) });
      const moved = result.done.filter((op) => op.kind === "quarantine").length;
      if (moved > 0) {
        const target = { batchId: result.batch_id };
        toast({
          kind: complete ? "info" : "warning",
          text: `${complete ? "" : "Partly applied: "}${
            p.body.action === "link" ? "Replaced" : "Moved"
          } ${plural(moved, "duplicate")}${p.body.action === "link" ? " with links" : " to To Delete"}`,
          action: undoAction(() => {
            if (inFlight.current || undo.undoing.current || dialogOpen()) return;
            undo.open(target);
          }),
        });
      }
      check.reload();
    });
  };

  const groups = result?.groups ?? [];
  const includedGroups = groups.filter((g) => !excluded.has(g.sha256));
  const bulk = (action: Action) => begin(includedGroups, action);
  const bulkCopies = includedGroups.reduce((n, g) => n + removalsOf(g).length, 0);
  const est = estimate.data;
  const clearChoices = () => {
    setKeeps({});
    setSkipped(new Set());
    setExcluded(new Set());
  };
  const start = () => {
    clearChoices();
    check.start();
  };
  const fold = useFold("duplicates");
  const reset = (
    <ResetButton
      title="Duplicates"
      busy={busy}
      check={{
        ...check,
        reset: () => {
          clearChoices();
          check.reset();
        },
      }}
    />
  );

  const confirmView = (() => {
    if (!pending) return null;
    const link = pending.body.action === "link";
    const n = pending.copies;
    return (
      <ConfirmPlan
        planKey={snapshotKey(pending.body)}
        title={link ? `Replace ${plural(n, "duplicate")} with links?` : `Move ${plural(n, "duplicate")} to To Delete?`}
        danger={!link}
        confirmLabel={link ? "Replace with links" : "Move to To Delete"}
        busy={busy}
        ops={pending.dry.done}
        onConfirm={() => apply(pending)}
        onCancel={() => setPending(null)}
      >
        <p>
          {link
            ? "Each copy goes to To Delete and a link to the copy you keep takes its place, so anything that points at that path still opens the file. "
            : "Each copy goes to To Delete, keeping its path. "}
          Nothing is deleted: Undo puts {n === 1 ? "it" : "them"} back{link ? " and removes the link" : ""}, and you empty
          To Delete {inFileManager()} yourself.
        </p>
        <PlanList ops={pending.dry.done} />
        <CarryOverList items={pending.dry.carry_over} asked={pending.body.carry_over ?? true} />
      </ConfirmPlan>
    );
  })();

  if (fold?.folded)
    return (
      <Card title="Duplicates" icon={<Copy />} fold={fold} actions={reset}>
        <p className="hint">
          {foldedLine(check, result && (result.groups_total > 0 ? plural(result.groups_total, "group") + " of identical files" : "No duplicates."))}
        </p>
      </Card>
    );
  return (
    <Card title="Duplicates" icon={<Copy />} fold={fold} actions={reset}>
      <p>
        Finds files with exactly the same content. Only files that share a size with another file are read, and a
        file read before is not read again.
      </p>
      {!check.running && (
        <div className="duplicates-estimate">
          {est && est.to_read_files > 0 ? (
            <p>
              Starting reads <strong>{groupDigits(est.to_read_files)}</strong> {est.to_read_files === 1 ? "file" : "files"},{" "}
              <strong>{formatSize(est.to_read_bytes)}</strong> in all
              {est.known > 0 && `; ${groupDigits(est.known)} more already have a stored fingerprint and are not read again`}.
            </p>
          ) : est ? (
            <p>
              Nothing needs to be read
              {est.candidates > 0 ? `: all ${groupDigits(est.candidates)} files that share a size were read before` : ": no two files share a size"}.
            </p>
          ) : null}
          {est && est.to_read_files > 0 && (
            <p className="notice" role="note">
              Reading a file that is kept online-only in Google Drive for desktop downloads it first. You can stop at
              any time; what was read is kept.
            </p>
          )}
        </div>
      )}
      <div className="check-actions">
        {check.running ? (
          <button type="button" onClick={check.stop}>
            Stop
          </button>
        ) : (
          <button type="button" className="primary" onClick={start} disabled={check.starting || busy}>
            {result ? "Find duplicates again" : "Find duplicates"}
          </button>
        )}
      </div>
      {check.running && check.job && <JobProgress job={check.job} />}
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
      {result && !check.running && (
        <>
          <p className="duplicates-summary" role="status">
            {check.job?.state === "stopped" || !result.complete ? "Stopped early. " : ""}
            {plural(result.groups_total, "group")} of identical files; {plural(result.name_groups_total, "name")} used by files
            with different content.
            {result.read_files > 0 && ` Read ${plural(result.read_files, "file")} this time.`}
            {result.changed > 0 && ` ${plural(result.changed, "file")} changed since the last scan and were left out.`}
          </p>
          {result.unreadable.length > 0 && (
            <details>
              <summary>{plural(result.unreadable.length, "file")} could not be read</summary>
              <ul>
                {result.unreadable.map((u) => (
                  <li key={u.path}>
                    <code>{visible(u.path)}</code> ({visible(u.reason)})
                  </li>
                ))}
              </ul>
            </details>
          )}
          <h4>Identical copies</h4>
          {groups.length === 0 ? (
            <p className="hint">No identical files found.</p>
          ) : (
            <>
              <div className="dup-bulk">
                <label className="check">
                  <input type="checkbox" checked={carry} onChange={(e) => setCarry(e.target.checked)} />
                  Also add what the removed copies had (tags, collections, star, notes, checklist, tray items, From and
                  For) to the kept copy
                </label>
                <div className="check-actions">
                  <button type="button" disabled={busy || bulkCopies === 0} onClick={() => bulk("quarantine")}>
                    Move the other copies of the ticked groups to To Delete…
                  </button>
                  <button type="button" disabled={busy || bulkCopies === 0} onClick={() => bulk("link")}>
                    Replace them with links…
                  </button>
                </div>
                <p className="hint">
                  Pick the copy to keep in each group (the suggestion is the one in a numbered folder, then the oldest).
                  Files marked Important or locked are never removed.
                  {result.groups_total > groups.length && ` Showing ${groups.length} of ${result.groups_total} groups.`}
                </p>
              </div>
              <ul className="dup-groups">
                {groups.map((g) => (
                  <Group
                    key={g.sha256}
                    group={g}
                    keep={keepOf(g)}
                    skipped={skipped}
                    included={!excluded.has(g.sha256)}
                    busy={busy || pending !== null}
                    onKeep={(id) => setKeeps((k) => ({ ...k, [g.sha256]: id }))}
                    onToggle={(id) =>
                      setSkipped((s) => {
                        const next = new Set(s);
                        if (!next.delete(id)) next.add(id);
                        return next;
                      })
                    }
                    onInclude={() =>
                      setExcluded((s) => {
                        const next = new Set(s);
                        if (!next.delete(g.sha256)) next.add(g.sha256);
                        return next;
                      })
                    }
                    onAct={(action) => begin([g], action)}
                  />
                ))}
              </ul>
            </>
          )}
          <h4>Same name, different content</h4>
          <p className="hint">
            Probably versions of a document, not copies, so nothing here is offered for removal. Open them to compare.
          </p>
          {result.name_groups.length === 0 ? (
            <p className="hint">None found.</p>
          ) : (
            <ul className="dup-groups">
              {result.name_groups.map((g) => (
                <NameGroup key={g.name + g.files[0].drive_id} name={g.name} files={g.files} />
              ))}
              {result.name_groups_total > result.name_groups.length && (
                <li className="hint">
                  Showing {result.name_groups.length} of {result.name_groups_total} names.
                </li>
              )}
            </ul>
          )}
        </>
      )}
      {confirmView}
    </Card>
  );
}

function NameGroup({ name, files }: { name: string; files: DupFile[] }) {
  const [a, b] = files;
  const sideBySide =
    folderOf(a.path) !== folderOf(b.path)
      ? `/browse?${new URLSearchParams({ left: folderOf(a.path), right: folderOf(b.path) })}`
      : null;
  return (
    <li className="dup-group">
      <header className="dup-group-head">
        <FileSearch size={14} aria-hidden="true" />
        <strong>{visible(name)}</strong>
        <span className="hint">{plural(files.length, "file")}</span>
        {sideBySide && (
          <Link to={sideBySide} className="card-link" aria-label={`Compare ${visible(name)} side by side in Browse`}>
            Compare side by side
          </Link>
        )}
      </header>
      <ul className="dup-files">
        {files.map((f) => (
          <li key={f.drive_id} className="dup-file dup-file-plain">
            <span className="dup-path">
              <code title={visible(f.path)}>{visible(f.path)}</code>
              <span className="hint">
                {formatSize(f.size)}
                {f.mtime !== null && `, ${shortDate(f.mtime)}`}
              </span>
            </span>
            <span className="dup-actions">
              <Link to={browseTo(f)} className="card-link">
                Show in Browse
              </Link>
            </span>
          </li>
        ))}
      </ul>
    </li>
  );
}
