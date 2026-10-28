/** What Pay mode and the bill's copy rows show of a bill: which fields, in which order,
 * and their values as text. Shared by the item panel and Pay mode. */
import type { Item, TrayDef } from "../api/client";
import { fieldLabel, fieldWord, formatDate, formatMoney, groupIban } from "../format";
import { amountField } from "./today/TrayCard";

/** One value of the bill, shown large in Pay mode (``copy``: what its Copy button puts
 * on the clipboard, as in the copy rows). */
export type PayFact = { label: string; value: string; copy?: { raw: string; type: string; label: string } };

/** The bill's copy rows: payee, IBAN, reference, amount and due date (the tray's fields
 * of those kinds, in that order); each copies its raw value. */
export function paymentNames(tray: TrayDef): string[] {
  const defs = tray.fields ?? {};
  const byType = (type: string) => Object.keys(defs).find((n) => defs[n].type === type);
  const amount = amountField(tray);
  return [
    "payee" in defs ? "payee" : undefined,
    byType("iban"),
    byType("reference"),
    amount ?? undefined,
    tray.date_field ?? undefined,
  ].filter((n, i, all): n is string => n !== undefined && all.indexOf(n) === i);
}

/** What Pay mode shows next to the large barcode, to check it against the bill: payee,
 * IBAN, reference, amount and due date as text (those with a valid value), in the
 * order of the copy rows. */
export function payFacts(item: Item, tray: TrayDef): PayFact[] {
  const defs = tray.fields ?? {};
  const facts: PayFact[] = [];
  for (const name of paymentNames(tray)) {
    const def = defs[name];
    const value = item.fields[name];
    if (typeof value !== "string" || value === "" || item.invalid_fields.includes(name)) continue;
    let text = value;
    if (def.type === "iban" || (def.type === "reference" && /^RF/i.test(value))) text = groupIban(value);
    else if (def.type === "money") text = formatMoney(value);
    else if (def.type === "date") text = formatDate(value);
    facts.push({ label: fieldLabel(name), value: text, copy: { raw: value, type: def.type, label: fieldWord(name) } });
  }
  return facts;
}
