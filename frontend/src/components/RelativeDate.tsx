import { useEffect, useState } from "react";
import { formatDate, localToday } from "../format";
import { visible } from "../text";

const clockKey = (now = new Date()) => `${localToday(now)} ${now.getHours()}`;

/** The local date and hour, kept current: checked every minute and when the window
 * gets focus, so a page left open moves on (it re-renders only when the hour changes). */
export function useLocalClock(): { today: string; hour: number } {
  const [key, setKey] = useState(() => clockKey());
  useEffect(() => {
    const update = () => setKey(clockKey());
    const timer = setInterval(update, 60_000);
    window.addEventListener("focus", update);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", update);
    };
  }, []);
  const [today, hour] = key.split(" ");
  return { today, hour: Number(hour) };
}

/** The local date, kept current (see ``useLocalClock``): a page left open overnight
 * moves on to the new day. */
export function useLocalToday(): string {
  return useLocalClock().today;
}

const DAY_MS = 86_400_000;
const utcDay = (iso: string) => Date.parse(`${iso}T00:00:00Z`);

/** "today", "tomorrow", "in 3 days", "yesterday", "4 days ago" (past dates get the
 * ``overdue`` class); the absolute date is in ``title``. ``today`` defaults to the local
 * date (tests pass a fixed one). */
export function RelativeDate({ date, today = localToday() }: { date: string; today?: string }) {
  const days = Math.round((utcDay(date) - utcDay(today)) / DAY_MS);
  let text: string;
  if (Number.isNaN(days)) text = visible(date);
  else if (days === 0) text = "today";
  else if (days === 1) text = "tomorrow";
  else if (days === -1) text = "yesterday";
  else if (days > 1) text = `in ${days} days`;
  else text = `${-days} days ago`;
  return (
    <time dateTime={date} title={visible(formatDate(date))} className={days < 0 ? "overdue" : undefined}>
      {text}
    </time>
  );
}
