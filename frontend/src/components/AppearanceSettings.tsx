/** Settings → Appearance: Light, Dark, or Auto to follow the system. It applies at once,
 * to every archive, in this browser (see ``appearance.ts``). */
import { type Appearance, type Look, useAppearance, useStyle } from "../appearance";
import { Segmented } from "./ui/Segmented";

const OPTIONS: { value: Appearance; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "auto", label: "Auto" },
];

const LOOKS: { value: Look; label: string; hint: string }[] = [
  { value: "classic", label: "Classic", hint: "The look you know. Here until the new look has everything." },
  { value: "new", label: "New", hint: "Calmer, with figures and file names in a fixed-width font." },
];

function LookChoice() {
  const [look, setLook] = useStyle();
  return (
    <fieldset className="look-choice">
      <legend>Look</legend>
      <div className="look-cards">
        {LOOKS.map((o) => (
          <label key={o.value} className="look-card" data-look={o.value} data-checked={o.value === look ? "" : undefined}>
            <span className="look-preview" aria-hidden="true">
              <span className="look-preview-side" />
              <span className="look-preview-main">
                <span className="look-preview-title" />
                <span className="look-preview-card" />
                <span className="look-preview-bar" />
              </span>
            </span>
            <span className="look-card-text">
              <input type="radio" name="look" value={o.value} checked={o.value === look} onChange={() => setLook(o.value)} />
              <span className="look-card-name">{o.label}</span>
              <span className="look-card-hint hint">{o.hint}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function AppearanceSettings() {
  const [choice, setChoice] = useAppearance();
  return (
    <section aria-label="Appearance">
      <h3>Appearance</h3>
      <LookChoice />
      <h4>Theme</h4>
      <p className="hint">Auto follows your system setting. This applies to every archive, in this browser.</p>
      <Segmented options={OPTIONS} value={choice} onChange={setChoice} ariaLabel="Appearance" />
    </section>
  );
}
