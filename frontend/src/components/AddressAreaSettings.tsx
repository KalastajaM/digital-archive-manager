/** Settings → Reading documents: where the address sits on page 1 of a letter, which is
 * where dam looks for the person a letter is for. It follows the countries until the owner
 * sets one; "Reset to default" takes the owner's out of the settings again. One document
 * can have its own (Draw a box on that document). */
import { useState } from "react";
import { errorText, type PageBox, usePeople, useSavePeople } from "../api/client";
import { visible } from "../text";
import { SampleLetterArea } from "./zones/SampleLetterArea";

const SIDES = ["Left", "Top", "Right", "Bottom"] as const;

/** A fraction of the page as the percent shown (one decimal at most), and back. */
const toPercent = (f: number) => String(Math.round(f * 1000) / 10);
const fromPercent = (text: string) => Number.parseFloat(text.replace(",", ".")) / 100;

/** What the owner changed: the four sides, or back to the countries' area. */
type Draft = { zone: string[]; followsCountries: boolean };

export function AddressAreaSettings() {
  const people = usePeople();
  const save = useSavePeople();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  if (people.isError)
    return (
      <p className="error" role="alert">
        {visible(errorText(people.error))}
      </p>
    );
  if (!people.data) return <p className="hint">Loading…</p>;
  const data = people.data;
  // nothing changed: what is saved, which follows the countries when the owner set none
  const shown: Draft = draft ?? {
    zone: data.address_zone.map(toPercent),
    followsCountries: !data.address_zone_set,
  };
  const edit = (i: number, value: string) => {
    setSaved(false);
    setDraft({
      zone: shown.zone.map((z, at) => (at === i ? value : z)),
      followsCountries: false,
    });
  };
  const submit = async () => {
    setError(null);
    setSaved(false);
    const numbers = shown.zone.map(fromPercent);
    if (!shown.followsCountries && numbers.some((n) => !Number.isFinite(n))) {
      setError("The address area needs four numbers.");
      return;
    }
    try {
      // null takes the owner's area out of the settings: it follows the countries again
      await save.mutateAsync({
        people: data.people,
        address_zone: shown.followsCountries ? null : (numbers as PageBox),
      });
      setDraft(null);
      setSaved(true);
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <section className="address-area-settings" aria-label="Address area">
      <h4>Address area</h4>
      <p className="hint">
        Where the address sits on page 1 of a letter. dam looks for the person a letter is for there (Filing rules,
        People).
      </p>
      <div className="field address-zone" role="group" aria-label="Address area">
        <span className="field-label">Percent of page 1</span>
        <div className="address-zone-row">
          {SIDES.map((side, i) => (
            <label key={side}>
              {side}
              <input
                type="number"
                min={0}
                max={100}
                step={0.5}
                value={shown.zone[i]}
                onChange={(e) => edit(i, e.target.value)}
              />
            </label>
          ))}
          <button
            type="button"
            onClick={() => {
              setSaved(false);
              setDraft({
                zone: data.default_address_zone.map(toPercent),
                followsCountries: true,
              });
            }}
          >
            Reset to default
          </button>
        </div>
        <p className="hint">
          {shown.followsCountries ? "Follows the countries above." : "Set by you."} To set it from a letter, open the
          letter and use Draw a box: a box can be the address area for all letters or for that letter only.
        </p>
      </div>
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={draft === null || save.isPending}
          onClick={() => void submit()}
        >
          Save address area
        </button>
        {saved && (
          <span className="hint" role="status">
            Saved.
          </span>
        )}
      </div>
      <SampleLetterArea
        onSaved={() => {
          // the fields show what was saved from the letter
          setDraft(null);
          setSaved(false);
        }}
      />
    </section>
  );
}
