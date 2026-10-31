/** One tray field as an input, by its type: a checkbox, a date input, a choice from the
 * field's options or a text input (money with the decimal keypad, days with the numeric
 * one). Shared by the filing form, the done form and the item detail, so a field looks
 * and behaves the same everywhere. */
import type { InputHTMLAttributes, SelectHTMLAttributes } from "react";
import type { FieldDef } from "../api/client";
import { copyText, groupIban } from "../format";
import { visible } from "../text";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** An API value as the field's input shows it ("84.20" → "84,20", IBANs grouped);
 * null if the input cannot show it as it is (a date input shows nothing for a value
 * that is not YYYY-MM-DD, a checkbox has no text). */
export function editText(def: FieldDef, raw: string): string | null {
  if (def.type === "date") return ISO_DATE.test(raw) ? raw : null;
  if (def.type === "money") return copyText("money", raw);
  if (def.type === "iban") return groupIban(raw);
  if (def.type === "checkbox") return null;
  return raw;
}

type Extra = Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "type" | "value" | "checked" | "onChange">;

type Props = {
  id: string;
  def: FieldDef;
  value: string | boolean;
  onChange: (value: string | boolean) => void;
} & Extra;

export function FieldInput({ id, def, value, onChange, ...rest }: Props) {
  if (def.type === "checkbox") {
    return (
      <input
        {...rest}
        id={id}
        type="checkbox"
        checked={value === true}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  }
  if (def.type === "choice") {
    const text = typeof value === "string" ? value : "";
    const options = def.options ?? [];
    // a stored value the options no longer list stays shown until another is chosen
    const shown = text !== "" && !options.includes(text) ? [...options, text] : options;
    return (
      <select
        {...(rest as SelectHTMLAttributes<HTMLSelectElement>)}
        id={id}
        title={text || undefined}
        value={text}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="" />
        {shown.map((o) => (
          <option key={o} value={o}>
            {visible(o)}
          </option>
        ))}
      </select>
    );
  }
  return (
    <input
      {...rest}
      id={id}
      type={def.type === "date" ? "date" : "text"}
      inputMode={def.type === "money" ? "decimal" : def.type === "days" ? "numeric" : undefined}
      spellCheck={false}
      value={typeof value === "string" ? value : ""}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
