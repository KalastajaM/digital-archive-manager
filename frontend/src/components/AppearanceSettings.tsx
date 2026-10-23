/** Settings → Appearance: Light, Dark, or Auto to follow the system. It applies at once,
 * to every archive, in this browser (see ``appearance.ts``). */
import { type Appearance, useAppearance } from "../appearance";
import { Segmented } from "./ui/Segmented";

const OPTIONS: { value: Appearance; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "auto", label: "Auto" },
];

export function AppearanceSettings() {
  const [choice, setChoice] = useAppearance();
  return (
    <section aria-label="Appearance">
      <h3>Appearance</h3>
      <p className="hint">Auto follows your system setting. This applies to every archive, in this browser.</p>
      <Segmented options={OPTIONS} value={choice} onChange={setChoice} ariaLabel="Appearance" />
    </section>
  );
}
