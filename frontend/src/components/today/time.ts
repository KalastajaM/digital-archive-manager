/** Day arithmetic and "how long it waited" for Today's cards (local "YYYY-MM-DD" dates). */
import { plural } from "../../format";

export const DAY_MS = 86_400_000;

/** Whole days from ``from`` to ``to`` (both "YYYY-MM-DD"). */
export const daysBetween = (from: string, to: string) =>
  Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS);

/** How long something has waited: "today", "3 days", "3 weeks", "4 months". */
export function waited(days: number): string {
  if (days <= 0) return "today";
  if (days < 14) return plural(days, "day");
  if (days < 60) return plural(Math.floor(days / 7), "week");
  return plural(Math.floor(days / 30), "month");
}
