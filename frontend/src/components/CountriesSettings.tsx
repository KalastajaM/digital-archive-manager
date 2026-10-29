/** Settings → Reading documents: the country packs and language packs this archive's
 * documents are read with (``countries`` and ``languages`` in settings.yaml). English is
 * always on. */
import { useState } from "react";
import { type Countries, errorText, useCountries, useSaveCountries } from "../api/client";
import { visible } from "../text";
import { useToast } from "./Toasts";

type Choice = { countries: string[]; languages: string[] };

const fromServer = (c: Countries): Choice => ({
  countries: c.countries.filter((x) => x.enabled).map((x) => x.code),
  languages: c.languages.filter((x) => x.enabled).map((x) => x.code),
});

const same = (a: Choice, b: Choice) =>
  a.countries.join() === b.countries.join() && a.languages.join() === b.languages.join();

/** ``list`` with ``code`` added at the end or taken out. */
const toggled = (list: string[], code: string, on: boolean) => (on ? [...list, code] : list.filter((x) => x !== code));

export function CountriesSettings() {
  const query = useCountries();
  const save = useSaveCountries();
  const toast = useToast();
  const [draft, setDraft] = useState<Choice | null>(null);
  const saved = query.data ? fromServer(query.data) : null;
  const choice = draft ?? saved;
  const changed = saved !== null && choice !== null && !same(choice, saved);

  const submit = () => {
    if (!choice) return;
    // English last, as the server lists it: always on
    const languages = [...choice.languages.filter((x) => x !== "en"), "en"];
    save.mutate(
      { countries: choice.countries, languages },
      {
        onSuccess: () => {
          setDraft(null);
          toast({ kind: "info", text: "Saved. dam reads your documents with these from now on." });
        },
      },
    );
  };

  return (
    <section aria-label="Reading documents" className="countries-settings">
      <h3>Reading documents</h3>
      <p className="hint">
        dam uses these to find reference numbers, dates, due dates and totals in your documents. Kept in this
        archive's settings.
      </p>
      {query.isError && (
        <p className="error" role="alert">
          Could not load the settings: {visible(errorText(query.error))}
        </p>
      )}
      {query.data && choice && (
        <>
          <fieldset className="countries-group">
            <legend>Where your post comes from</legend>
            {query.data.countries.map((c) => (
              <label key={c.code} className="check countries-row">
                <input
                  type="checkbox"
                  checked={choice.countries.includes(c.code)}
                  onChange={(e) =>
                    setDraft({
                      countries: toggled(choice.countries, c.code, e.target.checked),
                      // a country turned on brings its languages; turned off, they stay
                      languages: e.target.checked
                        ? [...choice.languages, ...c.languages.filter((l) => !choice.languages.includes(l))]
                        : choice.languages,
                    })
                  }
                />
                <span className="countries-text">
                  <span className="countries-name">{c.name}</span>
                  {c.adds.map((line) => (
                    <span key={line} className="hint countries-adds">
                      {line}
                    </span>
                  ))}
                </span>
              </label>
            ))}
            <p className="hint">Without a country, dam still reads RF references, IBANs, dates and amounts.</p>
          </fieldset>
          <fieldset className="countries-group">
            <legend>Languages your documents are written in</legend>
            {query.data.languages.map((l) => (
              <label key={l.code} className="check countries-row">
                <input
                  type="checkbox"
                  checked={l.always || choice.languages.includes(l.code)}
                  disabled={l.always}
                  onChange={(e) => setDraft({ ...choice, languages: toggled(choice.languages, l.code, e.target.checked) })}
                />
                <span className="countries-text">
                  <span className="countries-name">{l.name}</span>
                  {l.always && <span className="hint countries-adds">always on (dam itself is in English)</span>}
                </span>
              </label>
            ))}
          </fieldset>
          {save.isError && (
            <p className="error" role="alert">
              {visible(errorText(save.error))}
            </p>
          )}
          <button type="button" className="primary" disabled={!changed || save.isPending} onClick={submit}>
            Save countries and languages
          </button>
        </>
      )}
    </section>
  );
}
