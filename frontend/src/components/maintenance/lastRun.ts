/** When each check last ended in this browser (``dam.maintenance.ran.v1``, per archive), so
 * a check's row can say "3 groups found · today 14:10". The server keeps a check's result
 * but not when it ended, so this is only what this browser saw. Every storage access is in
 * try/catch: private windows and blocked site data throw. */
import { archiveKey, type MaintenanceKind } from "../../api/client";
import { clockTime, dayWord, localToday, shortWhen } from "../../format";

export const RAN_KEY = "dam.maintenance.ran.v1";

function read(): Record<string, number> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(archiveKey(RAN_KEY)) ?? "{}");
    if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([, v]) => typeof v === "number"));
  } catch {
    return {};
  }
}

function write(ran: Record<string, number>) {
  try {
    if (Object.keys(ran).length === 0) localStorage.removeItem(archiveKey(RAN_KEY));
    else localStorage.setItem(archiveKey(RAN_KEY), JSON.stringify(ran));
  } catch {
    // Not saved: the time is only missing after a reload.
  }
}

/** When the check last ended here (epoch milliseconds), or null. */
export const lastRun = (kind: MaintenanceKind): number | null => read()[kind] ?? null;

export function noteRun(kind: MaintenanceKind, at = Date.now()) {
  write({ ...read(), [kind]: at });
}

/** Forgets one check's time, or every check's. */
export function forgetRun(kind?: MaintenanceKind) {
  if (!kind) return write({});
  const { [kind]: _gone, ...rest } = read();
  write(rest);
}

/** "today 14:10", "yesterday 08:50" or "15 Oct, 14:10". */
export function ranText(at: number, now = new Date()): string {
  const when = new Date(at);
  const word = dayWord(localToday(when), localToday(now));
  return word ? `${word} ${clockTime(when)}` : shortWhen(when);
}
