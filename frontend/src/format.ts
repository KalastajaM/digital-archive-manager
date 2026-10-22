/** Display and copy forms of API values (the API sends money as "84.20", dates as
 * "YYYY-MM-DD", IBANs compact). Formatting only: no values are computed here. */

const MONEY = /^(-?)(\d+)\.(\d{2})$/;

/** "1234.50" → "1 234,50" (narrow no-break spaces group thousands); other text as is. */
function moneyDigits(value: string, group: boolean): string {
  const m = MONEY.exec(value);
  if (!m) return value;
  const whole = group ? m[2].replace(/\B(?=(\d{3})+$)/g, " ") : m[2];
  return `${m[1]}${whole},${m[3]}`;
}

/** "84.20" → "84,20 €". */
export const formatMoney = (value: string) => `${moneyDigits(value, true)} €`;

/** "FI2112345600000785" → "FI21 1234 5600 0007 85". */
export const groupIban = (value: string) => value.replace(/\s+/g, "").replace(/(.{4})(?=.)/g, "$1 ");

/** "2026-10-15" → "15.10.2026"; anything else as is. */
export function formatDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  return m ? `${Number(m[3])}.${Number(m[2])}.${m[1]}` : iso;
}

/** The local calendar date as "YYYY-MM-DD". */
export function localToday(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** What a copy button puts on the clipboard: IBANs compact, amounts as "84,20", dates
 * as "15.10.2026" (as a web bank's form takes them). */
export function copyText(type: string | undefined, value: string): string {
  if (type === "iban") return value.replace(/\s+/g, "");
  if (type === "money") return moneyDigits(value, false);
  if (type === "date") return formatDate(value);
  return value;
}

/** A field value as shown on a row, by its tray field type. */
export function formatField(type: string | undefined, value: unknown): string {
  if (typeof value === "boolean") return value ? "yes" : "no";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  if (type === "money") return formatMoney(text);
  if (type === "iban") return groupIban(text);
  if (type === "date") return formatDate(text);
  return text;
}

/** A field name inside a sentence: "paid_on" → "paid on"; "iban" → "IBAN". */
export const fieldWord = (name: string) => (name === "iban" ? "IBAN" : name.replace(/_/g, " "));

/** A field's label, in Mac sentence case: "paid_on" → "Paid on"; "iban" → "IBAN". */
export function fieldLabel(name: string): string {
  const word = fieldWord(name);
  return word.charAt(0).toUpperCase() + word.slice(1);
}

/** The kinds of a file's scan fields, in the order the "Add field" choice lists them. */
export const SCAN_KINDS = [
  ["doc_date", "Document date"],
  ["due_date", "Due date"],
  ["date", "Date"],
  ["total", "Total"],
  ["amount", "Amount"],
  ["iban", "IBAN"],
  ["reference", "Reference"],
  ["payee", "Payee"],
  ["custom", "Other…"],
] as const;

export type ScanKind = (typeof SCAN_KINDS)[number][0];

/** Kinds a file has at most one field of. */
export const SINGLE_KINDS: readonly ScanKind[] = ["doc_date", "due_date", "total", "iban", "reference", "payee"];

/** The kind's input: dates take a date input, money a decimal one. */
export const scanKindType = (kind: ScanKind) =>
  kind.endsWith("date") ? "date" : kind === "total" || kind === "amount" ? "money" : kind === "iban" ? "iban" : "text";

/** A scan field's label: its kind's name, or the label of an "Other" field. */
export function scanFieldLabel(field: { kind: ScanKind; label: string | null }): string {
  if (field.kind === "custom") return field.label ?? "Other";
  return SCAN_KINDS.find(([kind]) => kind === field.kind)?.[1] ?? field.kind;
}

/** A scan field's value as shown (dates, amounts and IBANs formatted). */
export const scanFieldValue = (field: { kind: ScanKind; value: string }) =>
  formatField(scanKindType(field.kind), field.value);

const UNITS = ["KB", "MB", "GB", "TB"];

/** A byte count as "640 bytes", "1,5 MB", "312 MB" (1 MB = 1024 × 1024 bytes, as the
 * API's size limits are). */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  let value = bytes / 1024;
  let unit = 0;
  // Step up while the shown number would reach 1024 (never "1024 KB").
  while (Math.round(value) >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit++;
  }
  // One decimal below 10 (as it would be shown: 9.96 → "10", not "10,0").
  const shown = value < 9.95 ? value.toFixed(1).replace(".", ",") : String(Math.round(value));
  return `${shown} ${UNITS[unit]}`;
}

/** 1240 → "1 240" (narrow no-break spaces group thousands, as amounts do). */
export const groupDigits = (n: number) => String(n).replace(/\B(?=(\d{3})+$)/g, " ");

/** "1 file", "3 files". */
export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** A timestamp (seconds) as the local "YYYY-MM-DD" that RelativeDate shows. */
export const dayOf = (seconds: number) => localToday(new Date(seconds * 1000));

const SHORT_DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const SHORT_DATE_YEAR = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** A timestamp (seconds) as "15 Oct" this year, "15 Oct 2025" otherwise (list rows). */
export function shortDate(seconds: number, now = new Date()): string {
  const date = new Date(seconds * 1000);
  return (date.getFullYear() === now.getFullYear() ? SHORT_DATE : SHORT_DATE_YEAR).format(date);
}
