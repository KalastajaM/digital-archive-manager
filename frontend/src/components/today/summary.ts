/** The New look's Today, in numbers: the headline sentence and the four stat tiles, worked
 * out from what Today and the bill list already load (no new data). */
import type { Today as TodayData } from "../../api/client";
import { formatMoney, plural, shortCalendarDate } from "../../format";
import { visible } from "../../text";
import { urgency } from "../UrgencyTag";
import { type PayBill, sumOfBills } from "../usePayBills";
import { type TrayCardInfo, trayRows } from "./TrayCard";
import { addDays, daysBetween } from "./time";

export const DUE_WINDOW_DAYS = 14;

const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
/** Small counts in words ("seven"), larger ones as figures. */
export const countWord = (n: number) => (n >= 0 && n < WORDS.length ? WORDS[n] : String(n));
const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const counted = (n: number, one: string, many = `${one}s`) => `${countWord(n)} ${n === 1 ? one : many}`;

/** A tray that holds what is waiting on somebody else (Follow up): by its name or its
 * "waiting for" field. */
export const isWaitingTray = (info: TrayCardInfo) =>
  /follow|waiting|odota|seuranta/i.test(`${info.id} ${info.name}`) || "waiting_for" in (info.def?.fields ?? {});

export type Counts = {
  /** Overdue bills (open bills past due, and overdue bills still in the inbox). */
  overdueBills: number;
  /** Overdue items in the other trays. */
  overdueOther: number;
  toFile: number;
  dueSoon: number;
};

/** What the headline counts, from Today's overview (complete, and there at once). */
export function countsOf(data: TodayData, billTrayIds: Set<string>): Counts {
  const trays = data.overview.trays;
  return {
    overdueBills: trays.filter((t) => billTrayIds.has(t.tray_id)).reduce((n, t) => n + t.overdue, 0) + data.inbox_stats.overdue,
    overdueOther: trays.filter((t) => !billTrayIds.has(t.tray_id)).reduce((n, t) => n + t.overdue, 0),
    toFile: data.inbox_stats.count,
    dueSoon: data.attention.filter((a) => a.level === "today" || a.level === "soon").length,
  };
}

/** "One bill is overdue, seven documents to file": the page's headline. */
export function headlineOf(c: Counts): string {
  const clauses: string[] = [];
  const things = [
    c.overdueBills > 0 ? counted(c.overdueBills, "bill") : null,
    c.overdueOther > 0 ? counted(c.overdueOther, "item") : null,
  ].filter((t): t is string => t !== null);
  const overdue = c.overdueBills + c.overdueOther;
  if (overdue > 0) clauses.push(`${things.join(" and ")} ${overdue === 1 ? "is" : "are"} overdue`);
  if (c.toFile > 0) clauses.push(`${counted(c.toFile, "document")} to file`);
  if (clauses.length === 0) return c.dueSoon > 0 ? capital(`${counted(c.dueSoon, "bill")} due soon`) : "All clear";
  if (overdue === 0) clauses.unshift("Nothing is overdue");
  return capital(clauses.join(", "));
}

export type Tile = { id: string; label: string; value: string; note: string; tone: "normal" | "red" | "muted"; to: string };

export function tilesOf(input: {
  data: TodayData;
  bills: PayBill[];
  billsLoaded: boolean;
  /** Every tray on Today, in order. */
  trays: TrayCardInfo[];
  billTrayIds: Set<string>;
  today: string;
}): Tile[] {
  const { data, bills, billsLoaded, trays, billTrayIds, today } = input;
  const stats = data.inbox_stats;
  const tiles: Tile[] = [];

  // To file
  tiles.push({
    id: "to-file",
    label: "To file",
    value: String(stats.count),
    note:
      stats.count === 0
        ? "The inbox is empty"
        : stats.oldest_days === null
          ? "In the inbox"
          : `oldest from ${shortCalendarDate(addDays(today, -stats.oldest_days), today)}`,
    tone: stats.count === 0 ? "muted" : "normal",
    to: "/inbox",
  });

  // Overdue: the bills' amounts; the other trays' overdue items counted
  const late = bills.filter((b) => b.item.date !== null && b.item.date < today);
  const overdueOther = data.overview.trays
    .filter((t) => !billTrayIds.has(t.tray_id))
    .reduce((n, t) => n + t.overdue, 0);
  const lateNotes: string[] = [];
  if (late.length > 0) {
    const days = daysBetween(late[0].item.date!, today); // the list is by due date: the oldest first
    lateNotes.push(`${plural(late.length, "bill")}, ${plural(days, "day")} late`);
  }
  if (overdueOther > 0) lateNotes.push(plural(overdueOther, "other item"));
  if (stats.overdue > 0) lateNotes.push(`${stats.overdue} in the inbox`);
  const lateAny = late.length + overdueOther + stats.overdue > 0;
  const firstTray = bills[0]?.tray.id ?? [...billTrayIds][0];
  tiles.push({
    id: "overdue",
    label: "Overdue",
    value: !billsLoaded && billTrayIds.size > 0 ? "…" : late.length > 0 ? formatMoney(sumOfBills(late)) : String(overdueOther + stats.overdue),
    note: lateNotes.length > 0 ? lateNotes.join(" · ") : "Nothing overdue",
    tone: lateAny ? "red" : "muted",
    to: late.length > 0 ? `/trays/${encodeURIComponent(late[0].tray.id)}?item=${late[0].item.id}` : firstTray ? `/trays/${encodeURIComponent(firstTray)}` : "/trays",
  });

  // Due in 14 days (not yet late)
  if (billTrayIds.size > 0) {
    const soon = bills.filter(
      (b) => b.item.date !== null && b.item.date >= today && daysBetween(today, b.item.date) <= DUE_WINDOW_DAYS,
    );
    tiles.push({
      id: "due",
      label: `Due in ${DUE_WINDOW_DAYS} days`,
      value: !billsLoaded ? "…" : formatMoney(sumOfBills(soon)),
      note: soon.length > 0 ? plural(soon.length, "bill") : "No bills due",
      tone: soon.length > 0 ? "normal" : "muted",
      to: `/trays/${encodeURIComponent(soon[0]?.tray.id ?? firstTray)}`,
    });
  }

  // Waiting on others (Follow up): how many, and when the next is due
  const waiting = trays.filter(isWaitingTray);
  if (waiting.length > 0) {
    const open = waiting.reduce((n, t) => n + (t.count?.open ?? 0), 0);
    const overdue = waiting.reduce((n, t) => n + (t.count?.overdue ?? 0), 0);
    const rows = waiting.flatMap((t) =>
      trayRows(
        t,
        data.attention.filter((a) => a.tray === t.id),
        data.open_items.find((o) => o.tray_id === t.id)?.items ?? [],
      ),
    );
    const next = rows
      .map((r) => r.item.date)
      .filter((d): d is string => d !== null && d >= today)
      .sort()[0];
    let note = waiting.map((t) => visible(t.name)).join(", ");
    if (overdue > 0) note += `, ${overdue} overdue`;
    else if (next) {
      const when = urgency(next, today).text;
      note += `, next ${when}`;
    }
    tiles.push({
      id: "waiting",
      label: "Waiting on others",
      value: String(open),
      note,
      tone: open === 0 ? "muted" : "normal",
      to: `/trays/${encodeURIComponent(waiting[0].id)}`,
    });
  }
  return tiles;
}

/** "3 open · 186,30 €" beside a tray's name. */
export const openLine = (open: number, sum: string | null) =>
  `${open} open${sum !== null ? ` · ${formatMoney(sum)}` : ""}`;
