/** Settings → Filing rules: every rule in the order they are tried, each with its record
 * (how often its suggestion was kept), a way to edit, move and delete it, a "Test a
 * document" check of which rules match a file in the Inbox, the files that could not be
 * loaded, and the switch for the offer to make a rule after a hand filing. Editing and
 * making a rule use the rule sheet, which asks for a replay before it saves. */
import { ChevronDown, ChevronRight, ChevronUp, Plus, Trash2, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  errorText,
  type Rule,
  type RuleDraft,
  useDeleteRule,
  useExplain,
  useFileSuggestions,
  useInbox,
  useMoveRule,
  useRules,
  useRulesState,
} from "../../api/client";
import { plural } from "../../format";
import { visible } from "../../text";
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
  const words = [...r.when.text_contains, ...zones.flatMap((z) => z.text_contains ?? [])].join(", ");
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
