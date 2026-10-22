/** The coloured date tag on bill and action rows: red overdue, orange within
 * ``SOON_DAYS`` (as the API's "soon" level), grey later. */
import { formatDate } from "../format";
import { visible } from "../text";
import { Tag, type TagTone } from "./ui/Tag";

/** Matches the API's ``SOON_DAYS`` (dam/services/today.py). */
export const SOON_DAYS = 3;

const DAY_MS = 86_400_000;
const utcDay = (iso: string) => (/^\d{4}-\d{2}-\d{2}$/.test(iso) ? Date.parse(`${iso}T00:00:00Z`) : Number.NaN);
const SHORT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const SHORT_YEAR = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

export type Urgency = { text: string; tone: Extract<TagTone, "red" | "orange" | "grey"> };

/** "4 days overdue" (red), "today" / "tomorrow" / "in 3 days" (orange), "12 Nov" or
 * "5 Jan 2027" (grey); a date it cannot read is shown as it is, grey. */
export function urgency(date: string, today: string): Urgency {
  const days = Math.round((utcDay(date) - utcDay(today)) / DAY_MS);
  if (Number.isNaN(days)) return { text: visible(date), tone: "grey" };
  if (days < 0) return { text: `${-days} ${days === -1 ? "day" : "days"} overdue`, tone: "red" };
  if (days === 0) return { text: "today", tone: "orange" };
  if (days === 1) return { text: "tomorrow", tone: "orange" };
  if (days <= SOON_DAYS) return { text: `in ${days} days`, tone: "orange" };
  const at = new Date(utcDay(date));
  const sameYear = date.slice(0, 4) === today.slice(0, 4);
  return { text: (sameYear ? SHORT : SHORT_YEAR).format(at), tone: "grey" };
}

const PREFIX: Record<Urgency["tone"], string> = { red: "Overdue · ", orange: "", grey: "" };

export function UrgencyTag({ date, today }: { date: string; today: string }) {
  const { text, tone } = urgency(date, today);
  const prefix = tone === "orange" ? (text === "today" ? "Today · " : "Soon · ") : PREFIX[tone];
  return (
    <Tag tone={tone} title={`${prefix}${visible(formatDate(date))}`}>
      {text}
    </Tag>
  );
}
