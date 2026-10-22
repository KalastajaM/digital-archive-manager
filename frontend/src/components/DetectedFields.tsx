import { Pencil, X } from "lucide-react";
import { type KeyboardEvent, useId, useState } from "react";
import {
  errorText,
  type InboxEntry,
  type ScanField,
  usePutFileFields,
  useResetFileFields,
} from "../api/client";
import {
  SCAN_KINDS,
  type ScanKind,
  SINGLE_KINDS,
  scanFieldLabel,
  scanFieldValue,
  scanKindType,
} from "../format";
import { visible } from "../text";
import { IconButton } from "./ui/IconButton";

/** A scan source (what the rules engine calls it) in plain words. Unknown sources, such
 * as ones added later, are shown with their punctuation turned into spaces. */
export function sourceWord(source: string): string {
  const s = source.trim();
  const known: Record<string, string> = {
    mtime: "file date",
    "text-date": "date in the text",
    "filename-date": "file name",
    barcode: "barcode",
    scan: "scan",
    "similar files": "similar files",
    similar: "similar files",
    "similar-files": "similar files",
    learned: "similar files",
  };
  if (s in known) return known[s];
  if (s.startsWith("rule:")) {
    const rest = s.slice(5).trim();
    return rest ? `rule ${rest}` : "rule";
  }
  return s.replace(/[-_:]+/g, " ");
}

/** The sources as one line, each word once. */
export function sourcesLine(sources: string[]): string {
  return [...new Set(sources.map(sourceWord))].join(", ");
}

/** The rows' labels: several "Amount" rows are told apart ("Other amount" beside a
 * Total, else numbered). */
export function rowLabels(fields: ScanField[]): string[] {
  const amounts = fields.filter((f) => f.kind === "amount").length;
  const hasTotal = fields.some((f) => f.kind === "total");
  let n = 0;
  return fields.map((f) => {
    if (f.kind !== "amount" || (amounts < 2 && !hasTotal)) return scanFieldLabel(f);
    n++;
    const base = hasTotal ? "Other amount" : "Amount";
    return amounts > 1 ? `${base} ${n}` : base;
  });
}

/** What an editor is changing: the field at an index, or a new one. */
type Editing = number | "new";

/** Enter (in an input) saves, Escape cancels. Escape stops here: the inbox's own Escape (leave the
 * field) would otherwise run on the same key press. */
function editorKeys(save: () => void, cancel: () => void) {
  return (e: KeyboardEvent) => {
    if (e.key === "Enter") {
      if (e.target instanceof HTMLButtonElement) return; // Save and Cancel keep their own Enter
      e.preventDefault();
      save();
    } else if (e.key === "Escape") {
      e.stopPropagation();
      cancel();
    }
  };
}

/** The value input of a kind: a date picker for dates, a decimal keypad for amounts. */
function ValueInput({
  kind,
  value,
  label,
  onChange,
  autoFocus,
}: {
  kind: ScanKind;
  value: string;
  label: string;
  onChange: (value: string) => void;
  autoFocus?: boolean;
}) {
  const type = scanKindType(kind);
  return (
    <input
      type={type === "date" ? "date" : "text"}
      inputMode={type === "money" ? "decimal" : undefined}
      aria-label={label}
      value={value}
      spellCheck={false}
      autoFocus={autoFocus}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** Edit a field's value (and an "Other" field's label), or add a field. */
function FieldEditor({
  initial,
  taken,
  busy,
  onSave,
  onCancel,
}: {
  /** The field being edited; none when adding. */
  initial?: ScanField;
  /** Single-valued kinds the file already has (not offered when adding). */
  taken: ScanKind[];
  busy: boolean;
  onSave: (field: ScanField) => void;
  onCancel: () => void;
}) {
  const adding = initial === undefined;
  const firstFree = SCAN_KINDS.find(([k]) => !taken.includes(k))?.[0] ?? "custom";
  const [kind, setKind] = useState<ScanKind>(initial?.kind ?? firstFree);
  const [label, setLabel] = useState(initial?.label ?? "");
  const [value, setValue] = useState(initial?.value ?? "");
  const name = initial ? scanFieldLabel(initial) : "new field";
  const save = () => {
    if (!busy) onSave({ kind, label: kind === "custom" ? label : null, value });
  };
  const keys = editorKeys(save, onCancel);
  return (
    <div className="detected-editor" role="group" aria-label={adding ? "Add field" : `Edit ${name}`} onKeyDown={keys}>
      {adding && (
        <select
          aria-label="Kind"
          value={kind}
          autoFocus
          onChange={(e) => {
            setKind(e.target.value as ScanKind);
            setValue("");
          }}
        >
          {SCAN_KINDS.map(([k, text]) => (
            <option key={k} value={k} disabled={taken.includes(k)}>
              {text}
            </option>
          ))}
        </select>
      )}
      {kind === "custom" && (
        <input aria-label="Label" value={label} placeholder="Label" maxLength={60} onChange={(e) => setLabel(e.target.value)} />
      )}
      <ValueInput kind={kind} value={value} label={`Value of ${name}`} onChange={setValue} autoFocus={!adding} />
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
      <button type="button" className="primary" onClick={save} disabled={busy}>
        Save
      </button>
    </div>
  );
}

/** The scan's fields on the review card, editable: remove one (×), change its value
 * (pencil) or add one. Every change saves the file's whole list (it then replaces the
 * detected one everywhere the scan values are used); "Reset to detected" forgets it. */
export function DetectedFields({ entry }: { entry: InboxEntry }) {
  const headingId = useId();
  const driveId = entry.record.drive_id;
  const put = usePutFileFields();
  const reset = useResetFileFields();
  const [editing, setEditing] = useState<Editing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = put.isPending || reset.isPending;
  const fields = entry.fields;
  const taken = SINGLE_KINDS.filter((k) => fields.some((f) => f.kind === k));

  const save = (next: ScanField[]) => {
    setError(null);
    put.mutate(
      { driveId, fields: next },
      { onSuccess: () => setEditing(null), onError: (e) => setError(errorText(e)) },
    );
  };
  const resetToDetected = () => {
    setError(null);
    reset.mutate(driveId, {
      onSuccess: () => setEditing(null),
      onError: (e) => setError(errorText(e)),
    });
  };
  const open = (which: Editing) => {
    setError(null);
    setEditing(which);
  };
  const close = () => {
    setError(null);
    setEditing(null);
  };

  const sources = entry.suggestion.sources;
  const labels = rowLabels(fields);
  // The likeliest first: a Total before the other amounts (stable otherwise).
  const order = fields.map((_, i) => i).sort((a, b) => Number(fields[a].kind === "amount") - Number(fields[b].kind === "amount") || a - b);

  return (
    <section className="detected" aria-labelledby={headingId}>
      <h3 id={headingId}>Detected fields</h3>
      {fields.length === 0 && editing !== "new" && <p>Nothing detected.</p>}
      {fields.length > 0 && (
        <ul className="detected-rows">
          {order.map((i) => {
            const f = fields[i];
            const label = labels[i];
            const shown = `${label} ${scanFieldValue(f)}`;
            return (
              <li key={i}>
                {editing === i ? (
                  <FieldEditor
                    initial={f}
                    taken={taken}
                    busy={busy}
                    onSave={(changed) => save(fields.map((old, j) => (j === i ? changed : old)))}
                    onCancel={close}
                  />
                ) : (
                  <>
                    <span className="detected-label">{visible(label)}</span>
                    <span className="detected-value">{visible(scanFieldValue(f))}</span>
                    <IconButton
                      className="detected-action"
                      icon={<Pencil size={14} />}
                      label={`Edit ${label}`}
                      onClick={() => open(i)}
                      disabled={busy}
                    />
                    <IconButton
                      className="detected-action"
                      icon={<X size={14} />}
                      label={`Remove ${shown}`}
                      onClick={() => save(fields.filter((_, j) => j !== i))}
                      disabled={busy}
                    />
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {sources.length > 0 && (
        <dl className="detected-sources">
          <div>
            <dt>Sources</dt>
            <dd>{sourcesLine(sources)}</dd>
          </div>
        </dl>
      )}
      {editing === "new" && (
        <FieldEditor taken={taken} busy={busy} onSave={(added) => save([...fields, added])} onCancel={close} />
      )}
      <div className="detected-footer">
        {editing !== "new" && (
          <button type="button" onClick={() => open("new")} disabled={busy}>
            Add field
          </button>
        )}
        {entry.fields_edited && (
          <button type="button" onClick={resetToDetected} disabled={busy}>
            Reset to detected
          </button>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </section>
  );
}
