/** Settings → Appearance: Light, Dark, or Auto to follow the system. It applies at once,
 * to every archive, in this browser (see ``appearance.ts``). */
import { useState } from "react";
import { type Appearance, type Look, useAppearance, useStyle } from "../appearance";
import { forgetLayout, restoreLayout } from "../layoutMemory";
import { ManageArchives } from "./ManageArchives";
import { undoAction, useToast } from "./Toasts";
import { Segmented } from "./ui/Segmented";

const OPTIONS: { value: Appearance; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "auto", label: "Auto" },
];

const LOOKS: { value: Look; label: string; hint: string }[] = [
  { value: "new", label: "New", hint: "Calmer, with figures and file names in a fixed-width font." },
  { value: "classic", label: "Classic", hint: "The earlier look, kept for now. Relatives and Senders are in the New look only." },
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

function LayoutReset() {
  const reset = useResetLayout();
  return (
    <div className="layout-reset">
      <h4>Layout</h4>
      <p className="hint">Pane widths you drag and the order of the cards on Today are remembered in this browser, per screen.</p>
      <button type="button" onClick={reset}>
        Reset layout
      </button>
    </div>
  );
}

/** New: the theme as a radio group (Light, Dark, Auto), the way the board draws it. */
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

/** New: Theme, Layout and the note on the archive colour, as the board arranges them. */
function NewGroups() {
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

/** The one section for both looks, so switching the look in it keeps the Look cards (and
 * the keyboard focus on them) where they are. */
export function AppearanceSettings() {
  const [choice, setChoice] = useAppearance();
  const [look] = useStyle();
  const isNew = look === "new";
  return (
    <section aria-label="Appearance" className={isNew ? "appearance-new" : undefined}>
      {isNew ? (
        <header>
          <h3>Appearance</h3>
          <span className="appearance-sub">Kept in this browser, the same for every archive.</span>
        </header>
      ) : (
        <h3>Appearance</h3>
      )}
      <LookChoice />
      {isNew ? (
        <NewGroups />
      ) : (
        <>
          <h4>Theme</h4>
          <p className="hint">Auto follows your system setting. This applies to every archive, in this browser.</p>
          <Segmented options={OPTIONS} value={choice} onChange={setChoice} ariaLabel="Appearance" />
          <LayoutReset />
        </>
      )}
    </section>
  );
}
