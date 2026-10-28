/** Every open bill, for Pay mode's Previous / Next and the New Today's "To pay" table: the
 * items of each bill tray (a tray with an IBAN field, as the item panel decides), earliest
 * due date first, bills without a date last. */
import { useQueries } from "@tanstack/react-query";
import { type Item, type TrayDef, trayItemsQuery, useTrays } from "../api/client";
import { amountField } from "./today/TrayCard";

export type PayBill = { item: Item; tray: TrayDef };

/** A tray whose items are bills: it has an IBAN field. */
export const isBillTray = (tray: TrayDef | undefined) =>
  Object.values(tray?.fields ?? {}).some((f) => f.type === "iban");

const byDue = (a: PayBill, b: PayBill) => {
  const x = a.item.date;
  const y = b.item.date;
  if (x !== y) {
    if (x === null) return 1;
    if (y === null) return -1;
    return x < y ? -1 : 1;
  }
  return a.item.created - b.item.created || a.item.id - b.item.id;
};

/** Cents in a money value such as "84.20" (null when it is not one). */
function cents(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const m = /^\s*(-?)(\d+)(?:[.,](\d{1,2}))?\s*$/.exec(value);
  if (!m) return null;
  const n = Number(m[2]) * 100 + Number((m[3] ?? "").padEnd(2, "0"));
  return m[1] ? -n : n;
}

/** The sum of the bills' amounts as a "84.20" string, for ``formatMoney``. */
export function sumOfBills(bills: PayBill[]): string {
  const total = bills.reduce((sum, b) => {
    const field = amountField(b.tray);
    return sum + ((field ? cents(b.item.fields[field]) : null) ?? 0);
  }, 0);
  return `${Math.trunc(total / 100)}.${String(Math.abs(total % 100)).padStart(2, "0")}`;
}

export function useOpenBills(): { bills: PayBill[]; loaded: boolean } {
  const trays = useTrays();
  const billTrays = (trays.data?.trays ?? []).filter(isBillTray);
  const lists = useQueries({ queries: billTrays.map((t) => trayItemsQuery(t.id, "open")) });
  const loaded = trays.isSuccess && lists.every((l) => l.isSuccess || l.isError);
  const bills = billTrays
    .flatMap((tray, i) => (lists[i].data ?? []).filter((item) => item.state === "open").map((item) => ({ item, tray })))
    .sort(byDue);
  return { bills, loaded };
}
