/** Convert ##. Important: the app takes over the user's folder of shortcuts, one
 * top-level entry at a time (spec §3.4). Each link becomes a member of ! Important in
 * the group named by its subfolder; each real file moves into the archive folder chosen
 * for the entry (mirroring its subfolder path) and becomes a member. Every conversion is
 * previewed (the exact ops, members, groups, link names and notes), bound to its preview
 * by a fingerprint, and applied as its own undoable batch. The same patterns as Convert
 * ##. Ongoing: Quick Look, Open and Show in Finder on every entry and item. */
import { CircleCheck } from "lucide-react";
import { type RefObject, useRef, useState } from "react";
import {
  ApiError,
  type CollectionChange,
  type ConvertPlan,
  type ConvertResult,
  errorText,
  type ImportantConvertBody,
  type OngoingEntry,
  useImportantConvert,
  useImportantEntries,
  useImportantPreview,
} from "../api/client";
import { changeLines } from "../components/collectionText";
import { type RefusedRoot } from "../components/FolderBrowser";
import { FolderPicker } from "../components/FolderPicker";
import { baseName } from "../paths";

/** The converter refuses these destinations too (``_forbidden_destinations``): the
 * folder browser dims them like ``##. Ongoing`` and the quarantine. */
const CONVERT_REFUSES: readonly RefusedRoot[] = ["important", "inbox"];
import { LastChange } from "../components/LastChange";
import { ConfirmPlan, snapshotKey } from "../components/PlanPreview";
import { useBlockToastActions, useToast } from "../components/Toasts";
import { useUndoConfirm } from "../components/UndoConfirm";
import { EmptyState } from "../components/ui/EmptyState";
import { TipButton } from "../components/ui/TipButton";
import { Toolbar } from "../components/ui/Toolbar";
import { plural } from "../format";
import { visible } from "../text";
import { EntryHeader, FolderItems, GreyEntry, type Look, NEEDS_FOLDER, useEntryQuickLook } from "./ConvertOngoing";

const STALE_CODE = "stale_preview";
/** Shown beside the conversions that can be undone. */
export const UNDO_HINT =
  "Undo puts the files back where they were. If you took one of them out of Important since, add it back to its group first.";

type View = Pick<CollectionChange, "problems" | "batch" | "ongoing_status">;
type Done = { batchId: string; title: string; view: View };
type Pending = { body: ImportantConvertBody; plan: ConvertPlan };


/** The preview's members: where each goes (its group) and the name its link keeps. */
function PlanMembers({ plan }: { plan: ConvertPlan }) {
  return (
    <>
      <p>{plural(plan.members.length, "member")}:</p>
      <ul className="important-plan-members">
        {plan.members.map((m, i) => {
          const group = plan.groups[i] ?? "";
          const linkName = plan.link_names[i] || baseName(m);
          return (
            <li key={`${m}-${i}`}>
              <code>{visible(m)}</code> → {group ? <>group <b>{visible(group.replaceAll("/", " › "))}</b></> : "the top of Important"}
              {linkName !== baseName(m) && (
                <>
                  , linked as <code>{visible(linkName)}</code>
                </>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}

type RowProps = {
  entry: OngoingEntry;
  look: Look;
  inFlight: RefObject<boolean>;
  locked: boolean;
  onActive: (active: boolean) => void;
  onSkip: () => void;
  onConverted: (entry: OngoingEntry, result: ConvertResult) => void;
};

function EntryRow({ entry, look, inFlight, locked, onActive, onSkip, onConverted }: RowProps) {
  const preview = useImportantPreview();
  const convert = useImportantConvert();
  const [destination, setDestination] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const generation = useRef(0); // an answer for an earlier state of the field is dropped
  // Only real files need a place in the archive: a folder of shortcuts and subfolders
  // holds none
  const needsDestination = entry.real_files > 0;

  const edit = (change: () => void) => {
    change();
    generation.current += 1;
    setPending(null);
    setStale(false);
    setError(null);
  };
  const body = (): ImportantConvertBody => ({
    rel: entry.rel,
    destination: needsDestination ? destination.trim() : null,
  });
  const notReady = needsDestination && destination.trim() === "" ? NEEDS_FOLDER : null;
  const busy = preview.isPending || convert.isPending || locked;

  const start = async () => {
    if (inFlight.current || notReady) return;
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
      const result = await convert.mutateAsync({ ...p.body, fingerprint: p.plan.fingerprint });
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
      {needsDestination && (
        <div className="ongoing-entry-form">
          <FolderPicker
            label={
              entry.kind === "folder"
                ? `Archive folder for its ${plural(entry.real_files, "file")} (required)`
                : "Archive folder (required)"
            }
            required
            refuse={CONVERT_REFUSES}
            value={destination}
            onChange={(folder) => edit(() => setDestination(folder))}
          />
        </div>
      )}
      <div className="actions">
        <button type="button" disabled={busy} onClick={onSkip}>
          Skip
        </button>
        <TipButton className="primary" disabled={notReady !== null || busy} disabledReason={notReady} onClick={() => void start()}>
          Preview
        </TipButton>
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
          confirmLabel="Convert"
          intro={
            <>
              <p>Into ! Important ({plural(pending.plan.existing_members, "file")} there now)</p>
              {pending.plan.notes.map((n) => (
                <p key={n} className="notice">
                  {visible(n)}
                </p>
              ))}
              <PlanMembers plan={pending.plan} />
            </>
          }
          onConfirm={() => void apply(pending)}
          onCancel={() => setPending(null)}
        />
      )}
    </li>
  );
}

export default function ConvertImportant() {
  const entries = useImportantEntries();
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
        <Toolbar title="Convert ##. Important" />
        <div className="ongoing-body">
          {entries.isError ? (
            <p className="error" role="alert">
              Could not load ##. Important. {visible(errorText(entries.error))}
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
        title="Convert ##. Important"
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
          Each shortcut becomes a member of ! Important, in the group named by its subfolder; each real file moves into the
          archive folder you choose. Every conversion is previewed first and can be undone on its own.
        </p>
        {entries.isError && (
          <p className="notice" role="alert">
            The list could not be refreshed: {visible(errorText(entries.error))}
          </p>
        )}
        {done.length > 0 && <p className="hint important-undo-hint">{UNDO_HINT}</p>}
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
