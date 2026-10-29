/** Settings → Filing rules: the people a letter can be for (name and the texts that
 * identify them in the address area), the address area itself, and how far page 1 has
 * been read (with the switch for reading older documents in the background). */
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { errorText, type PageBox, type Person, usePage1Backfill, usePeople, useSavePeople, useStatus } from "../../api/client";
import { groupDigits } from "../../format";
import { visible } from "../../text";
import { IconButton } from "../ui/IconButton";

const SIDES = ["Left", "Top", "Right", "Bottom"] as const;

/** A fraction of the page as the percent shown (one decimal at most), and back. */
const toPercent = (f: number) => String(Math.round(f * 1000) / 10);
const fromPercent = (text: string) => Number.parseFloat(text.replace(",", ".")) / 100;

/** One person as edited: the match texts are one per line. */
type Row = { name: string; match: string };
const toRows = (people: Person[]): Row[] => people.map((p) => ({ name: p.name, match: p.match.join("\n") }));
const toPeople = (rows: Row[]): Person[] =>
  rows.map((r) => ({ name: r.name.trim(), match: r.match.split("\n").map((m) => m.trim()).filter(Boolean) }));

function People() {
  const ids = useId();
  const people = usePeople();
  const save = useSavePeople();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [zone, setZone] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  // what the form starts from: the saved list, once it has loaded
  useEffect(() => {
    if (!people.data || rows !== null) return;
    setRows(toRows(people.data.people));
    setZone(people.data.address_zone.map(toPercent));
  }, [people.data, rows]);

  if (people.isError) return <p className="error" role="alert">{visible(errorText(people.error))}</p>;
  if (!people.data || rows === null || zone === null) return <p className="hint">Loading…</p>;
  const edit = (i: number, change: Partial<Row>) => {
    setSaved(false);
    setRows((all) => (all ?? []).map((r, at) => (at === i ? { ...r, ...change } : r)));
  };
  const editZone = (i: number, value: string) => {
    setSaved(false);
    setZone((all) => (all ?? []).map((z, at) => (at === i ? value : z)));
  };
  const submit = async () => {
    setError(null);
    setSaved(false);
    const numbers = zone.map(fromPercent);
    if (numbers.some((n) => !Number.isFinite(n))) {
      setError("The address area needs four numbers.");
      return;
    }
    try {
      await save.mutateAsync({ people: toPeople(rows), address_zone: numbers as PageBox });
      setSaved(true);
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <section className="people-settings" aria-label="People">
      <h4>People</h4>
      <p className="hint">
        A letter is for the person whose name is found in the address area of page 1. Use {"{person}"} in a rule’s folder or
        name to file by it.
      </p>
      <p className="hint">
        Each line is looked for anywhere in the address area, ignoring case and accents, so a short line finds more than
        you may want: “Anna” is also found in “Hanna” and “Johanna Laine”. Write names the way senders write them, for
        example “Anna Virtanen”, “Anna Maria Virtanen” and “Virtanen Anna” (some put the surname first). A letter where
        two people are found is for nobody.
      </p>
      <ul className="people-list">
        {rows.map((r, i) => (
          <li key={i} className="people-row">
            <div className="field">
              <label htmlFor={`${ids}-name-${i}`}>Name</label>
              <input id={`${ids}-name-${i}`} value={r.name} onChange={(e) => edit(i, { name: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor={`${ids}-match-${i}`}>Found in the address area as (one per line)</label>
              <textarea
                id={`${ids}-match-${i}`}
                rows={2}
                placeholder={"Anna Virtanen\nVirtanen Anna"}
                value={r.match}
                onChange={(e) => edit(i, { match: e.target.value })}
              />
            </div>
            <IconButton
              icon={<Trash2 />}
              label={`Remove ${r.name.trim() || "this person"}`}
              onClick={() => {
                setSaved(false);
                setRows(rows.filter((_, at) => at !== i));
              }}
            />
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() => {
          setSaved(false);
          setRows([...rows, { name: "", match: "" }]);
        }}
      >
        <Plus size={14} aria-hidden="true" /> Add a person
      </button>
      <div className="field address-zone" role="group" aria-label="Address area">
        <span className="field-label">Address area (percent of page 1)</span>
        <div className="address-zone-row">
          {SIDES.map((side, i) => (
            <label key={side}>
              {side}
              <input
                type="number"
                min={0}
                max={100}
                step={0.5}
                value={zone[i]}
                onChange={(e) => editZone(i, e.target.value)}
              />
            </label>
          ))}
          <button
            type="button"
            onClick={() => {
              setSaved(false);
              setZone(people.data.default_address_zone.map(toPercent));
            }}
          >
            Reset to default
          </button>
        </div>
        <p className="hint">Draw it on a letter with Draw a box → Address area for all letters.</p>
      </div>
      {error && <p className="error" role="alert">{visible(error)}</p>}
      <div className="actions">
        <button type="button" className="primary" disabled={save.isPending} onClick={() => void submit()}>
          Save people and address area
        </button>
        {saved && <span className="hint" role="status">Saved.</span>}
      </div>
    </section>
  );
}

/** "Page 1 read for 1 240 of 2 015 documents" and the switch for the background reading. */
function Page1Progress() {
  const { data } = useStatus();
  const backfill = usePage1Backfill();
  const page1 = data?.page1;
  if (!page1) return null;
  return (
    <div className="page1-progress">
      <p>
        Page 1 read for {groupDigits(page1.read)} of {groupDigits(page1.total)} documents
      </p>
      <label className="check">
        <input
          type="checkbox"
          checked={page1.backfill}
          disabled={backfill.isPending}
          onChange={(e) => backfill.mutate(e.target.checked)}
        />
        Read page 1 of older documents in the background
      </label>
      {backfill.isError && <p className="error" role="alert">{visible(errorText(backfill.error))}</p>}
    </div>
  );
}

export function PeopleSettings() {
  return (
    <>
      <Page1Progress />
      <People />
    </>
  );
}
