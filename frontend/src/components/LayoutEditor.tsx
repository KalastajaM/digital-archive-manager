/** Choosing and editing the layout of a new archive: a starter layout, numbering, the
 * list of folders (rename, remove, add) and the names of the special folders. Used by the
 * first-run screen and by "Set up folders" inside the running app. It only edits a
 * value; nothing is created until the caller's confirm button. */
import { Plus, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { errorText, type LayoutBody, type LayoutPreview, type LayoutTemplate, type SetupFolder } from "../api/client";
import { plural } from "../format";
import { visible } from "../text";

export type LayoutRow = { id: number; key: string | null; name: string };
export type LayoutState = {
  template: string | null;
  numbered: boolean;
  rows: LayoutRow[];
  /** role -> name */
  special: Record<string, string>;
};

let nextRow = 1;
const rowsOf = (t: LayoutTemplate | undefined): LayoutRow[] =>
  (t?.folders ?? []).map((f) => ({ id: nextRow++, key: f.key, name: f.name }));

/** The starting point: the first layout (Household), numbered, the special names as given. */
export function initialLayout(templates: LayoutTemplate[], specials: SetupFolder[]): LayoutState {
  const first = templates[0];
  return {
    template: first?.id ?? null,
    numbered: true,
    rows: rowsOf(first),
    special: Object.fromEntries(specials.map((f) => [f.role, f.name])),
  };
}

/** What the API takes. ``withSpecial`` only in first-run setup, where the names are still
 * ours to choose; inside the running app they are fixed by the settings. */
export function layoutBody(state: LayoutState, withSpecial: boolean): LayoutBody {
  const body: LayoutBody = {
    template: state.template,
    numbered: state.numbered,
    folders: state.rows.map((r) => ({ key: r.key, name: r.name })),
  };
  if (withSpecial) {
    const s = state.special;
    body.special = { inbox: s.inbox ?? "", ongoing: s.ongoing ?? "", important: s.important ?? "", quarantine: s.quarantine ?? "" };
  }
  return body;
}

type EditorProps = {
  templates: LayoutTemplate[];
  specials: SetupFolder[];
  state: LayoutState;
  onChange: (next: LayoutState) => void;
  /** The special folder names cannot be changed here (the app is already set up). */
  specialLocked?: boolean;
  disabled?: boolean;
};

export function LayoutEditor({ templates, specials, state, onChange, specialLocked = false, disabled = false }: EditorProps) {
  const group = useId();
  const set = (patch: Partial<LayoutState>) => onChange({ ...state, ...patch });
  const choose = (t: LayoutTemplate) => set({ template: t.id, rows: rowsOf(t) });
  const lastAdded = useRef<number | null>(null);
  useEffect(() => {
    if (lastAdded.current === null) return;
    document.getElementById(`${group}-row-${lastAdded.current}`)?.focus();
    lastAdded.current = null;
  }, [state.rows, group]);

  return (
    <div className="layout-editor">
      <fieldset className="layout-templates" disabled={disabled}>
        <legend>Starter layout</legend>
        {templates.map((t) => (
          <label key={t.id} className="layout-template">
            <input type="radio" name={`${group}-template`} checked={state.template === t.id} onChange={() => choose(t)} />
            <span>
              <strong>{t.title}</strong>
              <span className="layout-template-hint">{t.description}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <label className="layout-numbered">
        <input type="checkbox" checked={state.numbered} disabled={disabled} onChange={(e) => set({ numbered: e.target.checked })} />
        <span>
          Number the folders (10. Finance, 11. Bills &amp; Receipts, …)
          <span className="layout-template-hint">Keeps them in this order in every file manager.</span>
        </span>
      </label>

      <h3 className="layout-heading">Your folders</h3>
      <p className="hint">Rename, remove or add folders before they are made. You can always make more later.</p>
      {state.rows.length === 0 ? (
        <p className="hint">No folders yet: only the special folders below will be made.</p>
      ) : (
        <ul className="layout-rows" aria-label="Folders to make">
          {state.rows.map((row, i) => (
            <li key={row.id}>
              {state.numbered && <span className="layout-number" aria-hidden="true">{`${10 + i}.`}</span>}
              <input
                id={`${group}-row-${row.id}`}
                type="text"
                aria-label={`Folder ${i + 1} name`}
                value={row.name}
                spellCheck={false}
                disabled={disabled}
                onChange={(e) => set({ rows: state.rows.map((r) => (r.id === row.id ? { ...r, name: e.target.value } : r)) })}
              />
              <button
                type="button"
                className="icon-button"
                aria-label={`Remove ${visible(row.name) || `folder ${i + 1}`}`}
                title="Remove from the list"
                disabled={disabled}
                onClick={() => set({ rows: state.rows.filter((r) => r.id !== row.id) })}
              >
                <X size={14} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        className="layout-add"
        disabled={disabled}
        onClick={() => {
          const id = nextRow++;
          lastAdded.current = id;
          set({ rows: [...state.rows, { id, key: null, name: "" }] });
        }}
      >
        <Plus size={14} aria-hidden="true" /> Add a folder
      </button>

      <h3 className="layout-heading">Special folders</h3>
      <p className="hint">
        {specialLocked
          ? "dam uses these four folders by name. Their names are set in config/settings.yaml."
          : "dam uses these four folders by name. The defaults work well; rename them if you like."}
      </p>
      <ul className="layout-special" aria-label="Special folders">
        {specials.map((f) => (
          <li key={f.role}>
            <label htmlFor={`${group}-special-${f.role}`}>
              <strong>{f.title}</strong>
              <span className="layout-template-hint">{f.purpose}</span>
            </label>
            <input
              id={`${group}-special-${f.role}`}
              type="text"
              value={state.special[f.role] ?? f.name}
              spellCheck={false}
              disabled={disabled || specialLocked}
              onChange={(e) => set({ special: { ...state.special, [f.role]: e.target.value } })}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Runs ``fetcher`` a moment after ``key`` last changed and keeps the newest answer. */
export function useDebouncedPreview<T>(key: string, fetcher: () => Promise<T>, enabled: boolean) {
  const [state, setState] = useState<{ data: T | null; error: string | null; pending: boolean; key: string }>({
    data: null,
    error: null,
    pending: enabled,
    key: "",
  });
  const latest = useRef(0);
  const run = useRef(fetcher);
  run.current = fetcher;
  useEffect(() => {
    if (!enabled) return;
    const ticket = ++latest.current;
    setState((old) => ({ ...old, pending: true }));
    const timer = setTimeout(() => {
      run
        .current()
        .then((data) => {
          if (ticket === latest.current) setState({ data, error: null, pending: false, key });
        })
        .catch((e: unknown) => {
          if (ticket === latest.current) setState({ data: null, error: errorText(e), pending: false, key });
        });
    }, 300);
    return () => clearTimeout(timer);
  }, [key, enabled]);
  // an answer for an older key is not the answer for this one
  const current = state.key === key;
  return { data: current ? state.data : null, error: current ? state.error : null, pending: !current || state.pending };
}

/** The previewed folders: each one, and which are already there (left as they are). */
export function LayoutPreviewList({ preview }: { preview: LayoutPreview }) {
  return (
    <section className="layout-preview" aria-label="Folders that will be made">
      <p>
        <strong>{preview.to_create === 0 ? "Nothing to make" : `${plural(preview.to_create, "folder")} will be made`}</strong>
        {preview.folders.length > preview.to_create && ` (${preview.folders.length - preview.to_create} already there)`}
      </p>
      <ol className="plan">
        {preview.folders.map((f) => (
          <li key={f.path} className="plan-op">
            <span className="plan-kind">{f.exists ? "Stays" : "New folder"}</span>
            <code>{visible(f.path)}</code>
            {f.exists && <span className="plan-note"> (already there, left as it is)</span>}
          </li>
        ))}
      </ol>
      {preview.to_create > 0 && (
        <p className="hint">
          {preview.rules_seedable
            ? "dam will also save a few example filing rules that point at these folders."
            : "Your own filing rules stay as they are."}{" "}
          You can undo this from Activity: only folders that are still empty are removed.
        </p>
      )}
    </section>
  );
}
