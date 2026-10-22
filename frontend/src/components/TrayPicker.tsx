/** "Then put it in": a segmented control with one option per tray plus "Nothing (just
 * file)", and the chosen tray's fields with the values found in the scan. */
import { type ReactNode, useId } from "react";
import type { TrayDef } from "../api/client";
import { fieldLabel, fieldWord } from "../format";
import { isShortcut, useKeydown } from "../keyboard";
import { visible } from "../text";
import { editText, FieldInput } from "./FieldInput";
import { Segmented, type SegmentedOption } from "./ui/Segmented";

const NONE = "";

/** Field name → what the form shows (and sends): text, or a checkbox's state. */
export type TrayValues = Record<string, string | boolean>;

/** Every field of ``tray`` blank (checkboxes off), in the tray's field order. */
export function blankValues(tray: TrayDef): TrayValues {
  const out: TrayValues = {};
  for (const [name, def] of Object.entries(tray.fields ?? {})) out[name] = def.type === "checkbox" ? false : "";
  return out;
}

/** The fields of ``tray`` that the scan has a value for (``entry.prefill`` keys). */
export function prefillValues(tray: TrayDef, prefill: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, def] of Object.entries(tray.fields ?? {})) {
    const raw = def.prefill ? prefill[def.prefill] : undefined;
    const shown = raw === undefined ? null : editText(def, raw);
    if (shown !== null) out[name] = shown;
  }
  return out;
}

const blank = (value: string | boolean | undefined) => typeof value === "string" && !value.trim();

type PickerProps = {
  trays: TrayDef[];
  value: string | null;
  onChange: (tray: string | null) => void;
  /** Why the trays are not listed (load error), if so. */
  problem?: string | null;
  /** The ``0``–``9`` keys (off where those keys mean something else, e.g. zoom). */
  shortcuts?: boolean;
  /** The group's label (the filing form says what happens after filing). */
  label?: string;
  /** Offer "Nothing (just file)" (off where a tray must be chosen). */
  showNone?: boolean;
};

/** ``1``–``9`` pick a tray by position, ``0`` picks Nothing (plain key presses only:
 * never while typing or with a dialog open). */
export function TrayPicker({
  trays,
  value,
  onChange,
  problem,
  shortcuts = true,
  label = "Then put it in",
  showNone = true,
}: PickerProps) {
  useKeydown((e) => {
    if (!shortcuts || !isShortcut(e) || !/^[0-9]$/.test(e.key)) return;
    const n = Number(e.key);
    if (n === 0 && !showNone) return;
    const tray = n === 0 ? null : trays[n - 1];
    if (tray === undefined) return;
    e.preventDefault();
    onChange(tray === null ? null : tray.id);
  });
  // The segmented control's values are strings: "" stands for Nothing.
  const options: SegmentedOption<string>[] = trays.map((t, i) => {
    const key = shortcuts && i < 9 ? String(i + 1) : undefined;
    const name = visible(t.name);
    return { value: t.id, label: name, title: key ? `${name} (${key})` : name, shortcut: key };
  });
  if (showNone) {
    options.push({
      value: NONE,
      label: "Nothing",
      ariaLabel: "Nothing (just file)",
      title: shortcuts ? "Nothing: just file it (0)" : "Nothing: just file it",
      shortcut: shortcuts ? "0" : undefined,
    });
  }
  return (
    <div className="field">
      <span className="field-label" aria-hidden="true">
        {label}
      </span>
      {trays.length > 0 || showNone ? (
        <Segmented
          className="tray-segmented"
          ariaLabel={label}
          options={options}
          value={value ?? NONE}
          onChange={(v) => onChange(v === NONE ? null : v)}
        />
      ) : null}
      {problem && <p className="hint">Trays could not be loaded: {visible(problem)}</p>}
    </div>
  );
}

type FieldsProps = {
  tray: TrayDef;
  values: TrayValues;
  /** Fields still showing the scan's value (not edited): labelled "found in scan". */
  found: Set<string>;
  onChange: (name: string, value: string | boolean) => void;
  /** Shown after a field's input, by field name (its suggestion chips). */
  chips?: Record<string, ReactNode>;
};

/** The tray's item fields. A required field left empty does not block filing: the
 * item is created and flagged, which the hint says (so the label does not say
 * "required"). */
export function TrayFields({ tray, values, found, onChange, chips }: FieldsProps) {
  const ids = useId();
  return (
    <div className="tray-fields">
      {Object.entries(tray.fields ?? {}).map(([name, def]) => {
        const id = `${ids}-${name}`;
        const value = values[name];
        const label = visible(fieldLabel(name));
        return (
          <div className="field" key={name}>
            <label htmlFor={id}>{label}</label>
            <FieldInput id={id} def={def} value={value ?? ""} onChange={(v) => onChange(name, v)} />
            {found.has(name) && <span className="hint"> found in scan</span>}
            {chips?.[name]}
            {def.required && blank(value) && (
              <p className="hint">Optional — without it the item is marked “needs a {visible(fieldWord(name))}”</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
