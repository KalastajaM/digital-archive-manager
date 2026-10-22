/** One tray field as an input, by its type: a checkbox, a date input or a text input
 * (money with the decimal keypad). Shared by the filing form, the done form and the
 * item detail, so a field looks and behaves the same everywhere. */
import type { InputHTMLAttributes } from "react";
import type { FieldDef } from "../api/client";
import { copyText, groupIban } from "../format";

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
  return (
    <input
      {...rest}
      id={id}
      type={def.type === "date" ? "date" : "text"}
      inputMode={def.type === "money" ? "decimal" : undefined}
      spellCheck={false}
      value={typeof value === "string" ? value : ""}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
