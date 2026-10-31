/** Settings → Appearance: Light, Dark, or Auto to follow the system. It applies at once,
 * to every archive, in this browser (see ``appearance.ts``). */
import { useState } from "react";
import { type Appearance, useAppearance } from "../appearance";
import { forgetLayout, restoreLayout } from "../layoutMemory";
import { ManageArchives } from "./ManageArchives";
import { undoAction, useToast } from "./Toasts";

const OPTIONS: { value: Appearance; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "auto", label: "Auto" },
];

/** Forgets the dragged pane widths and the Today order; says so, with Undo. */
function useResetLayout() {
  const toast = useToast();
  return () => {
    const removed = forgetLayout();
    toast({
      kind: "info",
      text: Object.keys(removed).length > 0 ? "Layout reset: the panes and Today are back to their default arrangement." : "Nothing to reset: the layout is already the default.",
      action: Object.keys(removed).length > 0 ? undoAction(() => restoreLayout(removed)) : undefined,
    });
  };
}

/** The theme as a radio group (Light, Dark, Auto). */
function ThemeRadios() {
  const [choice, setChoice] = useAppearance();
  return (
    <div role="radiogroup" aria-label="Appearance" className="theme-radios">
      {OPTIONS.map((o) => (
        <label key={o.value} data-checked={o.value === choice ? "" : undefined}>
          <input type="radio" name="theme" value={o.value} checked={o.value === choice} onChange={() => setChoice(o.value)} />
          {o.label}
        </label>
      ))}
    </div>
  );
}

/** Theme, Layout and the note on the archive colour. */
function AppearanceGroups() {
  const reset = useResetLayout();
  const [managing, setManaging] = useState(false);
  return (
    <>
      <fieldset className="appearance-group">
        <legend>Theme</legend>
        <ThemeRadios />
        <p className="hint">Auto follows your computer&apos;s setting.</p>
      </fieldset>
      <fieldset className="appearance-group">
        <legend>Layout</legend>
        <div className="appearance-row">
          <p>Pane widths you drag and the order of the sections on Today are remembered in this browser, per screen.</p>
          <button type="button" onClick={reset}>
            Reset layout
          </button>
        </div>
      </fieldset>
      <fieldset className="appearance-group">
        <legend>Archive colour</legend>
        <p>
          Every archive except Main gets a coloured band along the top of the window, so a test archive is never mistaken for the real one. Set
          it per archive under{" "}
          <button type="button" className="link-button" onClick={() => setManaging(true)}>
            Manage archives
          </button>
          .
        </p>
      </fieldset>
      <ManageArchives open={managing} onClose={() => setManaging(false)} />
    </>
  );
}

export function AppearanceSettings() {
  return (
    <section aria-label="Appearance" className="appearance-new">
      <header>
        <h3>Appearance</h3>
        <span className="appearance-sub">Kept in this browser, the same for every archive.</span>
      </header>
      <AppearanceGroups />
    </section>
  );
}
