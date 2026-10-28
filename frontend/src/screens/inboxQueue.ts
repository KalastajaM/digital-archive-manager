/** What the New look's inbox queue says about a file: its title, the status pill under it,
 * which rule suggested the filing, and the All / Bills / New filter. Everything is read
 * from the inbox list's own data (the suggestion and the scan's fields); nothing is asked
 * of the server. */
import type { InboxEntry } from "../api/client";
import { formatMoney, plural, shortCalendarDate } from "../format";

export type Filter = "all" | "bills" | "new";

export type Pill = { text: string; tone: "red" | "orange" | "grey" };

const DAY_MS = 86_400_000;
const utcDay = (iso: string) => Date.parse(`${iso}T00:00:00Z`);

/** The id in a source tag ("rule:water-2024", "rule:x (template error)"), else null. */
export function ruleIdOf(source: string | null | undefined): string | null {
  if (!source?.startsWith("rule:")) return null;
  const id = source.slice("rule:".length).replace(/ \(.*\)$/, "");
  return id || null;
}

/** The rule the filing suggestion comes from: the one that gave the folder, else the name,
 * the tray, a tag, a collection, else the first rule that matched. Null when no rule did. */
export function suggestingRule(s: InboxEntry["suggestion"]): string | null {
  const from = [
    s.folder_source,
    s.name_source,
    s.tray_source,
    ...Object.values(s.tag_sources),
    ...Object.values(s.collection_sources),
    ...s.sources,
  ];
  for (const source of from) {
    const id = ruleIdOf(source);
    if (id) return id;
  }
  return null;
}

/** A bill by what the scan read: it found a due date or an amount. */
export const isBill = (e: InboxEntry) => Boolean(e.prefill.due_date || e.prefill.total);

/** New: no rule suggests anything for it yet (dam has not seen this kind of document). */
export const isNewKind = (e: InboxEntry) => suggestingRule(e.suggestion) === null;

export function matches(e: InboxEntry, filter: Filter): boolean {
  return filter === "all" || (filter === "bills" ? isBill(e) : isNewKind(e));
}

export function counts(entries: InboxEntry[]): Record<Filter, number> {
  return {
    all: entries.length,
    bills: entries.filter(isBill).length,
    new: entries.filter(isNewKind).length,
  };
}

/** The name as a title: the suggested name without its extension and date prefix when it
 * differs from the file's own name, else the file's name. */
export function titleOf(e: InboxEntry): string {
  const name = e.record.name ?? e.record.path;
  const suggested = e.suggestion.name;
  if (!suggested || suggested === name) return name;
  const bare = suggested.replace(/\.[A-Za-z0-9]{1,5}$/, "").replace(/^\d{8}[ _-]*/, "");
  return bare || name;
}

const SCANNED = new Set(["pdf", "png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "tif", "tiff"]);

/** The status pill: overdue (red), due (orange), an amount (grey), the rule, or that nothing
 * was recognised (a scannable file with no suggestion at all). */
export function pillOf(e: InboxEntry, today: string): Pill | null {
  const due = e.prefill.due_date;
  const total = e.prefill.total;
  const amount = total ? formatMoney(total) : "";
  if (due) {
    const days = Math.round((utcDay(due) - utcDay(today)) / DAY_MS);
    const head = days < 0 ? `Overdue ${plural(-days, "day")}` : `Due ${shortCalendarDate(due, today)}`;
    return { text: amount ? `${head} · ${amount}` : head, tone: days < 0 ? "red" : "orange" };
  }
  if (amount) return { text: amount, tone: "grey" };
  const rule = suggestingRule(e.suggestion);
  if (rule) return { text: `Rule: ${rule}`, tone: "grey" };
  if (e.suggestion.waiting_for_page1) return { text: "Reading page 1…", tone: "grey" };
  if (!e.suggestion.folder && SCANNED.has((e.record.ext ?? "").toLowerCase())) return { text: "Not recognised", tone: "grey" };
  return null;
}
