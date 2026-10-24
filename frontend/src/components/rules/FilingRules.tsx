/** Settings → Filing rules: every rule in the order they are tried, each with its record
 * (how often its suggestion was kept), a way to edit, move and delete it, a "Test a
 * document" check of which rules match a file in the Inbox, the files that could not be
 * loaded, and the switch for the offer to make a rule after a hand filing. Editing and
 * making a rule use the rule sheet, which asks for a replay before it saves. */
import { ChevronDown, ChevronRight, ChevronUp, Plus, Trash2, TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorText,
  type ResolvedOp,
  type Rule,
  type RuleDraft,
  useDeleteRule,
  useExplain,
  useFileSuggestions,
  useInbox,
  useMoveRule,
  useQuarantineUnusedPictures,
  useRules,
  useRulesState,
} from "../../api/client";
import { plural } from "../../format";
import { visible } from "../../text";
import { ConfirmPlan, snapshotKey } from "../PlanPreview";
import { undoAction, useToast } from "../Toasts";
import { useUndoConfirm } from "../UndoConfirm";
import { IconButton } from "../ui/IconButton";
import { Sheet } from "../ui/Sheet";
import { SamplePage } from "../zones/SamplePage";
import { PeopleSettings } from "./PeopleSettings";
import { RuleSheet, rewriteNote } from "./RuleSheet";

/** "kept 9 of 9", "changed 2 of 5", "not used yet". */
export function record({ suggested, changed }: Rule["stats"]): string {
  if (suggested === 0) return "not used yet";
  return changed > 0 ? `changed ${changed} of ${suggested}` : `kept ${suggested} of ${suggested}`;
}

const fresh = (taken: string[]): RuleDraft => {
  let n = 1;
  while (taken.includes(n === 1 ? "new-rule" : `new-rule-${n}`)) n += 1;
  return { id: n === 1 ? "new-rule" : `new-rule-${n}`, words: [], folder: null, name: null, tags: [], tray: null, payee: null };
};

/** "the folder, the name" for the fields a rule wins. */
const gives = (wins: string[]) => `gives ${wins.map((w) => `the ${w}`).join(", ")}`;

function RuleLine({
  r,
  first,
  last,
  onOpen,
  onMove,
  onDelete,
}: {
  r: Rule;
  first: boolean;
  last: boolean;
  onOpen: () => void;
  onMove: (delta: number) => void;
  onDelete: () => void;
}) {
  const zones = r.when.zones;
  const pictures = zones.filter((z) => z.image).length;
  const words = [
    ...r.when.text_contains,
    ...zones.flatMap((z) => z.text_contains ?? []),
    ...(pictures > 0 ? [pictures === 1 ? "a picture" : `${pictures} pictures`] : []),
  ].join(", ");
  const target = r.then.folder ? `→ ${r.then.folder}` : "";
  return (
    <li className="rule-line">
      <button type="button" className="code-line" onClick={onOpen}>
        <code className="code-line-code">{visible(r.id)}</code>
        <span className="code-line-label">
          {visible(words)}
          {zones.length > 0 && (
            <span className="code-line-zone"> · {zones.length === 1 ? "area" : `${zones.length} areas`} on page 1</span>
          )}
        </span>
        <span className="code-line-summary">
          {[target, record(r.stats), r.learned ? "" : r.file].filter(Boolean).map(visible).join(" · ")}
        </span>
        {r.stats.flagged ? (
          <span className="code-line-warning">
            <TriangleAlert size={13} aria-hidden="true" /> Corrected recently
          </span>
        ) : (
          <span />
        )}
        <ChevronRight size={14} className="code-line-chevron" aria-hidden="true" />
      </button>
      <span className="rule-line-tools">
        {r.learned && (
          <>
            <IconButton icon={<ChevronUp />} label={`Move ${r.id} up`} disabled={first} onClick={() => onMove(-1)} />
            <IconButton icon={<ChevronDown />} label={`Move ${r.id} down`} disabled={last} onClick={() => onMove(1)} />
          </>
        )}
        <IconButton icon={<Trash2 />} label={`Delete rule ${r.id}`} onClick={onDelete} />
      </span>
    </li>
  );
}

/** The picture files no rule uses, and "Move N unused pictures to To Delete": a dry run
 * first (the usual plan in a confirm), then the move, then a toast with Undo. Nothing is
 * deleted; the files wait in To Delete as ``dam rule picture <name>``. */
function UnusedPictures({ names }: { names: string[] }) {
  const move = useQuarantineUnusedPictures();
  const toast = useToast();
  const undo = useUndoConfirm();
  const [plan, setPlan] = useState<{ names: string[]; ops: ResolvedOp[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false); // synchronous: a second click sees it at once

  const guarded = async (work: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null);
    try {
      await work();
    } catch (e) {
      setPlan(null);
      setError(errorText(e));
    } finally {
      inFlight.current = false;
    }
  };
  const preview = () =>
    guarded(async () => {
      const dry = await move.mutateAsync({ names, dry_run: true });
      if (dry.error || dry.failed) throw new Error(dry.error ?? "an operation failed");
      setPlan({ names, ops: dry.done });
    });
  const apply = (previewed: { names: string[]; ops: ResolvedOp[] }) =>
    guarded(async () => {
      setPlan(null);
      const result = await move.mutateAsync({ names: previewed.names, dry_run: false });
      const moved = result.done.filter((o) => o.kind === "picture_to_quarantine").length;
      if (result.error || result.failed) {
        setError(`Stopped after ${moved} of ${previewed.names.length}: ${result.error ?? "an operation failed"}`);
      }
      if (moved > 0) {
        toast({
          kind: "info",
          text: `Moved ${plural(moved, "unused picture")} to To Delete`,
          action: undoAction(() => {
            if (undo.undoing.current) return;
            undo.open({ batchId: result.batch_id });
          }),
        });
      }
    });

  return (
    <>
      <p className="hint rules-unused-pictures">
        {plural(names.length, "picture file")} in config/rules/areas ({names.map(visible).join(", ")}) {names.length === 1 ? "is" : "are"} not used by any rule. Deleting a rule leaves them.{" "}
        <button type="button" onClick={() => void preview()} disabled={move.isPending}>
          Move {plural(names.length, "unused picture")} to To Delete
        </button>
      </p>
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
      {plan && (
        <ConfirmPlan
          planKey={snapshotKey(plan.names)}
          title="Move unused pictures to To Delete?"
          intro={<p>They wait in To Delete until you empty it, and Undo puts them back.</p>}
          confirmLabel={`Move ${plan.names.length}`}
          ops={plan.ops}
          busy={move.isPending}
          onConfirm={() => void apply(plan)}
          onCancel={() => setPlan(null)}
        />
      )}
    </>
  );
}

function TestDocument() {
  const inbox = useInbox();
  const explain = useExplain();
  const [picked, setPicked] = useState("");
  const entries = inbox.data ?? [];
  const sample = entries.find((e) => e.record.drive_id === picked)?.record;
  // the address area and the person's line come with the document's suggestion
  const suggestion = useFileSuggestions(picked, picked !== "");
  const areas = [
    ...(explain.data ?? []).flatMap((x) => x.areas ?? []),
    ...(suggestion.data?.areas ?? []).filter((a) => a.kind === "address"),
  ];
  return (
    <div className="rules-test">
      <div className="field">
        <label htmlFor="rules-test-doc">Test a document</label>
        <select
          id="rules-test-doc"
          value={picked}
          onChange={(e) => {
            setPicked(e.target.value);
            if (e.target.value) explain.mutate(e.target.value);
          }}
        >
          <option value="">Pick a file in the Inbox</option>
          {entries.map((e) => (
            <option key={e.record.drive_id} value={e.record.drive_id}>
              {visible(e.record.name ?? e.record.path)}
            </option>
          ))}
        </select>
      </div>
      {explain.isError && (
        <p className="error" role="alert">
          {visible(errorText(explain.error))}
        </p>
      )}
      {picked && explain.data && (
        <ul className="rules-test-list" aria-label="Rules for this document">
          {explain.data.map((x) => (
            <li key={x.rule_id}>
              <code>{visible(x.rule_id)}</code> {x.matched ? "matches" : "no match"}: {visible(x.why)}
              {x.wins.length > 0 && <> ({gives(x.wins)})</>}
              {(x.zone_lines ?? []).map((lines, i) =>
                lines.length > 0 ? (
                  <span key={i}>
                    {" "}
                    Page 1 in {x.zone_lines.length === 1 ? "the area" : `area ${i + 1}`}: {lines.map((l) => `“${visible(l)}”`).join(", ")}
                  </span>
                ) : null,
              )}
            </li>
          ))}
        </ul>
      )}
      {picked && explain.data && sample && areas.length > 0 && (
        <SamplePage
          driveId={sample.drive_id}
          ext={sample.ext}
          areas={areas}
          person={suggestion.data?.person ?? null}
          personLine={suggestion.data?.person_line ?? null}
        />
      )}
    </div>
  );
}

export function FilingRules() {
  const rules = useRules();
  const move = useMoveRule();
  const remove = useDeleteRule();
  const state = useRulesState();
  const [editing, setEditing] = useState<Rule | RuleDraft | null>(null);
  const [deleting, setDeleting] = useState<Rule | null>(null);
  const [error, setError] = useState<string | null>(null);

  const header = (
    <>
      <h3>Filing rules</h3>
      <p className="hint">
        A rule files a document by the words in it. dam tries them in this order. <Link to="/help#filing-rules">More in Help</Link>
      </p>
    </>
  );
  if (rules.isError) {
    return (
      <section className="filing-codes" aria-label="Filing rules">
        {header}
        <p className="error" role="alert">
          {visible(errorText(rules.error))}
        </p>
      </section>
    );
  }
  if (!rules.data) {
    return (
      <section className="filing-codes" aria-label="Filing rules">
        {header}
        <p className="hint">Loading…</p>
      </section>
    );
  }
  const { rules: list, errors, state: offers } = rules.data;
  const learned = list.filter((r) => r.learned); // only these can be moved
  const run = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(errorText(e));
    }
  };
  const confirmDelete = async () => {
    if (!deleting) return;
    const id = deleting.id;
    setDeleting(null);
    await run(() => remove.mutateAsync(id));
  };

  return (
    <section className="filing-codes" aria-label="Filing rules">
      {header}
      {errors.length > 0 && (
        <div className="banner" role="alert">
          <p>Some rule files could not be loaded:</p>
          <ul>
            {errors.map((p, i) => (
              <li key={`${p.file}-${i}`}>
                <code>{visible(p.file)}</code>: {visible(p.message)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
      <div className="filing-codes-actions">
        <button type="button" onClick={() => setEditing(fresh(list.map((r) => r.id)))}>
          <Plus size={14} aria-hidden="true" /> New rule
        </button>
      </div>
      {list.length === 0 ? (
        <p className="hint">No rules yet. File a document by hand and dam offers to make one.</p>
      ) : (
        <ul className="filing-codes-list rules-list">
          {list.map((r) => (
            <RuleLine
              key={r.id}
              r={r}
              first={r.id === learned[0]?.id}
              last={r.id === learned[learned.length - 1]?.id}
              onOpen={() => setEditing(r)}
              onMove={(delta) => void run(() => move.mutateAsync({ id: r.id, delta }))}
              onDelete={() => setDeleting(r)}
            />
          ))}
        </ul>
      )}
      {(rules.data.unused_pictures ?? []).length > 0 && <UnusedPictures names={rules.data.unused_pictures ?? []} />}
      <TestDocument />
      <div className="rules-offer">
        <label className="check">
          <input
            type="checkbox"
            checked={offers.offer}
            onChange={(e) => void run(() => state.mutateAsync({ offer: e.target.checked }))}
          />
          Offer to make a rule after I file a document by hand
        </label>
        {offers.declined > 0 && (
          <button type="button" onClick={() => void run(() => state.mutateAsync({ clear_declined: true }))}>
            Forget {plural(offers.declined, "declined sender")}
          </button>
        )}
      </div>
      <PeopleSettings />
      {editing && (
        <RuleSheet
          key={editing.id}
          initial={editing}
          replaces={"learned" in editing ? editing.id : undefined}
          samplePage
          onClose={() => setEditing(null)}
        />
      )}
      {deleting && (
        <Sheet
          open
          title={`Delete rule ${visible(deleting.id)}?`}
          onClose={() => setDeleting(null)}
          footer={
            <>
              <button type="button" onClick={() => setDeleting(null)}>
                Cancel
              </button>
              <button type="button" className="primary danger" onClick={() => void confirmDelete()}>
                Delete rule
              </button>
            </>
          }
        >
          <p>The rule is removed from its file. Documents already filed stay where they are.</p>
          {!deleting.learned && <p className="hint">{visible(rewriteNote("Deleting", deleting.file))}</p>}
        </Sheet>
      )}
    </section>
  );
}
