/** Duplicates: the check for files with the same content (hashing only files that share a
 * size with another, saying first how much will be read), the groups with a copy to keep
 * and a choice of what to do with the others, and the same-name files with other content,
 * listed for review only. Moving copies to To Delete or replacing them with a link to the
 * kept copy is one previewed batch with one Undo. */
import { CircleSlash2, Copy, FileSearch, Link as LinkIcon, Trash2 } from "lucide-react";
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
import { Segmented } from "../ui/Segmented";
import { Tag } from "../ui/Tag";
import { IgnoreButton, IgnoredList, useIgnore } from "./Ignore";
import { JobProgress } from "./JobProgress";
import { foldedLine, ResetButton } from "./ListChecks";
import { useMaintenanceJob } from "./useMaintenanceJob";
import { useFold } from "./view";


const PLACE_LABEL: Record<DupFile["place"], string | null> = { numbered: null, inbox: "Inbox", other: null };
const baseName = (path: string) => path.slice(path.lastIndexOf("/") + 1);
const folderOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
const browseTo = (file: DupFile) =>
  `/browse?${new URLSearchParams({ path: folderOf(file.path), select: file.drive_id })}`;

const refusal = (e: unknown) => (e instanceof ApiError && e.detail ? e.detail : errorText(e));

type Pending = { body: DuplicateResolveBody; dry: DuplicateResolveResult; moved: number; linked: number };

/** The toast after Apply: "Moved 1 duplicate to To Delete and replaced 1 with a link". */
const doneWords = (moved: number, linked: number) =>
  moved === 0
    ? `Replaced ${plural(linked, "duplicate")} with links`
    : `Moved ${plural(moved, "duplicate")} to To Delete${linked > 0 ? ` and replaced ${linked} with a link` : ""}`;

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

/** What happens to a copy that is not kept: nothing, moved to To Delete, or moved and
 * replaced with a link to the kept copy. To Delete until chosen otherwise. */
type Choice = "leave" | "quarantine" | "link";

/** The copies that could go: not the kept one and not Important or locked. */
const candidatesOf = (group: DupGroup, keep: string) => group.files.filter((f) => f.drive_id !== keep && !f.locked);
/** What a group's Apply does: the copies moved, and those of them replaced with a link. */
const changesOf = (group: DupGroup, keep: string, choices: Record<string, Choice>) => {
  const chosen = candidatesOf(group, keep).map((f) => ({ f, c: choices[f.drive_id] ?? "quarantine" }));
  return {
    others: chosen.filter((x) => x.c !== "leave").map((x) => x.f.drive_id),
    links: chosen.filter((x) => x.c === "link").map((x) => x.f.drive_id),
  };
};

/** "1 to To Delete, 1 replaced with a link" (what Apply will do). */
const changeWords = (moved: number, linked: number) =>
  [moved > 0 && `${moved} to To Delete`, linked > 0 && `${linked} replaced with a link`].filter(Boolean).join(", ");

const CHOICES = [
  { value: "leave" as const, label: <CircleSlash2 size={14} aria-hidden="true" />, title: "Leave it where it is", ariaLabel: "Leave" },
  { value: "quarantine" as const, label: <Trash2 size={14} aria-hidden="true" />, title: "Move it to To Delete", ariaLabel: "To Delete" },
  {
    value: "link" as const,
    label: <LinkIcon size={14} aria-hidden="true" />,
    title: "Move it to To Delete and put a link to the kept copy in its place",
    ariaLabel: "Link",
  },
];

/** A copy in a group, on two lines: its folder (the group's head already names the file),
 * then its own name where it differs, its size and date. A copy not kept has its choice:
 * leave it, To Delete, or replace with a link. */
function FileRow({
  file,
  groupName,
  groupKey,
  keep,
  choice,
  onKeep,
  onChoose,
}: {
  file: DupFile;
  groupName: string;
  groupKey: string;
  keep: boolean;
  choice: Choice;
  onKeep: () => void;
  onChoose: (choice: Choice) => void;
}) {
  const place = PLACE_LABEL[file.place];
  return (
    <li className="dup-file" data-keep={keep ? "" : undefined}>
      <label className="dup-keep">
        <input type="radio" name={`keep-${groupKey}`} checked={keep} onChange={onKeep} />
        <span>Keep</span>
      </label>
      <span className="dup-path dup-copy">
        <code title={visible(file.path)}>{visible(folderOf(file.path) || "Top level")}</code>
        <span className="dup-meta">
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
      </span>
      <span className="dup-actions">
        {!keep && file.locked && (
          <span className="hint" title={file.why ?? undefined}>
            Stays
          </span>
        )}
        {!keep && !file.locked && (
          <Segmented
            ariaLabel={`What to do with ${visible(file.path)}`}
            className="dup-choice"
            options={CHOICES}
            value={choice}
            onChange={onChoose}
          />
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
  choices,
  included,
  busy,
  onKeep,
  onChoose,
  onInclude,
  onApply,
  onIgnore,
}: {
  group: DupGroup;
  keep: string;
  choices: Record<string, Choice>;
  included: boolean;
  busy: boolean;
  onKeep: (id: string) => void;
  onChoose: (id: string, choice: Choice) => void;
  onInclude: () => void;
  onApply: () => void;
  onIgnore: () => void;
}) {
  const { others, links } = changesOf(group, keep, choices);
  const why = others.length === 0 ? "Every copy is left where it is" : undefined;
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
        <IgnoreButton label={name} disabled={busy} onClick={onIgnore} />
      </header>
      <ul className="dup-files">
        {group.files.map((f) => (
          <FileRow
            key={f.drive_id}
            file={f}
            groupName={name}
            groupKey={group.sha256}
            keep={f.drive_id === keep}
            choice={choices[f.drive_id] ?? "quarantine"}
            onKeep={() => onKeep(f.drive_id)}
            onChoose={(c) => onChoose(f.drive_id, c)}
          />
        ))}
      </ul>
      <div className="dup-group-actions">
        <button type="button" disabled={busy || !!why} title={why} onClick={onApply}>
          Apply…
        </button>
        {!why && <span className="hint">{changeWords(others.length - links.length, links.length)}</span>}
      </div>
    </li>
  );
}

export function Duplicates() {
  const check = useMaintenanceJob("duplicates");
  const ignore = useIgnore(check.reload);
  const estimate = useDuplicateEstimate();
  const resolve = useResolveDuplicates();
  const toast = useToast();
  const undo = useUndoConfirm(() => check.reload());
  const result = check.job?.duplicates ?? null;
  const [keeps, setKeeps] = useState<Record<string, string>>({});
  const [choices, setChoices] = useState<Record<string, Choice>>({});
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
  const changesIn = (g: DupGroup) => changesOf(g, keepOf(g), choices);
  const bodyFor = (groups: DupGroup[], dry_run: boolean): DuplicateResolveBody => ({
    groups: groups.map((g) => ({ keep: keepOf(g), ...changesIn(g) })),
    action: "quarantine",
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

  const begin = (groups: DupGroup[]) => {
    const usable = groups.filter((g) => changesIn(g).others.length > 0);
    if (usable.length === 0 || pending !== null) return;
    void guarded(async () => {
      const body = bodyFor(usable, true);
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
      setPending({
        body,
        dry,
        moved: body.groups.reduce((n, g) => n + g.others.length - (g.links?.length ?? 0), 0),
        linked: body.groups.reduce((n, g) => n + (g.links?.length ?? 0), 0),
      });
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
      const linked = result.done.filter((op) => op.kind === "symlink").length;
      if (moved > 0) {
        const target = { batchId: result.batch_id };
        toast({
          kind: complete ? "info" : "warning",
          text: `${complete ? "" : "Partly applied: "}${doneWords(moved - linked, linked)}`,
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
  const bulkCopies = includedGroups.reduce((n, g) => n + changesIn(g).others.length, 0);
  /** Every copy that can go in the ticked groups set to one choice. */
  const chooseAll = (c: Choice) =>
    setChoices((now) => {
      const next = { ...now };
      for (const g of includedGroups) for (const f of candidatesOf(g, keepOf(g))) next[f.drive_id] = c;
      return next;
    });
  const est = estimate.data;
  const clearChoices = () => {
    setKeeps({});
    setChoices({});
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
    const { moved, linked } = pending;
    const link = linked > 0;
    const n = moved + linked;
    return (
      <ConfirmPlan
        planKey={snapshotKey(pending.body)}
        title={
          moved === 0
            ? `Replace ${plural(n, "duplicate")} with links?`
            : linked === 0
              ? `Move ${plural(n, "duplicate")} to To Delete?`
              : `Apply ${plural(n, "change")} to duplicates?`
        }
        danger={moved > 0}
        confirmLabel={moved === 0 ? "Replace with links" : linked === 0 ? "Move to To Delete" : "Apply"}
        busy={busy}
        ops={pending.dry.done}
        onConfirm={() => apply(pending)}
        onCancel={() => setPending(null)}
      >
        <p>
          {moved > 0 && "Each copy goes to To Delete, keeping its path. "}
          {link &&
            `${moved > 0 ? "A copy replaced with a link also goes there" : "Each copy goes to To Delete"}, and a link to the copy you keep takes its place, so anything that points at that path still opens the file. `}
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
                  <button type="button" disabled={busy || bulkCopies === 0} onClick={() => begin(includedGroups)}>
                    Apply the ticked groups…
                  </button>
                  <span className="hint">Set every copy in them to</span>
                  <button
                    type="button"
                    className="link-button"
                    disabled={busy}
                    onClick={() => chooseAll("quarantine")}
                    aria-label="Set every copy in the ticked groups to To Delete"
                  >
                    To Delete
                  </button>
                  <button
                    type="button"
                    className="link-button"
                    disabled={busy}
                    onClick={() => chooseAll("link")}
                    aria-label="Set every copy in the ticked groups to Link"
                  >
                    Link
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
                    choices={choices}
                    included={!excluded.has(g.sha256)}
                    busy={busy || pending !== null}
                    onKeep={(id) => setKeeps((k) => ({ ...k, [g.sha256]: id }))}
                    onChoose={(id, c) => setChoices((now) => ({ ...now, [id]: c }))}
                    onInclude={() =>
                      setExcluded((s) => {
                        const next = new Set(s);
                        if (!next.delete(g.sha256)) next.add(g.sha256);
                        return next;
                      })
                    }
                    onApply={() => begin([g])}
                    onIgnore={() =>
                      void ignore.ignore({
                        kind: "duplicates",
                        key: g.sha256,
                        label: baseName(g.files[0].path),
                        members: g.files.map((f) => f.drive_id),
                      })
                    }
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
                <NameGroup
                  key={g.name + g.files[0].drive_id}
                  name={g.name}
                  files={g.files}
                  busy={ignore.busy}
                  onIgnore={() =>
                    void ignore.ignore({ kind: "versions", key: g.name, label: g.name, members: g.files.map((f) => f.drive_id) })
                  }
                />
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
      {!check.running && <IgnoredList kinds={["duplicates", "versions"]} onChange={check.reload} />}
      {confirmView}
    </Card>
  );
}

function NameGroup({
  name,
  files,
  busy,
  onIgnore,
}: {
  name: string;
  files: DupFile[];
  busy: boolean;
  onIgnore: () => void;
}) {
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
        <IgnoreButton label={name} disabled={busy} onClick={onIgnore} />
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
