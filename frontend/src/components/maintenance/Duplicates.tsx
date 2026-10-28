/** Duplicates: the check for files with the same content (hashing only files that share a
 * size with another, saying first how much will be read), the groups with a copy to keep
 * and a choice of what to do with the others, and the same-name files with other content
 * (versions), which can be compared side by side and get the same choices, left in place
 * until chosen otherwise. Moving copies to To Delete or replacing them with a link to the
 * kept copy is one previewed batch with one Undo. */
import { CircleSlash2, Copy, FileSearch, Link as LinkIcon, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  type CarryOver,
  type DupFile,
  type DupGroup,
  type DupNameGroup,
  type DuplicateResolveBody,
  type DuplicateResolveResult,
  errorText,
  useDuplicateEstimate,
  useResolveDuplicates,
} from "../../api/client";
import { useStyle } from "../../appearance";
import { formatSize, groupDigits, plural, shortDate } from "../../format";
import { dialogOpen } from "../../keyboard";
import { inFileManager } from "../../fileManager";
import { visible } from "../../text";
import { ConfirmPlan, PlanList, snapshotKey } from "../PlanPreview";
import { undoAction, useBlockToastActions, useToast } from "../Toasts";
import { useUndoConfirm } from "../UndoConfirm";
import { type QLFile, useQuickLook } from "../useQuickLook";
import { Card } from "../ui/Card";
import { Segmented } from "../ui/Segmented";
import { Tag } from "../ui/Tag";
import { Compare } from "./Compare";
import { IgnoreButton, IgnoredList, useIgnore } from "./Ignore";
import { JobProgress } from "./JobProgress";
import { CheckHead, foldedLine, ResetButton } from "./ListChecks";
import { QuickLookButton, ShowInBrowse } from "./ShowInBrowse";
import { useMaintenanceJob } from "./useMaintenanceJob";
import { useFold } from "./view";
import { baseName, extOf } from "../../paths";


const PLACE_LABEL: Record<DupFile["place"], string | null> = { numbered: null, inbox: "Inbox", other: null };
const folderOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
const browseTo = (file: DupFile) =>
  `/browse?${new URLSearchParams({ path: folderOf(file.path), select: file.drive_id })}`;

const qlFile = (f: DupFile): QLFile => ({ drive_id: f.drive_id, name: null, path: f.path, ext: extOf(f.path) });

const refusal = (e: unknown) => (e instanceof ApiError && e.detail ? e.detail : errorText(e));

/** A group to resolve: identical copies (``content``) or files sharing a name with other
 * content (``name``, versions of a document). */
type Batch = {
  key: string;
  same: "content" | "name";
  name: string;
  files: DupFile[];
  keep: string; // the suggested file to keep
  size: number | null; // the copies' size (identical copies only)
};

const ofContent = (g: DupGroup): Batch => ({
  key: g.sha256,
  same: "content",
  name: baseName(g.files[0].path),
  files: g.files,
  keep: g.keep,
  size: g.size,
});

/** Versions: keep one that cannot be removed, then one in a numbered folder, then the newest. */
const ofName = (g: DupNameGroup): Batch => {
  const rank = { numbered: 0, other: 1, inbox: 2 } as const;
  const best = [...g.files].sort(
    (a, b) => Number(!a.locked) - Number(!b.locked) || rank[a.place] - rank[b.place] || (b.mtime ?? 0) - (a.mtime ?? 0),
  )[0];
  return { key: `name:${g.name}:${g.files[0].drive_id}`, same: "name", name: g.name, files: g.files, keep: best.drive_id, size: null };
};

type Noun = "duplicate" | "version";
type Pending = { body: DuplicateResolveBody; dry: DuplicateResolveResult; moved: number; linked: number; noun: Noun };

/** The toast after Apply: "Moved 1 duplicate to To Delete and replaced 1 with a link". */
const doneWords = (moved: number, linked: number, noun: Noun) =>
  moved === 0
    ? `Replaced ${plural(linked, noun)} with links`
    : `Moved ${plural(moved, noun)} to To Delete${linked > 0 ? ` and replaced ${linked} with a link` : ""}`;

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

/** A copy not chosen for yet: identical copies go to To Delete, versions stay (they differ,
 * so removing one is a decision made after comparing them). */
const defaultChoice = (group: Batch): Choice => (group.same === "name" ? "leave" : "quarantine");
/** The copies that could go: not the kept one and not Important or locked. */
const candidatesOf = (group: Batch, keep: string) => group.files.filter((f) => f.drive_id !== keep && !f.locked);
/** What a group's Apply does: the copies moved, and those of them replaced with a link. */
const changesOf = (group: Batch, keep: string, choices: Record<string, Choice>) => {
  const chosen = candidatesOf(group, keep).map((f) => ({ f, c: choices[f.drive_id] ?? defaultChoice(group) }));
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
  onLook,
}: {
  file: DupFile;
  groupName: string;
  groupKey: string;
  keep: boolean;
  choice: Choice;
  onKeep: () => void;
  onChoose: (choice: Choice) => void;
  onLook: () => void;
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
        <QuickLookButton onClick={onLook} />
        <ShowInBrowse to={browseTo(file)} />
      </span>
      {file.why && !keep && <span className="hint dup-why">{visible(file.why)}</span>}
    </li>
  );
}

/** A group with its Keep and choices. Identical copies have a tick for the bulk action;
 * versions have Compare instead, and no bulk action (each is decided on its own). */
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
  onLook,
  onCompare,
}: {
  group: Batch;
  keep: string;
  choices: Record<string, Choice>;
  included?: boolean;
  busy: boolean;
  onKeep: (id: string) => void;
  onChoose: (id: string, choice: Choice) => void;
  onInclude?: () => void;
  onApply: () => void;
  onIgnore: () => void;
  onLook: (id: string) => void;
  onCompare?: () => void;
}) {
  const { others, links } = changesOf(group, keep, choices);
  const why = others.length === 0 ? "Every file is left where it is" : undefined;
  const name = group.name;
  return (
    <li className="dup-group">
      <header className="dup-group-head">
        {onInclude ? (
          <label className="check">
            <input type="checkbox" checked={included} onChange={onInclude} aria-label={`Include ${visible(name)} in the bulk action`} />
            <strong>{visible(name)}</strong>
          </label>
        ) : (
          <>
            <FileSearch size={14} aria-hidden="true" />
            <strong>{visible(name)}</strong>
          </>
        )}
        <span className="hint">
          {group.size === null
            ? plural(group.files.length, "file")
            : `${plural(group.files.length, "copy", "copies")} of ${formatSize(group.size)}`}
        </span>
        <IgnoreButton label={name} disabled={busy} onClick={onIgnore} />
      </header>
      <ul className="dup-files">
        {group.files.map((f) => (
          <FileRow
            key={f.drive_id}
            file={f}
            groupName={name}
            groupKey={group.key}
            keep={f.drive_id === keep}
            choice={choices[f.drive_id] ?? defaultChoice(group)}
            onKeep={() => onKeep(f.drive_id)}
            onChoose={(c) => onChoose(f.drive_id, c)}
            onLook={() => onLook(f.drive_id)}
          />
        ))}
      </ul>
      <div className="dup-group-actions">
        {onCompare && (
          <button type="button" onClick={onCompare} aria-label={`Compare the files named ${visible(name)} side by side`}>
            Compare side by side
          </button>
        )}
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
  const [comparing, setComparing] = useState<Batch | null>(null);
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

  const keepOf = (g: Batch) => {
    const chosen = keeps[g.key];
    return chosen && g.files.some((f) => f.drive_id === chosen) ? chosen : g.keep;
  };
  const changesIn = (g: Batch) => changesOf(g, keepOf(g), choices);
  const bodyFor = (groups: Batch[], dry_run: boolean): DuplicateResolveBody => ({
    groups: groups.map((g) => ({ keep: keepOf(g), ...changesIn(g), same: g.same })),
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

  const begin = (groups: Batch[]) => {
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
        noun: usable.every((g) => g.same === "name") ? "version" : "duplicate",
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
          text: `${complete ? "" : "Partly applied: "}${doneWords(moved - linked, linked, p.noun)}`,
          action: undoAction(() => {
            if (inFlight.current || undo.undoing.current || dialogOpen()) return;
            undo.open(target);
          }),
        });
      }
      check.reload();
    });
  };

  const groups = (result?.groups ?? []).map(ofContent);
  const versions = (result?.name_groups ?? []).map(ofName);
  // Quick Look moves through every file shown, identical copies first, then same-name files
  const lookable = [...groups, ...versions].flatMap((g) => g.files);
  const [lookAt, setLookAt] = useState(0);
  // opened by a row's button only: a Space on the page keeps scrolling it
  const byButton = useRef(false);
  const quickLook = useQuickLook(lookable.map(qlFile), lookAt, setLookAt, { canOpen: () => byButton.current });
  const look = (id: string) => {
    const i = lookable.findIndex((f) => f.drive_id === id);
    if (i < 0) return;
    setLookAt(i);
    byButton.current = true;
    quickLook.open();
    byButton.current = false;
  };
  const includedGroups = groups.filter((g) => !excluded.has(g.key));
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
  const [lookStyle] = useStyle();
  const isNew = lookStyle === "new";
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
    const { moved, linked, noun } = pending;
    const link = linked > 0;
    const n = moved + linked;
    const differ = pending.body.groups.some((g) => g.same === "name");
    return (
      <ConfirmPlan
        planKey={snapshotKey(pending.body)}
        title={
          moved === 0
            ? `Replace ${plural(n, noun)} with links?`
            : linked === 0
              ? `Move ${plural(n, noun)} to To Delete?`
              : `Apply ${plural(n, "change")} to ${noun}s?`
        }
        danger={moved > 0}
        confirmLabel={moved === 0 ? "Replace with links" : linked === 0 ? "Move to To Delete" : "Apply"}
        busy={busy}
        ops={pending.dry.done}
        onConfirm={() => apply(pending)}
        onCancel={() => setPending(null)}
      >
        {differ && (
          <p className="notice" role="note">
            {noun === "version" ? "These files are" : "Some of these files are"} not copies: their content differs from
            the file you keep{link ? ", and a link opens the kept one instead" : ""}.
          </p>
        )}
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

  // New: the header carries the status line and the one button
  const summary = result
    ? [
        result.groups_total > 0 && `${plural(result.groups_total, "group")} of identical files`,
        result.name_groups_total > 0 && `${plural(result.name_groups_total, "name")} with other content`,
      ]
        .filter(Boolean)
        .join(", ")
    : "";
  const head = isNew ? <CheckHead check={check} found={summary !== ""} summary={summary} label="Check" onStart={start} busy={busy} reset={reset} /> : reset;
  if (fold?.folded)
    return (
      <Card title="Duplicates" icon={<Copy />} className={isNew ? "check-card check-duplicates" : undefined} fold={fold} actions={head}>
        {isNew ? null : (
          <p className="hint">
            {foldedLine(check, result && (result.groups_total > 0 ? plural(result.groups_total, "group") + " of identical files" : "No duplicates."))}
          </p>
        )}
      </Card>
    );
  return (
    <Card title="Duplicates" icon={<Copy />} className={isNew ? "check-card check-duplicates" : undefined} fold={fold} actions={head}>
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
      {!isNew && (
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
      )}
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
          {(groups.length > 0 || versions.length > 0) && (
            <label className="check">
              <input type="checkbox" checked={carry} onChange={(e) => setCarry(e.target.checked)} />
              Also add what the removed copies had (tags, collections, star, notes, checklist, tray items, From and
              For) to the kept copy
            </label>
          )}
          <h4>Identical copies</h4>
          {groups.length === 0 ? (
            <p className="hint">No identical files found.</p>
          ) : (
            <>
              <div className="dup-bulk">
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
                    key={g.key}
                    group={g}
                    keep={keepOf(g)}
                    choices={choices}
                    included={!excluded.has(g.key)}
                    busy={busy || pending !== null}
                    onKeep={(id) => setKeeps((k) => ({ ...k, [g.key]: id }))}
                    onChoose={(id, c) => setChoices((now) => ({ ...now, [id]: c }))}
                    onInclude={() =>
                      setExcluded((s) => {
                        const next = new Set(s);
                        if (!next.delete(g.key)) next.add(g.key);
                        return next;
                      })
                    }
                    onApply={() => begin([g])}
                    onLook={look}
                    onIgnore={() =>
                      void ignore.ignore({
                        kind: "duplicates",
                        key: g.key,
                        label: g.name,
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
            Probably versions of a document, or the same document saved another way, so every file stays where it is
            until you choose otherwise. Compare them side by side, then keep one and move or link the others.
          </p>
          {versions.length === 0 ? (
            <p className="hint">None found.</p>
          ) : (
            <ul className="dup-groups">
              {versions.map((g) => (
                <Group
                  key={g.key}
                  group={g}
                  keep={keepOf(g)}
                  choices={choices}
                  busy={busy || pending !== null || ignore.busy}
                  onKeep={(id) => setKeeps((k) => ({ ...k, [g.key]: id }))}
                  onChoose={(id, c) => setChoices((now) => ({ ...now, [id]: c }))}
                  onApply={() => begin([g])}
                  onLook={look}
                  onCompare={() => setComparing(g)}
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
      {quickLook.view}
      {comparing && (
        <Compare
          name={comparing.name}
          files={comparing.files}
          keep={keepOf(comparing)}
          onKeep={(id) => setKeeps((k) => ({ ...k, [comparing.key]: id }))}
          onClose={() => setComparing(null)}
        />
      )}
    </Card>
  );
}
